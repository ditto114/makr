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
