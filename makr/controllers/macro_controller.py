"""Macro controller for UI1 (채변) operations."""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Protocol

import pyautogui
from tkinter import messagebox

from makr.core.config import DelayConfig


class CoordinateProvider(Protocol):
    """Protocol for providing coordinates by key."""

    def get_point(self, key: str) -> tuple[int, int] | None:
        """Get coordinates for the given key."""
        ...


class EntryCoordinateProvider:
    """Coordinate provider using tkinter Entry widgets."""

    def __init__(
        self,
        entries: dict[str, tuple[tk.Entry, tk.Entry]],
        label_map: dict[str, str],
    ) -> None:
        self.entries = entries
        self.label_map = label_map

    def get_point(self, key: str) -> tuple[int, int] | None:
        """Get coordinates from entry widgets."""
        if key not in self.entries:
            return None
        x_entry, y_entry = self.entries[key]
        label = self.label_map.get(key, key)
        try:
            x_val = int(x_entry.get())
            y_val = int(y_entry.get())
        except ValueError:
            messagebox.showerror("좌표 오류", f"{label} 좌표를 정수로 입력해주세요.")
            return None
        return x_val, y_val


class MacroController:
    """Controls the execution sequence for UI1 macros."""

    def __init__(
        self,
        entries: dict[str, tuple[tk.Entry, tk.Entry]],
        status_var: tk.StringVar,
        delay_config: DelayConfig,
        label_map: dict[str, str],
        use_esc_click: Callable[[], bool],
    ) -> None:
        self.entries = entries
        self.status_var = status_var
        self.current_step = 1
        self.delay_config = delay_config
        self.label_map = label_map
        self.use_esc_click = use_esc_click
        self._coordinate_provider = EntryCoordinateProvider(entries, label_map)
        self._update_status()

    def _update_status(self) -> None:
        """Update the status display with current step."""
        self.status_var.set(f"다음 실행 단계: {self.current_step}단계")

    def _get_point(self, key: str) -> tuple[int, int] | None:
        """Get coordinates for the given key."""
        return self._coordinate_provider.get_point(key)

    def _click_point(self, point: tuple[int, int], *, label: str | None = None) -> None:
        """Click at the given point."""
        x_val, y_val = point
        pyautogui.click(x_val, y_val)

    def _press_key(self, key: str, *, label: str | None = None) -> None:
        """Press the given keyboard key."""
        pyautogui.press(key)

    def _delay_seconds(self, delay_ms: int) -> float:
        """Convert milliseconds to seconds."""
        return max(delay_ms, 0) / 1000

    def _sleep_ms(self, delay_ms: int) -> None:
        """Sleep for the given milliseconds."""
        delay_sec = self._delay_seconds(delay_ms)
        if delay_sec:
            time.sleep(delay_sec)

    def run_step(self, *, newline_mode: bool = False) -> None:
        """Execute the current step and advance to the next."""
        if self.current_step == 1:
            self._run_step_one()
            self.current_step = 2
        else:
            self._run_step_two(newline_mode=newline_mode)
            self.current_step = 1
        self._update_status()

    def reset_and_run_first(self, *, newline_mode: bool = False) -> None:
        """Reset with Esc and re-run step 1."""
        self._sleep_ms(self.delay_config.f2_before_esc())
        if self.use_esc_click():
            esc_point = self._get_point("esc_click")
            if esc_point is None:
                return
            self._click_point(esc_point, label="초기화 Esc 클릭")
        else:
            self._press_key("esc", label="초기화 ESC")
        self.current_step = 1
        self._update_status()
        self._run_step_one()
        self.current_step = 2
        self._update_status()

    def _run_step_one(self) -> None:
        """Execute step 1: click pos1 then pos2."""
        pos1 = self._get_point("pos1")
        pos2 = self._get_point("pos2")
        if pos1 is None or pos2 is None:
            return
        self._sleep_ms(self.delay_config.f2_before_pos1())
        self._click_point(pos1, label="1단계 pos1")
        self._sleep_ms(self.delay_config.f2_before_pos2())
        self._click_point(pos2, label="1단계 pos2")

    def _run_step_two(self, *, newline_mode: bool = False) -> None:
        """Execute step 2: click pos3 and enter, with optional newline mode."""
        pos3 = self._get_point("pos3")
        if pos3 is None:
            return
        repeat_count = max(self.delay_config.f1_repeat_count(), 1)
        if newline_mode:
            pos4 = self._get_point("pos4")
            if pos4 is None:
                return
        for _ in range(repeat_count):
            if newline_mode:
                self._sleep_ms(self.delay_config.f1_newline_before_pos4())
                self._click_point(pos4, label="2단계 pos4")
                self._sleep_ms(self.delay_config.f1_newline_before_pos3())
            else:
                self._sleep_ms(self.delay_config.f1_before_pos3())
            self._click_point(pos3, label="2단계 pos3")
            self._sleep_ms(
                self.delay_config.f1_newline_before_enter()
                if newline_mode
                else self.delay_config.f1_before_enter()
            )
            self._press_key("enter", label="2단계 Enter")
