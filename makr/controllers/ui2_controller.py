"""UI2 (월재) automation controller."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from typing import Callable

import pyautogui
from tkinter import messagebox

from makr.core.config import UiTwoDelayConfig
from makr.core.tasks import RepeatingTask
from makr.core.state import UI2AutomationState


def _sleep_ms(delay_ms: int) -> None:
    """Sleep for the given milliseconds."""
    delay_sec = max(delay_ms, 0) / 1000
    if delay_sec:
        time.sleep(delay_sec)


class UI2Controller:
    """Controller for UI2 (월재) automation operations."""

    def __init__(
        self,
        entries: dict[str, tuple[tk.Entry, tk.Entry]],
        delay_config: UiTwoDelayConfig,
        status_fn: Callable[[str], None],
        automation_var: tk.BooleanVar,
        test_new_channel_var: tk.BooleanVar,
    ) -> None:
        self.entries = entries
        self.delay_config = delay_config
        self.status_fn = status_fn
        self.automation_var = automation_var
        self.test_new_channel_var = test_new_channel_var
        self.state = UI2AutomationState()
        self.repeater_f5 = RepeatingTask(status_fn)
        self.repeater_f6 = RepeatingTask(status_fn)
        self.f4_automation_task = RepeatingTask(status_fn)

        # Callbacks set by the application
        self.on_start_new_set: Callable[[], None] | None = None
        self.on_finish_set: Callable[[str, str | None], None] | None = None
        self.on_clear_set_state: Callable[[], None] | None = None
        self.run_on_ui: Callable[[str, Callable[[], None]], None] | None = None

    def _get_point(self, key: str, label: str) -> tuple[int, int] | None:
        """Get coordinates from entry widgets."""
        if key not in self.entries:
            return None
        x_entry, y_entry = self.entries[key]
        try:
            x_val = int(x_entry.get())
            y_val = int(y_entry.get())
        except ValueError:
            messagebox.showerror("좌표 오류", f"{label} 좌표를 정수로 입력해주세요.")
            return None
        return x_val, y_val

    def _build_f4_action(self) -> Callable[[], None] | None:
        """Build the F4 action callable."""
        pos11 = self._get_point("pos11", "···")
        pos12 = self._get_point("pos12", "🔃")
        if pos11 is None or pos12 is None:
            return None
        delay_between = self.delay_config.f4_between_pos11_pos12()
        delay_before_enter = self.delay_config.f4_before_enter()

        def _run() -> None:
            pyautogui.click(*pos11)
            _sleep_ms(delay_between)
            pyautogui.click(*pos12)
            _sleep_ms(delay_before_enter)
            pyautogui.press("enter")

        return _run

    def run_f4_batch(
        self,
        action: Callable[[], None],
        *,
        repeat_count: int = 10,
        interval_sec: float = 0.2,
        start_message: str | None = None,
        stop_message: str | None = None,
    ) -> None:
        """Run F4 action in a batch."""
        if start_message:
            self.status_fn(start_message)

        def _run() -> None:
            for idx in range(max(repeat_count, 1)):
                action()
                if idx < repeat_count - 1:
                    time.sleep(max(interval_sec, 0))
            if stop_message:
                self.status_fn(stop_message)

        threading.Thread(target=_run, daemon=True).start()

    def stop_automation(self, message: str | None = None) -> None:
        """Stop all automation."""
        self.state.reset()
        if self.on_clear_set_state:
            self.on_clear_set_state()
        self.f4_automation_task.stop()
        if self.repeater_f5.stop():
            self.status_fn("F5: 중지되었습니다.")
        if self.repeater_f6.stop():
            self.status_fn("F6: 중지되었습니다.")
        if message:
            self.status_fn(message)

    def start_automation(self) -> None:
        """Start UI2 automation."""
        if self.state.active:
            self.status_fn("자동화 모드: 이미 실행 중입니다.")
            return
        if self.repeater_f5.stop():
            self.status_fn("F5: 중지되었습니다.")
        if self.repeater_f6.stop():
            self.status_fn("F6: 중지되었습니다.")
        self.state.start_automation()
        action = self._build_f4_action()
        if action is None:
            return
        if self.on_start_new_set:
            self.on_start_new_set()
        self.run_f4_batch(action)

    def restart_f4_cycle(self) -> None:
        """Restart the F4 cycle."""
        action = self._build_f4_action()
        if action is None:
            return
        self.state.start_automation()
        if self.on_start_new_set:
            self.on_start_new_set()
        self.run_f4_batch(action)

    def restart_f4_logic(self) -> None:
        """Restart just the F4 logic."""
        action = self._build_f4_action()
        if action is None:
            return
        if self.on_start_new_set:
            self.on_start_new_set()
        self.run_f4_batch(action)

    def run_f4(self) -> None:
        """Handle F4 key press."""
        if self.automation_var.get():
            self.start_automation()
            return

        if self.f4_automation_task.stop():
            self.status_fn("자동화 모드: 중지되었습니다.")
        action = self._build_f4_action()
        if action is None:
            return
        if self.repeater_f6.stop():
            self.status_fn("F6 반복 클릭을 중지했습니다.")
        self.run_f4_batch(
            action,
            start_message="F4: 10회 실행 중…",
            stop_message="F4: 실행 완료",
        )

    def run_f5(self) -> None:
        """Handle F5 key press."""
        pos13 = self._get_point("pos13", "로그인")
        if pos13 is None:
            return
        interval_ms = self.delay_config.f5_interval()
        self.repeater_f5.start_click(
            pos13,
            interval_ms,
            start_message="F5: 로그인 반복 클릭 시작",
            stop_message="F5: 중지되었습니다.",
        )

    def run_f6(self, *, force_start: bool = False) -> None:
        """Handle F6 key press."""
        if self.repeater_f6.is_running and not force_start:
            self.repeater_f6.stop(stop_message="F6: 중지되었습니다.")
            return
        if self.repeater_f6.is_running and force_start:
            self.repeater_f6.stop(stop_message="F6: 중지되었습니다.")

        pos14 = self._get_point("pos14", "캐릭터")
        if pos14 is None:
            return
        interval_ms = self.delay_config.f6_interval()
        if self.repeater_f5.stop():
            self.status_fn("F5: 중지되었습니다.")
        self.repeater_f6.start_click(
            pos14,
            interval_ms,
            start_message="F6: 캐릭터 반복 클릭 시작",
            stop_message="F6: 중지되었습니다.",
        )

    def start_normal_channel_sequence(self) -> None:
        """Start the normal channel sequence (F5)."""
        if self.run_on_ui:
            self.run_on_ui("2", self.run_f5)
