"""Unified repeating task implementation."""

from __future__ import annotations

import threading
from typing import Callable

import pyautogui


class RepeatingTask:
    """Unified repeating task that can perform clicks or custom actions."""

    def __init__(self, status_fn: Callable[[str], None]) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._status_fn = status_fn

    def start(
        self,
        action: Callable[[], None],
        interval_sec: float,
        *,
        start_message: str,
        stop_message: str,
    ) -> None:
        """Start the repeating task with a custom action."""
        self.stop()
        self._stop_event.clear()

        def _run() -> None:
            self._status_fn(start_message)
            try:
                while not self._stop_event.is_set():
                    action()
                    if self._stop_event.wait(max(interval_sec, 0)):
                        break
            finally:
                self._status_fn(stop_message)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def start_click(
        self,
        point: tuple[int, int],
        delay_ms: int,
        *,
        start_message: str,
        stop_message: str,
    ) -> None:
        """Start the repeating task with mouse clicks."""
        delay_sec = max(delay_ms, 0) / 1000

        def click_action() -> None:
            pyautogui.click(*point)

        self.start(
            click_action,
            delay_sec,
            start_message=start_message,
            stop_message=stop_message,
        )

    def stop(self, *, stop_message: str | None = None) -> bool:
        """Stop the repeating task. Returns True if it was running."""
        if not self.is_running:
            return False
        self._stop_event.set()
        if stop_message:
            self._status_fn(stop_message)
        return True

    @property
    def is_running(self) -> bool:
        """Check if the task is currently running."""
        return self._thread is not None and self._thread.is_alive()


# Backward compatibility aliases
class RepeatingClickTask(RepeatingTask):
    """Backward compatible class for click-specific repeating tasks."""

    def start(  # type: ignore[override]
        self,
        point: tuple[int, int],
        delay_ms: int,
        *,
        start_message: str,
        stop_message: str,
    ) -> None:
        """Start repeating clicks at the given point."""
        self.start_click(
            point,
            delay_ms,
            start_message=start_message,
            stop_message=stop_message,
        )


class RepeatingActionTask(RepeatingTask):
    """Backward compatible class for action-specific repeating tasks."""

    pass
