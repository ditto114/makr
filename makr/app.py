"""단계별 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, F1/F2 단축키로
순차 동작을 제어합니다.
"""

from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from queue import Empty, Queue
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from makr.packet import PacketCaptureManager

import pyautogui
from pynput import keyboard, mouse

APP_STATE_PATH = Path(__file__).with_name("app_state.json")

# pyautogui의 기본 지연(0.1초)을 제거해 클릭 간 딜레이를 사용자 설정값에만 의존하도록 합니다.
pyautogui.PAUSE = 0


def load_app_state() -> dict:
    if not APP_STATE_PATH.exists():
        return {}
    try:
        return json.loads(APP_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_app_state(state: dict) -> None:
    try:
        APP_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        messagebox.showwarning("설정 저장", "입력값을 저장하는 중 오류가 발생했습니다.")


@dataclass
class DelayConfig:
    f2_before_esc: Callable[[], int]
    f2_before_pos1: Callable[[], int]
    f2_before_pos2: Callable[[], int]
    f1_before_pos3: Callable[[], int]
    f1_before_enter: Callable[[], int]
    f1_repeat_count: Callable[[], int]
    f1_newline_before_pos4: Callable[[], int]
    f1_newline_before_pos3: Callable[[], int]
    f1_newline_before_enter: Callable[[], int]


@dataclass
class UiTwoDelayConfig:
    f4_between_pos11_pos12: Callable[[], int]
    f4_before_enter: Callable[[], int]
    f5_interval: Callable[[], int]
    f6_interval: Callable[[], int]


class RepeatingClickTask:
    def __init__(self, status_fn: Callable[[str], None]) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._status_fn = status_fn

    def start(self, point: tuple[int, int], delay_ms: int, *, start_message: str, stop_message: str) -> None:
        self.stop()
        delay_sec = max(delay_ms, 0) / 1000
        self._stop_event.clear()

        def _run() -> None:
            self._status_fn(start_message)
            try:
                while not self._stop_event.is_set():
                    pyautogui.click(*point)
                    if self._stop_event.wait(delay_sec):
                        break
            finally:
                self._status_fn(stop_message)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self, *, stop_message: str | None = None) -> bool:
        if not self.is_running:
            return False
        self._stop_event.set()
        if stop_message:
            self._status_fn(stop_message)
        return True

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class RepeatingActionTask:
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

    def stop(self, *, stop_message: str | None = None) -> bool:
        if not self.is_running:
            return False
        self._stop_event.set()
        if stop_message:
            self._status_fn(stop_message)
        return True

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class MacroController:
    """실행 순서를 관리하고 GUI 콜백을 제공합니다."""

    def __init__(
        self,
        entries: dict[str, tuple[tk.Entry, tk.Entry]],
        status_var: tk.StringVar,
        delay_config: DelayConfig,
    ) -> None:
        self.entries = entries
        self.status_var = status_var
        self.current_step = 1
        self.delay_config = delay_config
        self._update_status()

    def _update_status(self) -> None:
        self.status_var.set(f"다음 실행 단계: {self.current_step}단계")

    def _get_point(self, key: str) -> tuple[int, int] | None:
        x_entry, y_entry = self.entries[key]
        try:
            x_val = int(x_entry.get())
            y_val = int(y_entry.get())
        except ValueError:
            messagebox.showerror("좌표 오류", f"{key} 좌표를 정수로 입력해주세요.")
            return None
        return x_val, y_val

    def _click_point(self, point: tuple[int, int], *, label: str | None = None) -> None:
        x_val, y_val = point
        pyautogui.click(x_val, y_val)

    def _press_key(self, key: str, *, label: str | None = None) -> None:
        pyautogui.press(key)

    def _delay_seconds(self, delay_ms: int) -> float:
        return max(delay_ms, 0) / 1000

    def _sleep_ms(self, delay_ms: int) -> None:
        delay_sec = self._delay_seconds(delay_ms)
        if delay_sec:
            time.sleep(delay_sec)

    def run_step(self, *, newline_mode: bool = False) -> None:
        """실행 단축키 콜백: 현재 단계 수행 후 다음 단계로 이동."""
        if self.current_step == 1:
            self._run_step_one()
            self.current_step = 2
        else:
            self._run_step_two(newline_mode=newline_mode)
            self.current_step = 1
        self._update_status()

    def reset_and_run_first(self, *, newline_mode: bool = False) -> None:
        """다시 단축키 콜백: Esc 입력 후 1단계를 재실행."""
        self._sleep_ms(self.delay_config.f2_before_esc())
        self._press_key("esc", label="초기화 ESC")
        self.current_step = 1
        self._update_status()
        self._run_step_one()
        self.current_step = 2
        self._update_status()

    def _run_step_one(self) -> None:
        pos1 = self._get_point("pos1")
        pos2 = self._get_point("pos2")
        if pos1 is None or pos2 is None:
            return
        self._sleep_ms(self.delay_config.f2_before_pos1())
        self._click_point(pos1, label="1단계 pos1")
        self._sleep_ms(self.delay_config.f2_before_pos2())
        self._click_point(pos2, label="1단계 pos2")

    def _run_step_two(self, *, newline_mode: bool = False) -> None:
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


def build_gui() -> None:
    root = tk.Tk()
    root.title("단계별 자동화")
    root.attributes("-topmost", True)

    saved_state = load_app_state()

    status_var = tk.StringVar()
    devlogic_alert_var = tk.StringVar(value="")
    devlogic_packet_var = tk.StringVar(value="")
    overlay_window: tk.Toplevel | None = None
    overlay_drag_offset: tuple[int, int] = (0, 0)
    try:
        overlay_default_x = int(saved_state.get("overlay_x", 80))
        overlay_default_y = int(saved_state.get("overlay_y", 40))
    except (TypeError, ValueError):
        overlay_default_x, overlay_default_y = 80, 40
    overlay_position: dict[str, int] = {"x": overlay_default_x, "y": overlay_default_y}
    ui_mode = tk.StringVar(value=str(saved_state.get("ui_mode", "1")))
    f2_before_esc_var = tk.StringVar(value=str(saved_state.get("delay_f2_before_esc_ms", "0")))
    f2_before_pos1_var = tk.StringVar(value=str(saved_state.get("delay_f2_before_pos1_ms", "0")))
    f2_before_pos2_var = tk.StringVar(
        value=str(saved_state.get("delay_f2_before_pos2_ms", saved_state.get("click_delay_ms", "100")))
    )
    f1_before_pos3_var = tk.StringVar(value=str(saved_state.get("delay_f1_before_pos3_ms", "0")))
    f1_before_enter_var = tk.StringVar(value=str(saved_state.get("delay_f1_before_enter_ms", "0")))
    f1_repeat_count_var = tk.StringVar(value=str(saved_state.get("f1_repeat_count", "1")))
    f1_newline_before_pos4_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_pos4_ms", "0"))
    )
    f1_newline_before_pos3_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_pos3_ms", "30"))
    )
    f1_newline_before_enter_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_enter_ms", "0"))
    )
    f4_between_pos11_pos12_var = tk.StringVar(
        value=str(saved_state.get("delay_f4_between_pos11_pos12_ms", "0"))
    )
    f4_before_enter_var = tk.StringVar(
        value=str(saved_state.get("delay_f4_before_enter_ms", "0"))
    )
    f5_interval_var = tk.StringVar(value=str(saved_state.get("delay_f5_interval_ms", "100")))
    f6_interval_var = tk.StringVar(value=str(saved_state.get("delay_f6_interval_ms", "100")))
    channel_watch_interval_var = tk.StringVar(
        value=str(saved_state.get("channel_watch_interval_ms", "200"))
    )
    channel_timeout_var = tk.StringVar(value=str(saved_state.get("channel_timeout_ms", "5000")))
    newline_var = tk.BooleanVar(value=bool(saved_state.get("newline_after_pos2", False)))
    ui2_automation_var = tk.BooleanVar(
        value=bool(saved_state.get("ui2_automation_enabled", False))
    )

    entries_ui1: dict[str, tuple[tk.Entry, tk.Entry]] = {}
    entries_ui2: dict[str, tuple[tk.Entry, tk.Entry]] = {}
    capture_listener: mouse.Listener | None = None
    hotkey_listener: keyboard.Listener | None = None

    def _parse_delay_ms(var: tk.StringVar, label: str, fallback: int) -> int:
        try:
            delay_ms = int(float(var.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror(f"{label} 오류", f"{label}를 숫자로 입력하세요.")
            delay_ms = fallback
        if delay_ms < 0:
            messagebox.showerror(f"{label} 오류", f"{label}는 0 이상이어야 합니다.")
            delay_ms = 0
        var.set(str(delay_ms))
        return delay_ms

    def _make_delay_getter(var: tk.StringVar, label: str, fallback: int) -> Callable[[], int]:
        return lambda: _parse_delay_ms(var, label, fallback)

    def _parse_positive_int(var: tk.StringVar, label: str, fallback: int) -> int:
        try:
            value = int(float(var.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror(f"{label} 오류", f"{label}를 숫자로 입력하세요.")
            value = fallback
        if value < 1:
            messagebox.showerror(f"{label} 오류", f"{label}는 1 이상이어야 합니다.")
            value = 1
        var.set(str(value))
        return value

    def _make_positive_int_getter(var: tk.StringVar, label: str, fallback: int) -> Callable[[], int]:
        return lambda: _parse_positive_int(var, label, fallback)

    def get_channel_watch_interval_ms() -> int:
        return _parse_delay_ms(channel_watch_interval_var, "채널 감시 주기", 200)

    def get_channel_timeout_ms() -> int:
        return _parse_delay_ms(channel_timeout_var, "채널 타임아웃", 5000)

    def add_coordinate_row(parent: tk.Widget, label_text: str, key: str, target_entries: dict[str, tuple[tk.Entry, tk.Entry]]) -> None:
        frame = tk.Frame(parent)
        frame.pack(fill="x", padx=10, pady=5)

        tk.Label(frame, text=label_text, width=8, anchor="w").pack(side="left")
        x_entry = tk.Entry(frame, width=6)
        x_entry.pack(side="left", padx=(0, 4))
        x_entry.insert(0, str(saved_state.get("coordinates", {}).get(key, {}).get("x", "0")))

        y_entry = tk.Entry(frame, width=6)
        y_entry.pack(side="left")
        y_entry.insert(0, str(saved_state.get("coordinates", {}).get(key, {}).get("y", "0")))

        target_entries[key] = (x_entry, y_entry)

        def start_capture() -> None:
            nonlocal capture_listener
            if capture_listener is not None and capture_listener.running:
                messagebox.showinfo("좌표 등록", "다른 좌표 등록이 진행 중입니다.")
                return

            status_var.set(f"{label_text} 등록: 원하는 위치를 클릭하세요.")
            root.withdraw()

            def on_click(x: float, y: float, button: mouse.Button, pressed: bool) -> bool:
                if pressed and button == mouse.Button.left:
                    root.after(0, finalize_capture, key, int(x), int(y))
                    return False
                return True

            capture_listener = mouse.Listener(on_click=on_click)
            capture_listener.start()

        def finalize_capture(target_key: str, x_val: int, y_val: int) -> None:
            nonlocal capture_listener
            x_entry_local, y_entry_local = target_entries[target_key]
            x_entry_local.delete(0, tk.END)
            x_entry_local.insert(0, str(x_val))
            y_entry_local.delete(0, tk.END)
            y_entry_local.insert(0, str(y_val))
            status_var.set(f"{label_text} 좌표가 등록되었습니다: ({x_val}, {y_val})")
            root.deiconify()
            capture_listener = None

        register_button = tk.Button(frame, text="클릭으로 등록", command=start_capture)
        register_button.pack(side="left", padx=(6, 0))

    top_bar = tk.Frame(root)
    top_bar.pack(fill="x", pady=(6, 4))
    action_frame = tk.Frame(top_bar)
    action_frame.pack(side="right", padx=6)

    overlay_toggle_button = tk.Button(action_frame, text="오버레이로 보기", width=12)
    overlay_toggle_button.pack(side="right", padx=(0, 4))
    content_frame = tk.Frame(root)
    content_frame.pack(fill="both", expand=True)

    ui1_frame = tk.Frame(content_frame)
    ui2_frame = tk.Frame(content_frame)

    def add_step_delay_row(parent: tk.Widget, title: str, steps: list[tuple[tk.StringVar, str]]) -> None:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=title, width=10, anchor="w").pack(side="left")
        for idx, (var, label_text) in enumerate(steps):
            tk.Entry(row, textvariable=var, width=6).pack(side="left", padx=(0, 4))
            tk.Label(row, text=label_text).pack(side="left", padx=(0, 4))
            if idx < len(steps) - 1:
                tk.Label(row, text="-").pack(side="left", padx=(0, 4))

    def add_single_delay_row(parent: tk.Widget, title: str, var: tk.StringVar, suffix: str = "ms") -> None:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=title, width=10, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=var, width=8).pack(side="left", padx=(0, 6))
        if suffix:
            tk.Label(row, text=suffix).pack(side="left")

    # UI 1
    ui1_top = tk.Frame(ui1_frame)
    ui1_top.pack(fill="x", pady=(0, 4))
    tk.Checkbutton(ui1_top, text="줄바꿈", variable=newline_var).pack(side="right", padx=(0, 12))

    add_coordinate_row(ui1_frame, "pos1", "pos1", entries_ui1)
    add_coordinate_row(ui1_frame, "pos2", "pos2", entries_ui1)
    add_coordinate_row(ui1_frame, "pos3", "pos3", entries_ui1)
    add_coordinate_row(ui1_frame, "pos4", "pos4", entries_ui1)

    delay_frame_ui1 = tk.LabelFrame(ui1_frame, text="딜레이 설정")
    delay_frame_ui1.pack(fill="x", padx=10, pady=(0, 10))

    add_step_delay_row(
        delay_frame_ui1,
        "(F2)",
        [
            (f2_before_esc_var, "Esc"),
            (f2_before_pos1_var, "pos1"),
            (f2_before_pos2_var, "pos2"),
        ],
    )
    add_single_delay_row(delay_frame_ui1, "채널감시주기", channel_watch_interval_var, "ms (기본 200)")
    add_single_delay_row(delay_frame_ui1, "채널타임아웃", channel_timeout_var, "ms (기본 5000)")
    add_step_delay_row(
        delay_frame_ui1,
        "(F1-1)",
        [
            (f1_before_pos3_var, "pos3"),
            (f1_before_enter_var, "Enter"),
        ],
    )
    add_single_delay_row(delay_frame_ui1, "F1 반복", f1_repeat_count_var, "회")
    add_step_delay_row(
        delay_frame_ui1,
        "(F1-2)",
        [
            (f1_newline_before_pos4_var, "pos4"),
            (f1_newline_before_pos3_var, "pos3"),
            (f1_newline_before_enter_var, "Enter"),
        ],
    )

    # UI 2
    ui2_top = tk.Frame(ui2_frame)
    ui2_top.pack(fill="x", pady=(0, 4))
    ui2_automation_checkbox = tk.Checkbutton(
        ui2_top, text="자동화", variable=ui2_automation_var
    )
    ui2_automation_checkbox.pack(side="right", padx=(0, 12))

    add_coordinate_row(ui2_frame, "pos11", "pos11", entries_ui2)
    add_coordinate_row(ui2_frame, "pos12", "pos12", entries_ui2)
    add_coordinate_row(ui2_frame, "pos13", "pos13", entries_ui2)
    add_coordinate_row(ui2_frame, "pos14", "pos14", entries_ui2)

    delay_frame_ui2 = tk.LabelFrame(ui2_frame, text="딜레이 설정")
    delay_frame_ui2.pack(fill="x", padx=10, pady=(0, 10))

    add_step_delay_row(
        delay_frame_ui2,
        "(F4)",
        [
            (f4_between_pos11_pos12_var, "pos11-pos12"),
            (f4_before_enter_var, "Enter 전"),
        ],
    )
    add_single_delay_row(delay_frame_ui2, "(F5)", f5_interval_var, "ms (클릭 간격)")
    add_single_delay_row(delay_frame_ui2, "(F6)", f6_interval_var, "ms (클릭 간격)")

    delay_config = DelayConfig(
        f2_before_esc=_make_delay_getter(f2_before_esc_var, "(F2) Esc 전", 0),
        f2_before_pos1=_make_delay_getter(f2_before_pos1_var, "(F2) pos1 전", 0),
        f2_before_pos2=_make_delay_getter(f2_before_pos2_var, "(F2) pos2 전", 100),
        f1_before_pos3=_make_delay_getter(f1_before_pos3_var, "(F1-1) pos3 전", 0),
        f1_before_enter=_make_delay_getter(f1_before_enter_var, "(F1-1) Enter 전", 0),
        f1_repeat_count=_make_positive_int_getter(f1_repeat_count_var, "(F1) 반복 횟수", 1),
        f1_newline_before_pos4=_make_delay_getter(
            f1_newline_before_pos4_var, "(F1-2) pos4 전", 0
        ),
        f1_newline_before_pos3=_make_delay_getter(
            f1_newline_before_pos3_var, "(F1-2) pos3 전", 30
        ),
        f1_newline_before_enter=_make_delay_getter(
            f1_newline_before_enter_var, "(F1-2) Enter 전", 0
        ),
    )

    controller = MacroController(entries_ui1, status_var, delay_config)

    ui_toggle_button = tk.Button(top_bar, text="UI 전환", width=14)
    ui_toggle_button.pack(side="left", padx=(10, 4))

    test_button = tk.Button(action_frame, text="테스트", width=12)
    test_button.pack(side="right", padx=(0, 4))

    packet_capture_button = tk.Button(action_frame, text="패킷캡쳐 시작", width=12)
    packet_capture_button.pack(side="right", padx=(0, 4))

    status_label = tk.Label(root, textvariable=status_var, fg="#006400")
    status_label.pack(pady=(0, 4))
    devlogic_label = tk.Label(root, textvariable=devlogic_alert_var, fg="red")
    devlogic_label.pack(pady=(0, 2))
    devlogic_packet_label = tk.Label(root, textvariable=devlogic_packet_var, fg="red")
    devlogic_packet_label.pack(pady=(0, 6))

    def update_overlay_position_from_window() -> None:
        nonlocal overlay_position
        if overlay_window is None or not tk.Toplevel.winfo_exists(overlay_window):
            return
        overlay_position = {
            "x": overlay_window.winfo_x(),
            "y": overlay_window.winfo_y(),
        }

    def close_overlay_and_show_main() -> None:
        nonlocal overlay_window
        update_overlay_position_from_window()
        if overlay_window is not None and tk.Toplevel.winfo_exists(overlay_window):
            overlay_window.destroy()
        overlay_window = None
        root.deiconify()
        root.lift()

    def start_overlay_drag(event: tk.Event[tk.Widget]) -> None:  # type: ignore[type-arg]
        nonlocal overlay_drag_offset
        if overlay_window is None:
            return
        overlay_drag_offset = (
            event.x_root - overlay_window.winfo_x(),
            event.y_root - overlay_window.winfo_y(),
        )

    def drag_overlay(event: tk.Event[tk.Widget]) -> None:  # type: ignore[type-arg]
        if overlay_window is None:
            return
        new_x = event.x_root - overlay_drag_offset[0]
        new_y = event.y_root - overlay_drag_offset[1]
        overlay_window.geometry(f"+{new_x}+{new_y}")
        overlay_position["x"] = new_x
        overlay_position["y"] = new_y

    def show_overlay() -> None:
        nonlocal overlay_window
        if overlay_window is not None and tk.Toplevel.winfo_exists(overlay_window):
            overlay_window.deiconify()
            overlay_window.lift()
            root.withdraw()
            return

        overlay_window = tk.Toplevel(root)
        overlay_window.overrideredirect(True)
        overlay_window.attributes("-topmost", True)
        overlay_window.attributes("-alpha", 0.88)
        overlay_window.geometry(f"+{overlay_position['x']}+{overlay_position['y']}")

        card = tk.Frame(overlay_window, bg="#1f1f1f", bd=2, relief="ridge")
        card.pack(padx=4, pady=4)

        for widget in (card,):
            widget.bind("<ButtonPress-1>", start_overlay_drag)
            widget.bind("<B1-Motion>", drag_overlay)

        header = tk.Label(
            card,
            text="상태 오버레이",
            fg="#ffffff",
            bg="#1f1f1f",
            font=("Arial", 10, "bold"),
        )
        header.pack(anchor="w", padx=10, pady=(6, 2))
        header.bind("<ButtonPress-1>", start_overlay_drag)
        header.bind("<B1-Motion>", drag_overlay)

        tk.Label(
            card,
            textvariable=status_var,
            fg="#00a050",
            bg="#1f1f1f",
            anchor="w",
            font=("Arial", 10),
        ).pack(fill="x", padx=10, pady=(0, 2))

        tk.Label(
            card,
            textvariable=devlogic_alert_var,
            fg="#ff4d4f",
            bg="#1f1f1f",
            anchor="w",
            font=("Arial", 10, "bold"),
        ).pack(fill="x", padx=10, pady=(0, 0))

        tk.Label(
            card,
            textvariable=devlogic_packet_var,
            fg="#ff4d4f",
            bg="#1f1f1f",
            anchor="w",
            font=("Arial", 10),
        ).pack(fill="x", padx=10, pady=(0, 6))

        button_bar = tk.Frame(card, bg="#1f1f1f")
        button_bar.pack(fill="x", padx=6, pady=(0, 6))
        tk.Button(
            button_bar,
            text="메인 UI 열기",
            command=close_overlay_and_show_main,
            bg="#2e2e2e",
            fg="#ffffff",
            relief="flat",
            highlightthickness=0,
        ).pack(side="right", padx=(4, 0))

        overlay_window.bind("<ButtonPress-1>", start_overlay_drag)
        overlay_window.bind("<B1-Motion>", drag_overlay)
        root.withdraw()

    def set_status_async(message: str) -> None:
        root.after(0, status_var.set, message)

    ui_two_delay_config = UiTwoDelayConfig(
        f4_between_pos11_pos12=_make_delay_getter(
            f4_between_pos11_pos12_var, "(F4) pos11-pos12 전", 0
        ),
        f4_before_enter=_make_delay_getter(f4_before_enter_var, "(F4) Enter 전", 0),
        f5_interval=_make_delay_getter(f5_interval_var, "(F5) 반복 간격", 100),
        f6_interval=_make_delay_getter(f6_interval_var, "(F6) 반복 간격", 100),
    )

    ui1_frame.pack_forget()
    ui2_frame.pack_forget()

    def switch_ui(mode: str) -> None:
        target = "2" if mode == "2" else "1"
        ui_mode.set(target)
        ui1_frame.pack_forget()
        ui2_frame.pack_forget()
        if target == "1":
            ui1_frame.pack(fill="both", expand=True)
            ui_toggle_button.configure(text="2번 UI로 전환")
        else:
            ui2_frame.pack(fill="both", expand=True)
            ui_toggle_button.configure(text="1번 UI로 전환")

    def toggle_ui() -> None:
        switch_ui("2" if ui_mode.get() == "1" else "1")

    ui_toggle_button.configure(command=toggle_ui)
    switch_ui(ui_mode.get())

    ui2_repeater_f5 = RepeatingClickTask(set_status_async)
    ui2_repeater_f6 = RepeatingClickTask(set_status_async)
    ui2_f4_automation_task = RepeatingActionTask(set_status_async)
    devlogic_last_detected_at: float | None = None
    devlogic_last_packet = ""
    devlogic_last_is_new_channel = False

    def _format_devlogic_packet(packet_text: str) -> tuple[str, bool]:
        start = packet_text.find("DevLogic")
        if start == -1:
            return "", False
        segment_start = start + len("DevLogic")
        end = packet_text.find("ExpDrop", segment_start)
        if end == -1:
            return "", False
        segment = packet_text[segment_start:end]
        sanitized = re.sub(r"[^0-9A-Za-z가-힣]", "-", segment)
        display = sanitized[:20]
        is_new_channel = bool(display) and display.strip("-") == ""
        return display, is_new_channel

    def _get_ui2_point(key: str, label: str) -> tuple[int, int] | None:
        x_entry, y_entry = entries_ui2[key]
        try:
            x_val = int(x_entry.get())
            y_val = int(y_entry.get())
        except ValueError:
            messagebox.showerror("좌표 오류", f"{label} 좌표를 정수로 입력해주세요.")
            return None
        return x_val, y_val

    def _sleep_ms_ui2(delay_ms: int) -> None:
        delay_sec = max(delay_ms, 0) / 1000
        if delay_sec:
            time.sleep(delay_sec)

    def _build_ui2_f4_action() -> Callable[[], None] | None:
        pos11 = _get_ui2_point("pos11", "pos11")
        pos12 = _get_ui2_point("pos12", "pos12")
        if pos11 is None or pos12 is None:
            return None
        delay_between = ui_two_delay_config.f4_between_pos11_pos12()
        delay_before_enter = ui_two_delay_config.f4_before_enter()

        def _run() -> None:
            set_status_async("F4: pos11 → pos12 실행 중…")
            pyautogui.click(*pos11)
            _sleep_ms_ui2(delay_between)
            pyautogui.click(*pos12)
            _sleep_ms_ui2(delay_before_enter)
            pyautogui.press("enter")
            set_status_async("F4: 실행 완료")

        return _run

    def run_ui2_f4() -> None:
        if ui2_automation_var.get():
            if ui2_f4_automation_task.is_running:
                ui2_f4_automation_task.stop(stop_message="자동화 모드: 중지되었습니다.")
                return
            action = _build_ui2_f4_action()
            if action is None:
                return
            if ui2_repeater_f6.stop():
                set_status_async("F6 반복 클릭을 중지했습니다.")
            ui2_f4_automation_task.start(
                action,
                0.5,
                start_message="자동화 모드: F4 반복 시작",
                stop_message="자동화 모드: 중지되었습니다.",
            )
            return

        if ui2_f4_automation_task.stop():
            set_status_async("자동화 모드: 중지되었습니다.")
        action = _build_ui2_f4_action()
        if action is None:
            return
        if ui2_repeater_f6.stop():
            set_status_async("F6 반복 클릭을 중지했습니다.")
        threading.Thread(target=action, daemon=True).start()

    def run_ui2_f5() -> None:
        pos13 = _get_ui2_point("pos13", "pos13")
        if pos13 is None:
            return
        interval_ms = ui_two_delay_config.f5_interval()
        ui2_repeater_f5.start(
            pos13,
            interval_ms,
            start_message="F5: pos13 반복 클릭 시작",
            stop_message="F5: 중지되었습니다.",
        )

    def run_ui2_f6(*, force_start: bool = False) -> None:
        if ui2_repeater_f6.is_running and not force_start:
            ui2_repeater_f6.stop(stop_message="F6: 중지되었습니다.")
            return
        if ui2_repeater_f6.is_running and force_start:
            ui2_repeater_f6.stop(stop_message="F6: 중지되었습니다.")

        pos14 = _get_ui2_point("pos14", "pos14")
        if pos14 is None:
            return
        interval_ms = ui_two_delay_config.f6_interval()
        if ui2_repeater_f5.stop():
            set_status_async("F5: 중지되었습니다.")
        ui2_repeater_f6.start(
            pos14,
            interval_ms,
            start_message="F6: pos14 반복 클릭 시작",
            stop_message="F6: 중지되었습니다.",
        )

    def on_ui2_automation_toggle() -> None:
        if not ui2_automation_var.get():
            if ui2_f4_automation_task.stop():
                set_status_async("자동화 모드: 중지되었습니다.")

    ui2_automation_checkbox.configure(command=on_ui2_automation_toggle)

    test_window: tk.Toplevel | None = None
    test_treeview: ttk.Treeview | None = None
    test_detail_text: tk.Text | None = None
    test_pattern_table: ttk.Treeview | None = None
    test_records: list[tuple[str, str, str | None, str, list[list[str]]]] = []
    test_channel_names: list[str] = []
    test_channel_name_set: set[str] = set()
    pattern_table_regex = re.compile(r"[A-Z][가-힣]\d{2,3}")

    def format_timestamp(ts: float) -> str:
        ts_int = int(ts)
        millis = int((ts - ts_int) * 1000)
        return time.strftime('%H:%M:%S', time.localtime(ts)) + f".{millis:03d}"

    class ChannelSegmentRecorder:
        anchor_keyword = "ChannelName"

        def __init__(
            self,
            on_capture: Callable[[str], None],
            on_channel_activity: Callable[[float], None] | None = None,
        ) -> None:
            self._on_capture = on_capture
            self._on_channel_activity = on_channel_activity
            self._buffer = ""
            self._pattern = re.compile(r"[A-Z]-[가-힣]\d{2,3}-")

        @staticmethod
        def _normalize(text: str) -> str:
            return re.sub(r"[^A-Za-z0-9가-힣]", "-", text)

        def feed(self, text: str) -> None:
            normalized = self._normalize(text)
            if not normalized:
                return
            if self.anchor_keyword in normalized and self._on_channel_activity is not None:
                self._on_channel_activity(time.time())
            self._buffer += normalized
            self._process_buffer()

        def _process_buffer(self) -> None:
            while True:
                anchor_idx = self._buffer.find(self.anchor_keyword)
                if anchor_idx == -1:
                    # 불필요한 데이터가 과도하게 쌓이지 않도록 끝부분만 유지
                    self._buffer = self._buffer[-len(self.anchor_keyword) :]
                    return
                if self._on_channel_activity is not None:
                    self._on_channel_activity(time.time())

                search_start = anchor_idx + len(self.anchor_keyword)
                match = self._pattern.search(self._buffer, pos=search_start)
                if match is None:
                    # 앵커부터의 문자열만 유지하여 다음 입력을 기다림
                    self._buffer = self._buffer[anchor_idx:]
                    return

                captured = match.group(0).replace("-", "")
                self._on_capture(captured)

                # 매칭된 구간 이후 데이터를 유지하여 추가 탐색
                self._buffer = self._buffer[match.end() :]

    def collect_app_state() -> dict:
        update_overlay_position_from_window()
        coordinates: dict[str, dict[str, str]] = {}
        for key, (x_entry, y_entry) in {**entries_ui1, **entries_ui2}.items():
            coordinates[key] = {"x": x_entry.get(), "y": y_entry.get()}
        return {
            "coordinates": coordinates,
            "ui_mode": ui_mode.get(),
            "delay_f2_before_esc_ms": f2_before_esc_var.get(),
            "delay_f2_before_pos1_ms": f2_before_pos1_var.get(),
            "delay_f2_before_pos2_ms": f2_before_pos2_var.get(),
            "delay_f1_before_pos3_ms": f1_before_pos3_var.get(),
            "delay_f1_before_enter_ms": f1_before_enter_var.get(),
            "f1_repeat_count": f1_repeat_count_var.get(),
            "delay_f1_newline_before_pos4_ms": f1_newline_before_pos4_var.get(),
            "delay_f1_newline_before_pos3_ms": f1_newline_before_pos3_var.get(),
            "delay_f1_newline_before_enter_ms": f1_newline_before_enter_var.get(),
            "delay_f4_between_pos11_pos12_ms": f4_between_pos11_pos12_var.get(),
            "delay_f4_before_enter_ms": f4_before_enter_var.get(),
            "delay_f5_interval_ms": f5_interval_var.get(),
            "delay_f6_interval_ms": f6_interval_var.get(),
            "channel_watch_interval_ms": channel_watch_interval_var.get(),
            "channel_timeout_ms": channel_timeout_var.get(),
            "newline_after_pos2": newline_var.get(),
            "ui2_automation_enabled": ui2_automation_var.get(),
            "overlay_x": overlay_position["x"],
            "overlay_y": overlay_position["y"],
        }

    def build_pattern_table(names: list[str]) -> tuple[str | None, list[list[str]]]:
        if not names:
            return None, []

        col_width = max(len(match) for match in names)
        rows_for_view: list[list[str]] = []
        formatted_rows: list[str] = []
        for idx in range(0, len(names), 6):
            chunk = names[idx : idx + 6]
            padded = chunk + [""] * (6 - len(chunk))
            rows_for_view.append(padded)
            formatted_rows.append(
                " | ".join(cell.ljust(col_width) if cell else "".ljust(col_width) for cell in padded)
            )

        return "\n".join(formatted_rows), rows_for_view

    def update_pattern_table() -> None:
        if test_pattern_table is None:
            return

        for item in test_pattern_table.get_children():
            test_pattern_table.delete(item)

        _, rows = build_pattern_table(test_channel_names)

        if not rows:
            test_pattern_table.insert("", "end", values=("(없음)", "", "", "", "", ""))
            return

        for row in rows:
            padded = row + [""] * (6 - len(row))
            test_pattern_table.insert("", "end", values=padded)

    def add_test_record(content: str) -> tuple[list[str], list[str]]:
        matches = pattern_table_regex.findall(content)
        new_names = [name for name in matches if name not in test_channel_name_set]
        if not matches:
            return [], []

        if new_names:
            for name in new_names:
                test_channel_name_set.add(name)
                test_channel_names.append(name)

            timestamp = format_timestamp(time.time())
            table_text, table_rows = build_pattern_table(test_channel_names)
            display_content = (
                f"{content}\n\n[추출된 패턴]\n{table_text}"
                if table_text
                else content
            )
            test_records.append((timestamp, content, table_text, display_content, table_rows))
            if test_treeview is not None:
                index = len(test_records)
                item_id = test_treeview.insert("", "end", values=(index, timestamp, display_content))
                test_treeview.selection_set(item_id)
                update_test_detail(index)
                update_pattern_table()
        return matches, new_names

    def update_test_detail(selected_index: int | None = None) -> None:
        if test_detail_text is None:
            return

        test_detail_text.configure(state="normal")
        test_detail_text.delete("1.0", "end")

        if selected_index is None or selected_index < 1 or selected_index > len(test_records):
            test_detail_text.insert("1.0", "기록을 선택하세요.")
            update_pattern_table()
        else:
            _, content, table_text, _, _ = test_records[selected_index - 1]
            patterns = table_text or "(없음)"
            detail_text = f"{content}\n\n[추출된 패턴]\n{patterns}"
            test_detail_text.insert("1.0", detail_text)

        update_pattern_table()

        test_detail_text.configure(state="disabled")

    def refresh_test_treeview() -> None:
        if test_treeview is None:
            return
        for item in test_treeview.get_children():
            test_treeview.delete(item)
        for idx, (ts, _, _, display_content, _) in enumerate(test_records, start=1):
            test_treeview.insert("", "end", values=(idx, ts, display_content))
        update_test_detail(test_records and 1 or None)

    def clear_test_records() -> None:
        test_channel_names.clear()
        test_channel_name_set.clear()
        test_records.clear()
        refresh_test_treeview()
        update_pattern_table()
        status_var.set("테스트 기록이 초기화되었습니다.")

    def show_test_window() -> None:
        nonlocal test_window, test_treeview, test_detail_text, test_pattern_table
        if test_window is not None and tk.Toplevel.winfo_exists(test_window):
            test_window.lift()
            test_window.focus_force()
            refresh_test_treeview()
            return

        test_window = tk.Toplevel(root)
        test_window.title("테스트")
        test_window.geometry("520x500")
        test_window.resizable(True, True)

        info_label = ttk.Label(
            test_window,
            text=(
                "ChannelName이 포함된 패킷을 정규화한 뒤, 다음 [A-가00- 또는 A-가000-] "
                "형태가 나타날 때까지 기록하고 해당 문자열에서 하이픈(-)을 제거해 "
                "추출합니다."
            ),
            wraplength=480,
            justify="left",
        )
        info_label.pack(fill="x", padx=8, pady=(8, 4))

        tree = ttk.Treeview(
            test_window,
            columns=("index", "time", "content"),
            show="headings",
            height=10,
        )
        tree.heading("index", text="#")
        tree.heading("time", text="시간")
        tree.heading("content", text="기록")
        tree.column("index", width=40, anchor="center")
        tree.column("time", width=120, anchor="center")
        tree.column("content", width=340, anchor="w")
        tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        scrollbar = ttk.Scrollbar(test_window, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 8))

        detail_frame = ttk.LabelFrame(test_window, text="선택 기록 상세")
        detail_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical")
        detail_scroll.pack(side="right", fill="y")
        detail_text = tk.Text(detail_frame, height=6, wrap="none", state="disabled")
        detail_text.pack(fill="both", expand=True)
        detail_text.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.configure(command=detail_text.yview)

        pattern_frame = ttk.LabelFrame(test_window, text="추출된 패턴 표")
        pattern_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        pattern_columns = [f"c{i}" for i in range(1, 7)]
        pattern_table = ttk.Treeview(
            pattern_frame,
            columns=pattern_columns,
            show="headings",
            height=4,
        )
        for col in pattern_columns:
            pattern_table.heading(col, text=col[-1])
            pattern_table.column(col, width=70, anchor="center")
        pattern_table.pack(side="left", fill="both", expand=True)
        pattern_scroll = ttk.Scrollbar(pattern_frame, orient="vertical", command=pattern_table.yview)
        pattern_table.configure(yscrollcommand=pattern_scroll.set)
        pattern_scroll.pack(side="right", fill="y")

        button_bar = ttk.Frame(test_window)
        button_bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(button_bar, text="기록 초기화", command=clear_test_records).pack(side="right")

        test_treeview = tree
        test_detail_text = detail_text
        test_pattern_table = pattern_table
        refresh_test_treeview()

        def on_select_test_record(event: tk.Event[tk.Widget]) -> None:  # type: ignore[type-arg]
            if test_treeview is None:
                return
            selection = test_treeview.selection()
            if not selection:
                update_test_detail(None)
                return
            item_id = selection[0]
            values = test_treeview.item(item_id, "values")
            try:
                idx = int(values[0])
            except (ValueError, IndexError):
                update_test_detail(None)
                return
            update_test_detail(idx)

        tree.bind("<<TreeviewSelect>>", on_select_test_record)

        def on_close_test_window() -> None:
            nonlocal test_window, test_treeview, test_detail_text, test_pattern_table
            if test_treeview is not None:
                for item in test_treeview.get_children():
                    test_treeview.delete(item)
            test_treeview = None
            if test_detail_text is not None:
                test_detail_text.destroy()
            test_detail_text = None
            if test_pattern_table is not None:
                for item in test_pattern_table.get_children():
                    test_pattern_table.delete(item)
                test_pattern_table.destroy()
            test_pattern_table = None
            window = test_window
            test_window = None
            if window is not None:
                window.destroy()

        test_window.protocol("WM_DELETE_WINDOW", on_close_test_window)

    class ChannelDetectionSequence:
        def __init__(self) -> None:
            self.running = False
            self.detection_queue: Queue[tuple[float, bool]] = Queue()
            self.newline_mode = False
            self.last_detected_at: float | None = None

        def start(self, newline_mode: bool) -> None:
            if self.running:
                messagebox.showinfo("매크로", "F3 매크로가 이미 실행 중입니다.")
                return
            self.running = True
            self._clear_queue()
            self.newline_mode = newline_mode
            self.last_detected_at = None
            threading.Thread(target=self._run_sequence, daemon=True).start()

        def stop(self) -> None:
            self.running = False
            self._clear_queue()
            self.last_detected_at = None

        def notify_channel_found(
            self, *, detected_at: float | None = None, is_new: bool
        ) -> None:
            if not self.running:
                return
            timestamp = detected_at or time.time()
            self.detection_queue.put((timestamp, is_new))

        def _run_on_main(self, func: Callable[[], None]) -> None:
            done = threading.Event()

            def _wrapper() -> None:
                try:
                    func()
                finally:
                    done.set()

            root.after(0, _wrapper)
            done.wait()

        def _set_status(self, message: str) -> None:
            root.after(0, status_var.set, message)

        def _clear_queue(self) -> None:
            while True:
                try:
                    self.detection_queue.get_nowait()
                except Empty:
                    break

        def _wait_for_detection(self, timeout_sec: float) -> tuple[float, bool] | None:
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

        def _run_sequence(self) -> None:
            try:
                while self.running:
                    self._set_status("F3: F2 기능 실행 중…")
                    self._run_on_main(
                        lambda: controller.reset_and_run_first(
                            newline_mode=self.newline_mode
                        )
                    )

                    self._set_status("F3: 채널명 감시 중…")
                    self._clear_queue()
                    timeout_sec = self._delay_seconds(get_channel_timeout_ms())
                    first_detection = self._wait_for_detection(timeout_sec)
                    self.last_detected_at = first_detection[0] if first_detection else None

                    if not self.running:
                        break

                    if first_detection is None:
                        self._set_status("F3: 채널명이 발견되지 않았습니다. 재시도합니다…")
                        continue

                    first_time, is_new = first_detection
                    if is_new:
                        self._set_status("F3: 새 채널명 기록, F1 실행 중…")
                        self._run_on_main(
                            lambda: controller.run_step(newline_mode=self.newline_mode)
                        )
                        break

                    watch_interval = self._delay_seconds(get_channel_watch_interval_ms())
                    if watch_interval <= 0:
                        self._set_status("F3: 새 채널명이 없어 재시작합니다…")
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
                        self._set_status("F3: 새 채널명 기록, F1 실행 중…")
                        self._run_on_main(
                            lambda: controller.run_step(newline_mode=self.newline_mode)
                        )
                        break

                    self._set_status("F3: 새 채널명이 없어 재시작합니다…")
            finally:
                self.running = False
                self._run_on_main(controller._update_status)

        def _delay_seconds(self, delay_ms: int) -> float:
            return max(delay_ms, 0) / 1000

    channel_detection_sequence = ChannelDetectionSequence()

    def handle_captured_pattern(content: str) -> None:
        detected_at = time.time()
        matches, new_names = add_test_record(content)
        if matches:
            channel_detection_sequence.notify_channel_found(
                detected_at=detected_at,
                is_new=bool(new_names),
            )

    channel_segment_recorder = ChannelSegmentRecorder(handle_captured_pattern)

    def process_packet_detection(text: str) -> None:
        nonlocal devlogic_last_detected_at, devlogic_last_packet, devlogic_last_is_new_channel
        if "DevLogic" in text:
            devlogic_last_detected_at = time.time()
            devlogic_last_packet, devlogic_last_is_new_channel = _format_devlogic_packet(text)
            devlogic_packet_var.set(devlogic_last_packet)
            if devlogic_last_is_new_channel and ui2_f4_automation_task.stop():
                status_var.set("신규채널 감지: 자동화 모드를 중단하고 채널 감지를 대기합니다.")
            run_on_ui("2", run_ui2_f5)
            root.after(1000, lambda: run_on_ui("2", lambda: run_ui2_f6(force_start=True)))
        channel_segment_recorder.feed(text)

    def poll_devlogic_alert() -> None:
        interval_ms = get_channel_watch_interval_ms()
        now = time.time()
        alert_duration_sec = 3
        visible = (
            ui_mode.get() == "2"
            and devlogic_last_detected_at is not None
            and now - devlogic_last_detected_at <= alert_duration_sec
        )
        if visible:
            devlogic_alert_var.set("신규채널!!" if devlogic_last_is_new_channel else "채널 감지")
        else:
            devlogic_alert_var.set("")
        devlogic_packet_var.set(devlogic_last_packet if visible else "")
        root.after(max(interval_ms, 50), poll_devlogic_alert)

    packet_manager = PacketCaptureManager(
        on_packet=lambda text: root.after(0, process_packet_detection, text),
        on_error=lambda msg: root.after(0, messagebox.showerror, "패킷 캡쳐 오류", msg),
    )

    def update_packet_capture_button() -> None:
        text = "패킷캡쳐 중지" if packet_manager.running else "패킷캡쳐 시작"
        packet_capture_button.configure(text=text)

    def start_packet_capture() -> None:
        if packet_manager.running:
            return
        try:
            started = packet_manager.start()
        except Exception as exc:  # pragma: no cover - 안전망
            messagebox.showerror("패킷 캡쳐 오류", f"패킷 캡쳐 시작 실패: {exc}")
            update_packet_capture_button()
            return

        if not started:
            messagebox.showwarning("패킷 캡쳐", "패킷 캡쳐를 시작하지 못했습니다. scapy 설치 여부를 확인하세요.")
            update_packet_capture_button()
            return

        status_var.set("패킷 캡쳐가 시작되었습니다.")
        update_packet_capture_button()

    def stop_packet_capture() -> None:
        if not packet_manager.running:
            return
        try:
            packet_manager.stop()
        except Exception:
            messagebox.showwarning("패킷 캡쳐", "패킷 캡쳐 중지 실패")
        else:
            status_var.set("패킷 캡쳐가 중지되었습니다.")
        finally:
            update_packet_capture_button()

    def toggle_packet_capture() -> None:
        if packet_manager.running:
            stop_packet_capture()
        else:
            start_packet_capture()

    update_packet_capture_button()
    packet_capture_button.configure(command=toggle_packet_capture)

    overlay_toggle_button.configure(command=show_overlay)
    test_button.configure(command=show_test_window)
    poll_devlogic_alert()

    def run_on_ui(mode: str, action: Callable[[], None]) -> None:
        def _runner() -> None:
            switch_ui(mode)
            action()
        root.after(0, _runner)

    def on_hotkey_press(key: keyboard.Key) -> None:
        if key == keyboard.Key.f1:
            run_on_ui("1", controller.run_step)
        elif key == keyboard.Key.f2:
            run_on_ui("1", controller.reset_and_run_first)
        elif key == keyboard.Key.f3:
            def _toggle_f3() -> None:
                switch_ui("1")
                if channel_detection_sequence.running:
                    channel_detection_sequence.stop()
                    status_var.set("F3 매크로가 종료되었습니다.")
                    controller._update_status()
                else:
                    channel_detection_sequence.start(newline_var.get())
            root.after(0, _toggle_f3)
        elif key == keyboard.Key.f4:
            run_on_ui("2", run_ui2_f4)
        elif key == keyboard.Key.f5:
            run_on_ui("2", run_ui2_f5)
        elif key == keyboard.Key.f6:
            run_on_ui("2", run_ui2_f6)

    def start_hotkey_listener() -> None:
        nonlocal hotkey_listener
        if hotkey_listener is not None:
            return
        hotkey_listener = keyboard.Listener(on_press=on_hotkey_press)
        hotkey_listener.start()

    def on_close() -> None:
        close_overlay_and_show_main()
        save_app_state(collect_app_state())
        if hotkey_listener is not None:
            hotkey_listener.stop()
        channel_detection_sequence.stop()
        ui2_f4_automation_task.stop()
        ui2_repeater_f5.stop()
        ui2_repeater_f6.stop()
        stop_packet_capture()
        root.destroy()

    start_hotkey_listener()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
