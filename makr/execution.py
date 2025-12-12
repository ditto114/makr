"""매크로 실행 로직."""
from __future__ import annotations

import select
import socket
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .macro import Macro, MacroNode

try:
    import pyautogui
except Exception:  # pragma: no cover - 런타임 환경이 GUI를 제공하지 않는 경우 대비
    pyautogui = None  # type: ignore


class ExecutionError(RuntimeError):
    """매크로 실행 중 발생한 오류."""


@dataclass
class ExecutionLog:
    """실행 과정 로그."""

    lines: List[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.lines.append(f"[{timestamp}] {message}")


@dataclass
class ExecutionContext:
    """실행 상태 및 부가 정보."""

    log: ExecutionLog = field(default_factory=ExecutionLog)
    stop_requested: bool = False

    def request_stop(self) -> None:
        self.stop_requested = True
        self.log.add("사용자 중지 요청 수신")


def execute_macro(macro: Macro, context: Optional[ExecutionContext] = None) -> ExecutionLog:
    """매크로를 실행한다."""
    context = context or ExecutionContext()
    context.log.add(f"매크로 실행 시작: {macro.name}")
    for node in macro.nodes:
        _execute_node(node, context)
        if context.stop_requested:
            context.log.add("매크로 실행이 중지되었습니다.")
            break
    else:
        context.log.add("매크로 실행 완료")
    return context.log


def _execute_node(node: MacroNode, context: ExecutionContext) -> None:
    if context.stop_requested:
        return
    if node.kind == "condition":
        context.log.add(f"조건 평가 시작: {node.title}")
        if not _evaluate_condition(node, context):
            raise ExecutionError(f"조건 미충족: {node.title}")
        context.log.add(f"조건 달성: {node.title}")
    elif node.kind == "action":
        context.log.add(f"행동 실행: {node.title}")
        _execute_action(node, context)
    elif node.kind == "loop":
        repeat = int(node.config.get("repeat", 1))
        context.log.add(f"반복 블럭 시작 ({repeat}회): {node.title}")
        for iteration in range(repeat):
            if context.stop_requested:
                break
            context.log.add(f"- 반복 {iteration + 1}/{repeat}")
            for child in node.children:
                _execute_node(child, context)
                if context.stop_requested:
                    break
        context.log.add("반복 블럭 종료: %s" % node.title)
    else:
        raise ExecutionError(f"알 수 없는 노드 종류: {node.kind}")


def _evaluate_condition(node: MacroNode, context: ExecutionContext) -> bool:
    config = node.config
    condition_type = config.get("type")
    if condition_type == "wait":
        seconds = float(config.get("seconds", 1))
        context.log.add(f"- {seconds}초 대기")
        time.sleep(max(seconds, 0))
        return True
    if condition_type == "packet":
        ip = (config.get("ip") or "").strip()
        try:
            port = int(config.get("port", 32800))
        except (TypeError, ValueError) as exc:
            raise ExecutionError("패킷 감지 포트가 올바르지 않습니다.") from exc
        timeout = float(config.get("timeout", 0.0))
        detect_text = (config.get("detect_text") or "").strip()
        if not ip:
            raise ExecutionError("패킷 감지 IP가 설정되지 않았습니다.")
        detect_bytes = detect_text.encode("utf-8") if detect_text else b""
        context.log.add(
            f"- 패킷 감지 시작: {ip}:{port}, 타임아웃 {timeout if timeout > 0 else '무제한'}초"
        )
        deadline = time.time() + timeout if timeout > 0 else None
        buffer = bytearray()
        connection_timeout = min(max(timeout, 0.0), 5.0) if timeout > 0 else 5.0
        try:
            with socket.create_connection((ip, port), timeout=connection_timeout or None) as sock:
                sock.setblocking(False)
                while True:
                    if context.stop_requested:
                        context.log.add("- 패킷 감지가 중지 요청으로 종료되었습니다.")
                        return False
                    if deadline is not None and time.time() >= deadline:
                        context.log.add("- 패킷 감지 타임아웃")
                        return False
                    wait_timeout = 0.5
                    if deadline is not None:
                        remaining = max(deadline - time.time(), 0.0)
                        wait_timeout = min(max(remaining, 0.0), 0.5)
                    ready, _, _ = select.select([sock], [], [], wait_timeout)
                    if not ready:
                        continue
                    try:
                        chunk = sock.recv(4096)
                    except BlockingIOError:
                        continue
                    except OSError as exc:
                        raise ExecutionError(f"패킷 수신 중 오류: {exc}") from exc
                    if not chunk:
                        context.log.add("- 패킷 감지 대상 연결이 종료되었습니다.")
                        return False
                    buffer.extend(chunk)
                    decoded_text = None
                    if port == 32800:
                        try:
                            decoded_text = buffer.decode("utf-8")
                        except UnicodeDecodeError:
                            decoded_text = buffer.decode("utf-8", errors="ignore")
                    if decoded_text is not None:
                        if detect_text:
                            if detect_text in decoded_text:
                                context.log.add(f"- UTF-8 내용에서 감지 문자열 발견: {detect_text}")
                                context.log.add(f"- 수신 내용: {decoded_text}")
                                return True
                        elif decoded_text:
                            context.log.add(f"- 포트 32800 수신 내용: {decoded_text}")
                            return True
                    if detect_bytes and detect_bytes in buffer:
                        context.log.add("- 감지 문자열이 수신되었습니다.")
                        return True
                    if len(buffer) > 1_048_576:
                        del buffer[: len(buffer) - 1024]
        except OSError as exc:
            raise ExecutionError(f"패킷 감지 연결 실패: {exc}") from exc
    raise ExecutionError(f"지원되지 않는 조건 유형: {condition_type}")

def _execute_action(node: MacroNode, context: ExecutionContext) -> None:
    config = node.config
    action_type = config.get("type")
    if pyautogui is None:
        raise ExecutionError("pyautogui를 사용할 수 없습니다. GUI 환경을 확인하세요.")

    if action_type == "mouse_click":
        clicks = int(config.get("clicks", 1))
        interval = float(config.get("interval", 0.1))
        button = config.get("button", "left")
        x = config.get("x")
        y = config.get("y")
        if x is None or y is None:
            raise ExecutionError("마우스 클릭 좌표가 설정되지 않았습니다.")
        pyautogui.click(x=int(x), y=int(y), clicks=clicks, interval=interval, button=button)
        context.log.add(f"- 좌표({x}, {y}) 클릭")
        return

    if action_type == "keyboard":
        text_to_type = config.get("text", "")
        interval = float(config.get("interval", 0.05))
        press_enter = bool(config.get("press_enter", False))
        context.log.add(f"- 키보드 입력: {text_to_type}")
        if text_to_type:
            pyautogui.typewrite(text_to_type, interval=interval)
        if press_enter:
            pyautogui.press("enter")
        return

    raise ExecutionError(f"지원되지 않는 행동 유형: {action_type}")
