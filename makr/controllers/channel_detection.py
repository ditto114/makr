"""Channel detection sequence for F10 macro."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from queue import Empty, Queue
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from makr.controllers.macro_controller import MacroController


class ChannelDetectionSequence:
    """Manages the F10 channel detection sequence."""

    def __init__(
        self,
        root: tk.Tk,
        status_var: tk.StringVar,
        controller: "MacroController",
        get_channel_timeout_ms: Callable[[], int],
        get_channel_watch_interval_ms: Callable[[], int],
    ) -> None:
        self.root = root
        self.status_var = status_var
        self.controller = controller
        self.get_channel_timeout_ms = get_channel_timeout_ms
        self.get_channel_watch_interval_ms = get_channel_watch_interval_ms
        self.running = False
        self.detection_queue: Queue[tuple[float, bool]] = Queue()
        self.newline_mode = False
        self.last_detected_at: float | None = None

    def start(self, newline_mode: bool) -> None:
        """Start the detection sequence."""
        from tkinter import messagebox

        if self.running:
            messagebox.showinfo("매크로", "F10 매크로가 이미 실행 중입니다.")
            return
        self.running = True
        self._clear_queue()
        self.newline_mode = newline_mode
        self.last_detected_at = None
        threading.Thread(target=self._run_sequence, daemon=True).start()

    def stop(self) -> None:
        """Stop the detection sequence."""
        self.running = False
        self._clear_queue()
        self.last_detected_at = None

    def notify_channel_found(
        self, *, detected_at: float | None = None, is_new: bool
    ) -> None:
        """Notify that a channel was found."""
        if not self.running:
            return
        timestamp = detected_at or time.time()
        self.detection_queue.put((timestamp, is_new))

    def _run_on_main(self, func: Callable[[], None]) -> None:
        """Run a function on the main thread and wait for completion."""
        done = threading.Event()

        def _wrapper() -> None:
            try:
                func()
            finally:
                done.set()

        self.root.after(0, _wrapper)
        done.wait()

    def _set_status(self, message: str) -> None:
        """Set status message asynchronously."""
        self.root.after(0, self.status_var.set, message)

    def _clear_queue(self) -> None:
        """Clear the detection queue."""
        while True:
            try:
                self.detection_queue.get_nowait()
            except Empty:
                break

    def _wait_for_detection(self, timeout_sec: float) -> tuple[float, bool] | None:
        """Wait for a detection event with timeout."""
        if timeout_sec <= 0:
            try:
                return self.detection_queue.get_nowait()
            except Empty:
                return None

        deadline = time.time() + timeout_sec
        while self.running:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                return self.detection_queue.get(timeout=remaining)
            except Empty:
                continue
        return None

    def _delay_seconds(self, delay_ms: int) -> float:
        """Convert milliseconds to seconds."""
        return max(delay_ms, 0) / 1000

    def _run_sequence(self) -> None:
        """Run the main detection sequence."""
        try:
            while self.running:
                self._set_status("F10: F2 기능 실행 중…")
                self._clear_queue()
                self._run_on_main(
                    lambda: self.controller.reset_and_run_first(
                        newline_mode=self.newline_mode
                    )
                )

                self._set_status("F10: 채널명 감시 중…")
                timeout_sec = self._delay_seconds(self.get_channel_timeout_ms())
                first_detection = self._wait_for_detection(timeout_sec)
                self.last_detected_at = first_detection[0] if first_detection else None

                if not self.running:
                    break

                if first_detection is None:
                    self._set_status("F10: 채널명이 발견되지 않았습니다. 재시도합니다…")
                    continue

                first_time, is_new = first_detection
                if is_new:
                    self._set_status("F10: 새 채널명 기록, F1 실행 중…")
                    self._run_on_main(
                        lambda: self.controller.run_step(newline_mode=self.newline_mode)
                    )
                    break

                watch_interval = self._delay_seconds(self.get_channel_watch_interval_ms())
                if watch_interval <= 0:
                    self._set_status("F10: 새 채널명이 없어 재시작합니다…")
                    continue

                deadline = first_time + watch_interval
                new_channel_found = False

                while self.running:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break

                    event = self._wait_for_detection(remaining)
                    if not self.running:
                        break
                    if event is None:
                        break

                    detected_time, event_is_new = event
                    deadline = detected_time + watch_interval
                    self.last_detected_at = detected_time

                    if event_is_new:
                        new_channel_found = True
                        break

                if not self.running:
                    break

                if new_channel_found:
                    self._set_status("F10: 새 채널명 기록, F1 실행 중…")
                    self._run_on_main(
                        lambda: self.controller.run_step(newline_mode=self.newline_mode)
                    )
                    break

                self._set_status("F10: 새 채널명이 없어 재시작합니다…")
        finally:
            self.running = False
            self._run_on_main(self.controller._update_status)
