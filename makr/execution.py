"""매크로 실행 로직."""
from __future__ import annotations

import select
import socket
import time
from dataclasses import dataclass, field
from typing import List, Optional

from PIL import Image

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
    if condition_type == "image":
        if pyautogui is None:
            raise ExecutionError("pyautogui를 사용할 수 없습니다. GUI 환경을 확인하세요.")
        image_path = config.get("image_path")
        if not image_path:
            raise ExecutionError("이미지 경로가 지정되지 않았습니다.")
        timeout = float(config.get("timeout", 30))
        interval = float(config.get("interval", 0.5))
        confidence = _resolve_confidence(config)
        reference_image = _prepare_image(image_path)
        context.log.add(f"- 이미지 인식 대기: {image_path}")
        start = time.time()
        while True:
            location = _locate_image(reference_image, confidence)
            if location:
                context.log.add(f"- 이미지 인식 성공: {location}")
                return True
            if timeout > 0 and (time.time() - start) >= timeout:
                context.log.add("- 이미지 인식 시간 초과")
                return False
            time.sleep(max(interval, 0.1))
    if condition_type == "packet":
        ip = (config.get("ip") or "").strip()
        detect_text = config.get("detect_text", "")
        if not ip:
            raise ExecutionError("패킷 감지 IP가 설정되지 않았습니다.")
        try:
            port = int(config.get("port"))
        except (TypeError, ValueError) as exc:
            raise ExecutionError("패킷 감지 포트가 올바르지 않습니다.") from exc
        timeout = float(config.get("timeout", 0.0))
        if not detect_text:
            raise ExecutionError("감지할 문자열을 입력하세요.")
        detect_bytes = detect_text.encode("utf-8")
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
                    if detect_bytes in buffer:
                        context.log.add("- 감지 문자열이 수신되었습니다.")
                        return True
                    # 버퍼 크기 제한 (1MB 초과 시 뒤쪽만 유지)
                    if len(buffer) > 1_048_576:
                        del buffer[: len(buffer) - 1024]
        except OSError as exc:
            raise ExecutionError(f"패킷 감지 연결 실패: {exc}") from exc
    raise ExecutionError(f"지원되지 않는 조건 유형: {condition_type}")


def _execute_action(node: MacroNode, context: ExecutionContext) -> None:
    config = node.config
    action_type = config.get("type")
    if pyautogui is None and action_type in {"mouse_click", "keyboard", "image_click"}:
        raise ExecutionError("pyautogui를 사용할 수 없습니다. GUI 환경을 확인하세요.")

    if action_type == "mouse_click":
        mode = config.get("mode", "coordinates")
        clicks = int(config.get("clicks", 1))
        interval = float(config.get("interval", 0.1))
        button = config.get("button", "left")
        if mode == "coordinates":
            x = config.get("x")
            y = config.get("y")
            if x is None or y is None:
                raise ExecutionError("마우스 클릭 좌표가 설정되지 않았습니다.")
            pyautogui.click(x=int(x), y=int(y), clicks=clicks, interval=interval, button=button)
            context.log.add(f"- 좌표({x}, {y}) 클릭")
            return
        if mode == "image":
            image_path = config.get("image_path")
            confidence = _resolve_confidence(config)
            reference_image = _prepare_image(image_path)
            location = _locate_image(reference_image, confidence)
            if not location:
                raise ExecutionError("이미지를 찾을 수 없습니다: %s" % image_path)
            center = pyautogui.center(location)
            try:
                offset_x = int(config.get("offset_x", 0))
            except (TypeError, ValueError):
                offset_x = 0
            try:
                offset_y = int(config.get("offset_y", 0))
            except (TypeError, ValueError):
                offset_y = 0
            click_x = center.x + offset_x
            click_y = center.y + offset_y
            pyautogui.click(click_x, click_y, clicks=clicks, interval=interval, button=button)
            context.log.add(
                f"- 이미지 클릭: {image_path} (좌표 {click_x}, {click_y}, 오프셋 {offset_x}, {offset_y})"
            )
            return
        raise ExecutionError(f"지원되지 않는 마우스 클릭 모드: {mode}")

    if action_type == "keyboard":
        text = config.get("text", "")
        interval = float(config.get("interval", 0.05))
        press_enter = bool(config.get("press_enter", False))
        context.log.add(f"- 키보드 입력: {text}")
        if text:
            pyautogui.typewrite(text, interval=interval)
        if press_enter:
            pyautogui.press("enter")
        return

    if action_type == "image_click":
        image_path = config.get("image_path")
        confidence = _resolve_confidence(config)
        clicks = int(config.get("clicks", 1))
        interval = float(config.get("interval", 0.1))
        button = config.get("button", "left")
        reference_image = _prepare_image(image_path)
        location = _locate_image(reference_image, confidence)
        if not location:
            raise ExecutionError(f"이미지를 찾을 수 없습니다: {image_path}")
        center = pyautogui.center(location)
        pyautogui.click(center.x, center.y, clicks=clicks, interval=interval, button=button)
        context.log.add(f"- 이미지 위치 클릭: {image_path}")
        return

    raise ExecutionError(f"지원되지 않는 행동 유형: {action_type}")


def _locate_image(reference_image: Image.Image, confidence: Optional[float]):
    if pyautogui is None:
        raise ExecutionError("pyautogui를 사용할 수 없습니다. GUI 환경을 확인하세요.")
    try:
        if confidence is not None:
            return pyautogui.locateOnScreen(reference_image, confidence=float(confidence))
        return pyautogui.locateOnScreen(reference_image)
    except Exception as exc:  # pragma: no cover - pyautogui 내부 예외 처리
        # PyAutoGUI는 찾지 못한 경우 ImageNotFoundException을 던질 수 있으므로
        # 이를 시간 초과 루프로 처리할 수 있도록 None을 반환한다.
        image_not_found_exc = getattr(pyautogui, "ImageNotFoundException", None)
        if image_not_found_exc and isinstance(exc, image_not_found_exc):
            return None
        if exc.__class__.__name__ == "ImageNotFoundException":
            return None
        raise ExecutionError(f"이미지 검색 중 오류: {exc}")


def _prepare_image(image_path: Optional[str]) -> Image.Image:
    if not image_path:
        raise ExecutionError("이미지 경로가 설정되지 않았습니다.")
    try:
        with Image.open(image_path) as source:
            return source.copy()
    except FileNotFoundError:
        raise ExecutionError(f"이미지를 찾을 수 없습니다: {image_path}")
    except Exception as exc:  # pragma: no cover - Pillow 내부 예외 처리
        raise ExecutionError(f"이미지를 불러오는 중 오류: {exc}")


def _resolve_confidence(config: dict, default: float = 0.8) -> float:
    value = config.get("confidence")
    if value is None or value == "":
        return default
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"인식 정확도 값이 올바르지 않습니다: {exc}")
    if not 0 <= confidence <= 1:
        raise ExecutionError("인식 정확도는 0과 1 사이여야 합니다.")
    return confidence
