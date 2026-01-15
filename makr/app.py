"""대칭 전력 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, F1/F2 단축키로
순차 동작을 제어합니다.
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox, ttk
from typing import Callable

from makr.packet import PacketCaptureManager

import pyautogui
from pynput import keyboard, mouse

APP_STATE_PATH = Path(__file__).with_name("app_state.json")
NEW_CHANNEL_SOUND_PATH = Path(__file__).with_name("new.wav")

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


class SoundPlayer:
    def __init__(self, sound_path: Path) -> None:
        self._sound_path = sound_path
        self._winsound = (
            importlib.import_module("winsound")
            if importlib.util.find_spec("winsound")
            else None
        )

    def play_once(self) -> None:
        if not self._sound_path.exists():
            return
        suffix = self._sound_path.suffix.lower()
        if suffix != ".wav":
            return

        def _run() -> None:
            if self._winsound is not None:
                self._winsound.PlaySound(
                    str(self._sound_path),
                    self._winsound.SND_FILENAME | self._winsound.SND_ASYNC,
                )
                return
            if sys.platform == "darwin":
                subprocess.run(
                    ["afplay", str(self._sound_path)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        threading.Thread(target=_run, daemon=True).start()


class MacroController:
    """실행 순서를 관리하고 GUI 콜백을 제공합니다."""

    def __init__(
        self,
        entries: dict[str, tuple[tk.Entry, tk.Entry]],
        status_var: tk.StringVar,
        delay_config: DelayConfig,
        label_map: dict[str, str],
    ) -> None:
        self.entries = entries
        self.status_var = status_var
        self.current_step = 1
        self.delay_config = delay_config
        self.label_map = label_map
        self._update_status()

    def _update_status(self) -> None:
        self.status_var.set(f"다음 실행 단계: {self.current_step}단계")

    def _get_point(self, key: str) -> tuple[int, int] | None:
        x_entry, y_entry = self.entries[key]
        label = self.label_map.get(key, key)
        try:
            x_val = int(x_entry.get())
            y_val = int(y_entry.get())
        except ValueError:
            messagebox.showerror("좌표 오류", f"{label} 좌표를 정수로 입력해주세요.")
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
    root.title("대칭 전력")
    root.attributes("-topmost", True)

    saved_state = load_app_state()

    status_var = tk.StringVar()
    devlogic_alert_var = tk.StringVar(value="")
    devlogic_packet_var = tk.StringVar(value="")
    ui_mode = tk.StringVar(value=str(saved_state.get("ui_mode", "1")))
    f2_before_esc_var = tk.StringVar(value=str(saved_state.get("delay_f2_before_esc_ms", "0")))
    f2_before_pos1_var = tk.StringVar(value=str(saved_state.get("delay_f2_before_pos1_ms", "55")))
    f2_before_pos2_var = tk.StringVar(
        value=str(saved_state.get("delay_f2_before_pos2_ms", saved_state.get("click_delay_ms", "55")))
    )
    f1_before_pos3_var = tk.StringVar(value=str(saved_state.get("delay_f1_before_pos3_ms", "15")))
    f1_before_enter_var = tk.StringVar(value=str(saved_state.get("delay_f1_before_enter_ms", "15")))
    f1_repeat_count_var = tk.StringVar(value=str(saved_state.get("f1_repeat_count", "8")))
    f1_newline_before_pos4_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_pos4_ms", "170"))
    )
    f1_newline_before_pos3_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_pos3_ms", "30"))
    )
    f1_newline_before_enter_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_enter_ms", "15"))
    )
    f4_between_pos11_pos12_var = tk.StringVar(
        value=str(saved_state.get("delay_f4_between_pos11_pos12_ms", "25"))
    )
    f4_before_enter_var = tk.StringVar(
        value=str(saved_state.get("delay_f4_before_enter_ms", "55"))
    )
    f5_interval_var = tk.StringVar(value=str(saved_state.get("delay_f5_interval_ms", "25")))
    f6_interval_var = tk.StringVar(value=str(saved_state.get("delay_f6_interval_ms", "25")))
    channel_watch_interval_var = tk.StringVar(
        value=str(saved_state.get("channel_watch_interval_ms", "20"))
    )
    channel_timeout_var = tk.StringVar(value=str(saved_state.get("channel_timeout_ms", "700")))
    newline_var = tk.BooleanVar(value=bool(saved_state.get("newline_after_pos2", False)))
    try:
        pos3_mode_initial = int(saved_state.get("pos3_mode", 1))
    except (TypeError, ValueError):
        pos3_mode_initial = 1
    if pos3_mode_initial not in range(1, 7):
        pos3_mode_initial = 1
    pos3_mode_var = tk.IntVar(value=pos3_mode_initial)
    ui2_automation_var = tk.BooleanVar(
        value=bool(saved_state.get("ui2_automation_enabled", False))
    )
    ui2_test_new_channel_var = tk.BooleanVar(
        value=bool(saved_state.get("ui2_test_new_channel", False))
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
        return _parse_delay_ms(channel_watch_interval_var, "채널 감시 주기", 20)

    def get_channel_timeout_ms() -> int:
        return _parse_delay_ms(channel_timeout_var, "채널 타임아웃", 700)

    pos3_mode_coordinates: dict[int, dict[str, str]] = {}
    saved_coordinates = saved_state.get("coordinates", {})
    legacy_pos3_coords = saved_coordinates.get("pos3", {})
    for mode in range(1, 7):
        mode_key = f"pos3_{mode}"
        coords = saved_coordinates.get(mode_key, {})
        if not coords and mode == 1 and legacy_pos3_coords:
            coords = legacy_pos3_coords
        pos3_mode_coordinates[mode] = {
            "x": str(coords.get("x", "0")),
            "y": str(coords.get("y", "0")),
        }

    def get_pos3_mode_name(mode: int) -> str:
        return f"{mode}열"

    ui1_label_map = {
        "pos1": "메뉴",
        "pos2": "채널",
        "pos3": "열",
        "pos4": "∇",
    }

    def add_coordinate_row(
        parent: tk.Widget,
        label_text: str,
        key: str,
        target_entries: dict[str, tuple[tk.Entry, tk.Entry]],
    ) -> None:
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

        register_button = tk.Button(frame, text="좌표등록", command=start_capture)
        register_button.pack(side="left", padx=(6, 0))

    def add_pos3_row(parent: tk.Widget, label_text: str) -> None:
        frame = tk.Frame(parent)
        frame.pack(fill="x", padx=10, pady=5)

        tk.Label(frame, text=label_text, width=8, anchor="w").pack(side="left")
        x_entry = tk.Entry(frame, width=6)
        x_entry.pack(side="left", padx=(0, 4))
        y_entry = tk.Entry(frame, width=6)
        y_entry.pack(side="left")
        entries_ui1["pos3"] = (x_entry, y_entry)

        def load_pos3_mode_values() -> None:
            mode = pos3_mode_var.get()
            coords = pos3_mode_coordinates.get(mode, {"x": "0", "y": "0"})
            x_entry.delete(0, tk.END)
            x_entry.insert(0, coords["x"])
            y_entry.delete(0, tk.END)
            y_entry.insert(0, coords["y"])

        load_pos3_mode_values()

        def start_capture() -> None:
            nonlocal capture_listener
            if capture_listener is not None and capture_listener.running:
                messagebox.showinfo("좌표 등록", "다른 좌표 등록이 진행 중입니다.")
                return

            mode = pos3_mode_var.get()
            status_var.set(f"{label_text}({get_pos3_mode_name(mode)}) 등록: 원하는 위치를 클릭하세요.")
            root.withdraw()

            def on_click(x: float, y: float, button: mouse.Button, pressed: bool) -> bool:
                if pressed and button == mouse.Button.left:
                    root.after(0, finalize_capture, int(x), int(y))
                    return False
                return True

            capture_listener = mouse.Listener(on_click=on_click)
            capture_listener.start()

        def finalize_capture(x_val: int, y_val: int) -> None:
            nonlocal capture_listener
            mode = pos3_mode_var.get()
            pos3_mode_coordinates[mode] = {"x": str(x_val), "y": str(y_val)}
            x_entry.delete(0, tk.END)
            x_entry.insert(0, str(x_val))
            y_entry.delete(0, tk.END)
            y_entry.insert(0, str(y_val))
            status_var.set(
                f"{label_text}({get_pos3_mode_name(mode)}) 좌표가 등록되었습니다: ({x_val}, {y_val})"
            )
            root.deiconify()
            capture_listener = None

        register_button = tk.Button(frame, text="좌표등록", command=start_capture)
        register_button.pack(side="left", padx=(6, 0))

    top_bar = tk.Frame(root)
    top_bar.pack(fill="x", pady=(6, 4))
    action_frame = tk.Frame(top_bar)
    action_frame.pack(side="left", padx=6)
    record_frame = tk.Frame(top_bar)
    record_frame.pack(side="right", padx=6)

    content_frame = tk.Frame(root)
    content_frame.pack(fill="both", expand=True)

    tab_active_bg = "#ffffff"
    tab_inactive_bg = "#e6e6e6"
    tab_border = "#bdbdbd"

    tab_bar = tk.Frame(content_frame, bg=tab_active_bg)
    tab_bar.pack(fill="x", padx=6, pady=(0, 0))
    tab_button_holder = tk.Frame(tab_bar, bg=tab_active_bg)
    tab_button_holder.pack(side="left")

    panel_frame = tk.Frame(
        content_frame,
        bg=tab_active_bg,
        highlightthickness=1,
        highlightbackground=tab_border,
    )
    panel_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    ui1_frame = tk.Frame(panel_frame, bg=tab_active_bg)
    ui2_frame = tk.Frame(panel_frame, bg=tab_active_bg)

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
    pos3_mode_label_var = tk.StringVar()
    pos3_mode_label = tk.Label(ui1_top, textvariable=pos3_mode_label_var)
    pos3_mode_label.pack(side="left", padx=(12, 0))
    pos3_mode_button = tk.Button(ui1_top, text="다음", width=12)
    pos3_mode_button.pack(side="left", padx=(6, 0))
    newline_checkbox = tk.Checkbutton(ui1_top, text="줄바꿈", variable=newline_var)
    newline_checkbox.pack(side="right", padx=(0, 12))

    add_coordinate_row(ui1_frame, "메뉴", "pos1", entries_ui1)
    add_coordinate_row(ui1_frame, "채널", "pos2", entries_ui1)
    add_pos3_row(ui1_frame, "열")
    add_coordinate_row(ui1_frame, "∇", "pos4", entries_ui1)

    delay_frame_ui1 = tk.LabelFrame(ui1_frame, text="딜레이 설정")
    delay_frame_ui1.pack(fill="x", padx=10, pady=(0, 10))

    add_step_delay_row(
        delay_frame_ui1,
        "(F2)",
        [
            (f2_before_esc_var, "Esc"),
            (f2_before_pos1_var, "메뉴"),
            (f2_before_pos2_var, "채널"),
        ],
    )
    add_single_delay_row(delay_frame_ui1, "채널감시주기", channel_watch_interval_var, "ms (기본 20)")
    add_single_delay_row(delay_frame_ui1, "채널타임아웃", channel_timeout_var, "ms (기본 700)")
    add_step_delay_row(
        delay_frame_ui1,
        "(F1-1)",
        [
            (f1_before_pos3_var, "열"),
            (f1_before_enter_var, "Enter"),
        ],
    )
    add_single_delay_row(delay_frame_ui1, "F1 반복", f1_repeat_count_var, "회")
    add_step_delay_row(
        delay_frame_ui1,
        "(F1-2)",
        [
            (f1_newline_before_pos4_var, "∇"),
            (f1_newline_before_pos3_var, "열"),
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
    ui2_test_checkbox = tk.Checkbutton(
        ui2_top, text="테스트", variable=ui2_test_new_channel_var
    )
    ui2_test_checkbox.pack(side="right", padx=(0, 6))

    add_coordinate_row(ui2_frame, "···", "pos11", entries_ui2)
    add_coordinate_row(ui2_frame, "🔃", "pos12", entries_ui2)
    add_coordinate_row(ui2_frame, "로그인", "pos13", entries_ui2)
    add_coordinate_row(ui2_frame, "캐릭터", "pos14", entries_ui2)

    delay_frame_ui2 = tk.LabelFrame(ui2_frame, text="딜레이 설정")
    delay_frame_ui2.pack(fill="x", padx=10, pady=(0, 10))

    add_step_delay_row(
        delay_frame_ui2,
        "(F4)",
        [
            (f4_between_pos11_pos12_var, "···-🔃"),
            (f4_before_enter_var, "Enter 전"),
        ],
    )
    add_single_delay_row(delay_frame_ui2, "(F5)", f5_interval_var, "ms (클릭 간격)")
    add_single_delay_row(delay_frame_ui2, "(F6)", f6_interval_var, "ms (클릭 간격)")

    delay_config = DelayConfig(
        f2_before_esc=_make_delay_getter(f2_before_esc_var, "(F2) Esc 전", 0),
        f2_before_pos1=_make_delay_getter(f2_before_pos1_var, "(F2) 메뉴 전", 55),
        f2_before_pos2=_make_delay_getter(f2_before_pos2_var, "(F2) 채널 전", 55),
        f1_before_pos3=_make_delay_getter(f1_before_pos3_var, "(F1-1) 열 전", 15),
        f1_before_enter=_make_delay_getter(f1_before_enter_var, "(F1-1) Enter 전", 15),
        f1_repeat_count=_make_positive_int_getter(f1_repeat_count_var, "(F1) 반복 횟수", 8),
        f1_newline_before_pos4=_make_delay_getter(
            f1_newline_before_pos4_var, "(F1-2) ∇ 전", 170
        ),
        f1_newline_before_pos3=_make_delay_getter(
            f1_newline_before_pos3_var, "(F1-2) 열 전", 30
        ),
        f1_newline_before_enter=_make_delay_getter(
            f1_newline_before_enter_var, "(F1-2) Enter 전", 15
        ),
    )

    controller = MacroController(entries_ui1, status_var, delay_config, ui1_label_map)

    def store_current_pos3_mode_values() -> None:
        if "pos3" not in entries_ui1:
            return
        x_entry, y_entry = entries_ui1["pos3"]
        pos3_mode_coordinates[pos3_mode_var.get()] = {
            "x": x_entry.get(),
            "y": y_entry.get(),
        }

    def update_pos3_mode_label() -> None:
        pos3_mode_label_var.set(f"선택할 열: {get_pos3_mode_name(pos3_mode_var.get())}")

    def apply_newline_for_pos3_mode() -> None:
        newline_var.set(pos3_mode_var.get() == 1)

    def set_pos3_mode(new_mode: int) -> None:
        store_current_pos3_mode_values()
        normalized_mode = ((new_mode - 1) % 6) + 1
        pos3_mode_var.set(normalized_mode)
        coords = pos3_mode_coordinates.get(normalized_mode, {"x": "0", "y": "0"})
        x_entry, y_entry = entries_ui1["pos3"]
        x_entry.delete(0, tk.END)
        x_entry.insert(0, coords["x"])
        y_entry.delete(0, tk.END)
        y_entry.insert(0, coords["y"])
        update_pos3_mode_label()
        apply_newline_for_pos3_mode()
        status_var.set(f"선택할 열이 {get_pos3_mode_name(normalized_mode)}로 변경되었습니다.")

    def cycle_pos3_mode() -> None:
        set_pos3_mode(pos3_mode_var.get() + 1)

    packet_read_button = tk.Button(action_frame, text="패킷읽기", width=12)
    packet_read_button.pack(side="left", padx=(0, 6))

    packet_capture_button = tk.Button(action_frame, text="패킷캡쳐 시작", width=12)
    packet_capture_button.pack(side="left", padx=(0, 6))

    test_button = tk.Button(action_frame, text="채널목록", width=12)
    test_button.pack(side="left")

    record_button = tk.Button(record_frame, text="월재기록", width=12)
    record_button.pack(side="right")

    status_label = tk.Label(root, textvariable=status_var, fg="#006400")
    status_label.pack(pady=(0, 4))
    devlogic_label = tk.Label(root, textvariable=devlogic_alert_var, fg="red")
    devlogic_label.pack(pady=(0, 6))

    def set_status_async(message: str) -> None:
        root.after(0, status_var.set, message)

    ui_two_delay_config = UiTwoDelayConfig(
        f4_between_pos11_pos12=_make_delay_getter(
            f4_between_pos11_pos12_var, "(F4) ···-🔃 전", 25
        ),
        f4_before_enter=_make_delay_getter(f4_before_enter_var, "(F4) Enter 전", 55),
        f5_interval=_make_delay_getter(f5_interval_var, "(F5) 반복 간격", 25),
        f6_interval=_make_delay_getter(f6_interval_var, "(F6) 반복 간격", 25),
    )

    tab_button_1 = tk.Button(
        tab_button_holder,
        text="채변",
        width=10,
        takefocus=True,
    )
    tab_button_1.pack(side="left", padx=(0, 6), pady=(0, 0))

    tab_button_2 = tk.Button(
        tab_button_holder,
        text="월재",
        width=10,
        takefocus=True,
    )
    tab_button_2.pack(side="left", pady=(0, 0))

    def _style_tab_button(button: tk.Button, *, active: bool) -> None:
        if active:
            button.configure(
                bg=tab_active_bg,
                fg="#000000",
                relief="solid",
                bd=1,
                highlightthickness=0,
                activebackground=tab_active_bg,
                activeforeground="#000000",
            )
        else:
            button.configure(
                bg=tab_inactive_bg,
                fg="#555555",
                relief="ridge",
                bd=1,
                highlightthickness=0,
                activebackground="#dcdcdc",
                activeforeground="#333333",
            )

    def switch_ui(mode: str) -> None:
        target = "2" if mode == "2" else "1"
        ui_mode.set(target)
        ui1_frame.pack_forget()
        ui2_frame.pack_forget()
        if target == "1":
            _style_tab_button(tab_button_1, active=True)
            _style_tab_button(tab_button_2, active=False)
            ui1_frame.pack(fill="both", expand=True)
        else:
            _style_tab_button(tab_button_1, active=False)
            _style_tab_button(tab_button_2, active=True)
            ui2_frame.pack(fill="both", expand=True)

    def _bind_tab_activate(button: tk.Button, mode: str) -> None:
        def _activate(event: tk.Event[tk.Widget] | None = None) -> None:
            switch_ui(mode)

        button.configure(command=_activate)
        button.bind("<Return>", _activate)
        button.bind("<space>", _activate)

    _bind_tab_activate(tab_button_1, "1")
    _bind_tab_activate(tab_button_2, "2")
    switch_ui("1")
    update_pos3_mode_label()
    apply_newline_for_pos3_mode()
    pos3_mode_button.configure(command=cycle_pos3_mode)

    def enforce_newline_mode() -> None:
        if pos3_mode_var.get() == 1 and not newline_var.get():
            newline_var.set(True)
        elif pos3_mode_var.get() != 1 and newline_var.get():
            newline_var.set(False)

    newline_checkbox.configure(command=enforce_newline_mode)

    ui2_repeater_f5 = RepeatingClickTask(set_status_async)
    ui2_repeater_f6 = RepeatingClickTask(set_status_async)
    ui2_f4_automation_task = RepeatingActionTask(set_status_async)
    new_channel_sound_player = SoundPlayer(NEW_CHANNEL_SOUND_PATH)
    devlogic_last_detected_at: float | None = None
    devlogic_last_packet = ""
    devlogic_last_is_new_channel = False
    devlogic_last_alert_message = ""
    devlogic_last_alert_packet = ""
    ui2_automation_active = False
    ui2_waiting_for_new_channel = False
    ui2_waiting_for_normal_channel = False
    ui2_waiting_for_selection = False

    class BeepNotifier:
        def __init__(self, root_widget: tk.Tk) -> None:
            self._root = root_widget
            self._thread: threading.Thread | None = None
            self._stop_event = threading.Event()
            self._winsound = (
                importlib.import_module("winsound")
                if importlib.util.find_spec("winsound")
                else None
            )

        def start(self, duration_sec: float = 3.0) -> None:
            self.stop()
            self._stop_event.clear()

            def _run() -> None:
                end_time = time.time() + max(duration_sec, 0)
                while time.time() < end_time and not self._stop_event.is_set():
                    if self._winsound is not None:
                        self._winsound.Beep(1200, 200)
                    else:
                        self._root.after(0, self._root.bell)
                    if self._stop_event.wait(0.1):
                        break

            self._thread = threading.Thread(target=_run, daemon=True)
            self._thread.start()

        def stop(self) -> None:
            if self._thread is None:
                return
            self._stop_event.set()

    beep_notifier = BeepNotifier(root)

    def _format_devlogic_packet(packet_text: str) -> tuple[str, bool, bool]:
        start = packet_text.find("DevLogic")
        if start == -1:
            return "", False, False
        segment_start = start + len("DevLogic")
        segment = packet_text[segment_start : segment_start + 25]
        sanitized = re.sub(r"[^0-9A-Za-z가-힣]", "-", segment)
        display = sanitized[:25]
        if not display:
            return "", False, False
        has_alpha = bool(re.search(r"[A-Za-z]", display))
        has_digit = bool(re.search(r"[0-9]", display))
        has_korean = bool(re.search(r"[가-힣]", display))
        is_normal_channel = has_alpha and has_digit and has_korean
        is_new_channel = not is_normal_channel
        return display, is_new_channel, is_normal_channel

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
        pos11 = _get_ui2_point("pos11", "···")
        pos12 = _get_ui2_point("pos12", "🔃")
        if pos11 is None or pos12 is None:
            return None
        delay_between = ui_two_delay_config.f4_between_pos11_pos12()
        delay_before_enter = ui_two_delay_config.f4_before_enter()

        def _run() -> None:
            pyautogui.click(*pos11)
            _sleep_ms_ui2(delay_between)
            pyautogui.click(*pos12)
            _sleep_ms_ui2(delay_before_enter)
            pyautogui.press("enter")

        return _run

    def run_ui2_f4_batch(
        action: Callable[[], None],
        *,
        repeat_count: int = 10,
        interval_sec: float = 0.2,
        start_message: str | None = None,
        stop_message: str | None = None,
    ) -> None:
        if start_message:
            set_status_async(start_message)

        def _run() -> None:
            for idx in range(max(repeat_count, 1)):
                action()
                if idx < repeat_count - 1:
                    time.sleep(max(interval_sec, 0))
            if stop_message:
                set_status_async(stop_message)

        threading.Thread(target=_run, daemon=True).start()

    def stop_ui2_automation(message: str | None = None) -> None:
        nonlocal ui2_automation_active
        nonlocal ui2_waiting_for_new_channel
        nonlocal ui2_waiting_for_normal_channel
        nonlocal ui2_waiting_for_selection
        ui2_automation_active = False
        ui2_waiting_for_new_channel = False
        ui2_waiting_for_normal_channel = False
        ui2_waiting_for_selection = False
        clear_ui2_set_state()
        ui2_f4_automation_task.stop()
        if ui2_repeater_f5.stop():
            set_status_async("F5: 중지되었습니다.")
        if ui2_repeater_f6.stop():
            set_status_async("F6: 중지되었습니다.")
        if message:
            set_status_async(message)

    def start_ui2_automation() -> None:
        nonlocal ui2_automation_active
        nonlocal ui2_waiting_for_new_channel
        nonlocal ui2_waiting_for_normal_channel
        nonlocal ui2_waiting_for_selection
        if ui2_automation_active:
            set_status_async("자동화 모드: 이미 실행 중입니다.")
            return
        if ui2_repeater_f5.stop():
            set_status_async("F5: 중지되었습니다.")
        if ui2_repeater_f6.stop():
            set_status_async("F6: 중지되었습니다.")
        ui2_waiting_for_new_channel = True
        ui2_waiting_for_normal_channel = False
        ui2_waiting_for_selection = False
        ui2_automation_active = True
        action = _build_ui2_f4_action()
        if action is None:
            return
        start_new_ui2_set()
        run_ui2_f4_batch(action)

    def restart_ui2_f4_cycle() -> None:
        nonlocal ui2_automation_active
        nonlocal ui2_waiting_for_new_channel
        nonlocal ui2_waiting_for_normal_channel
        nonlocal ui2_waiting_for_selection
        action = _build_ui2_f4_action()
        if action is None:
            return
        ui2_waiting_for_new_channel = True
        ui2_waiting_for_normal_channel = False
        ui2_waiting_for_selection = False
        ui2_automation_active = True
        start_new_ui2_set()
        run_ui2_f4_batch(action)

    def restart_ui2_f4_logic() -> None:
        action = _build_ui2_f4_action()
        if action is None:
            return
        start_new_ui2_set()
        run_ui2_f4_batch(action)

    def run_ui2_f4() -> None:
        if ui2_automation_var.get():
            start_ui2_automation()
            return

        if ui2_f4_automation_task.stop():
            set_status_async("자동화 모드: 중지되었습니다.")
        action = _build_ui2_f4_action()
        if action is None:
            return
        if ui2_repeater_f6.stop():
            set_status_async("F6 반복 클릭을 중지했습니다.")
        run_ui2_f4_batch(
            action,
            start_message="F4: 10회 실행 중…",
            stop_message="F4: 실행 완료",
        )

    def run_ui2_f5() -> None:
        pos13 = _get_ui2_point("pos13", "로그인")
        if pos13 is None:
            return
        interval_ms = ui_two_delay_config.f5_interval()
        ui2_repeater_f5.start(
            pos13,
            interval_ms,
            start_message="F5: 로그인 반복 클릭 시작",
            stop_message="F5: 중지되었습니다.",
        )

    def run_ui2_f6(*, force_start: bool = False) -> None:
        if ui2_repeater_f6.is_running and not force_start:
            ui2_repeater_f6.stop(stop_message="F6: 중지되었습니다.")
            return
        if ui2_repeater_f6.is_running and force_start:
            ui2_repeater_f6.stop(stop_message="F6: 중지되었습니다.")

        pos14 = _get_ui2_point("pos14", "캐릭터")
        if pos14 is None:
            return
        interval_ms = ui_two_delay_config.f6_interval()
        if ui2_repeater_f5.stop():
            set_status_async("F5: 중지되었습니다.")
        ui2_repeater_f6.start(
            pos14,
            interval_ms,
            start_message="F6: 캐릭터 반복 클릭 시작",
            stop_message="F6: 중지되었습니다.",
        )

    def start_ui2_normal_channel_sequence() -> None:
        run_on_ui("2", run_ui2_f5)

    def on_ui2_automation_toggle() -> None:
        if not ui2_automation_var.get():
            stop_ui2_automation("자동화 모드: 중지되었습니다.")

    ui2_automation_checkbox.configure(command=on_ui2_automation_toggle)

    test_window: tk.Toplevel | None = None
    test_treeview: ttk.Treeview | None = None
    test_detail_text: tk.Text | None = None
    test_pattern_table: ttk.Treeview | None = None
    test_records: list[tuple[str, str, str | None, str, list[list[str]]]] = []
    test_channel_names: list[str] = []
    test_channel_name_set: set[str] = set()
    pattern_table_regex = re.compile(r"[A-Z][가-힣]\d{2,3}")
    ui2_record_window: tk.Toplevel | None = None
    ui2_record_treeview: ttk.Treeview | None = None
    ui2_record_items: list[tuple[int, str, str]] = []
    ui2_set_index = 0
    ui2_current_set_started_at: float | None = None

    def format_timestamp(ts: float) -> str:
        ts_int = int(ts)
        millis = int((ts - ts_int) * 1000)
        return time.strftime('%H:%M:%S', time.localtime(ts)) + f".{millis:03d}"

    def refresh_ui2_record_treeview() -> None:
        if ui2_record_treeview is None:
            return
        for item in ui2_record_treeview.get_children():
            ui2_record_treeview.delete(item)
        for set_no, started_at, result in ui2_record_items:
            ui2_record_treeview.insert(
                "",
                "end",
                text=f"{set_no}세트",
                values=(started_at, result),
            )

    def add_ui2_record_item(set_no: int, started_at: float, result: str) -> None:
        timestamp = format_timestamp(started_at)
        ui2_record_items.append((set_no, timestamp, result))
        if ui2_record_treeview is not None:
            ui2_record_treeview.insert(
                "",
                "end",
                text=f"{set_no}세트",
                values=(timestamp, result),
            )

    def start_new_ui2_set() -> None:
        nonlocal ui2_set_index
        nonlocal ui2_current_set_started_at
        ui2_set_index += 1
        ui2_current_set_started_at = time.time()
        set_status_async(f"{ui2_set_index}세트 시작")

    def finish_ui2_set(result: str, note: str | None = None) -> None:
        nonlocal ui2_current_set_started_at
        if ui2_current_set_started_at is None:
            return
        add_ui2_record_item(ui2_set_index, ui2_current_set_started_at, result)
        ui2_current_set_started_at = None
        suffix = f" - {note}" if note else ""
        set_status_async(f"{ui2_set_index}세트 종료 ({result}){suffix}")

    def clear_ui2_set_state() -> None:
        nonlocal ui2_current_set_started_at
        ui2_current_set_started_at = None

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
        store_current_pos3_mode_values()
        coordinates: dict[str, dict[str, str]] = {}
        for key, (x_entry, y_entry) in {**entries_ui1, **entries_ui2}.items():
            coordinates[key] = {"x": x_entry.get(), "y": y_entry.get()}
        for mode in range(1, 7):
            coordinates[f"pos3_{mode}"] = pos3_mode_coordinates.get(
                mode,
                {"x": "0", "y": "0"},
            )
        return {
            "coordinates": coordinates,
            "ui_mode": ui_mode.get(),
            "pos3_mode": pos3_mode_var.get(),
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
            "ui2_test_new_channel": ui2_test_new_channel_var.get(),
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
        test_window.title("채널목록")
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

    def show_ui2_record_window() -> None:
        nonlocal ui2_record_window, ui2_record_treeview
        if ui2_record_window is not None and tk.Toplevel.winfo_exists(ui2_record_window):
            ui2_record_window.lift()
            ui2_record_window.focus_force()
            refresh_ui2_record_treeview()
            return

        ui2_record_window = tk.Toplevel(root)
        ui2_record_window.title("월재기록")
        ui2_record_window.geometry("360x320")
        ui2_record_window.resizable(True, True)

        info_label = ttk.Label(
            ui2_record_window,
            text="세트 종료 시점마다 시작시간과 결과를 기록합니다.",
            wraplength=320,
            justify="left",
        )
        info_label.pack(fill="x", padx=8, pady=(8, 4))

        tree = ttk.Treeview(
            ui2_record_window,
            columns=("start_time", "result"),
            show="tree headings",
            height=10,
        )
        tree.heading("#0", text="세트")
        tree.heading("start_time", text="시작시간")
        tree.heading("result", text="결과")
        tree.column("#0", width=60, anchor="center")
        tree.column("start_time", width=180, anchor="center")
        tree.column("result", width=80, anchor="center")
        tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        scrollbar = ttk.Scrollbar(ui2_record_window, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 8))

        ui2_record_treeview = tree
        refresh_ui2_record_treeview()

        def on_close_record_window() -> None:
            nonlocal ui2_record_window, ui2_record_treeview
            if ui2_record_treeview is not None:
                for item in ui2_record_treeview.get_children():
                    ui2_record_treeview.delete(item)
            ui2_record_treeview = None
            window = ui2_record_window
            ui2_record_window = None
            if window is not None:
                window.destroy()

        ui2_record_window.protocol("WM_DELETE_WINDOW", on_close_record_window)

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
            if new_names:
                new_channel_sound_player.play_once()

    channel_segment_recorder = ChannelSegmentRecorder(handle_captured_pattern)

    packet_read_window: tk.Toplevel | None = None
    packet_read_text: tk.Text | None = None
    packet_read_records: list[str] = []

    def sanitize_packet_text(text: str) -> str:
        return re.sub(r"[^0-9A-Za-z가-힣]", "-", text)

    def clear_packet_reads() -> None:
        packet_read_records.clear()
        if packet_read_text is None:
            return
        packet_read_text.configure(state="normal")
        packet_read_text.delete("1.0", tk.END)
        packet_read_text.configure(state="disabled")

    def append_packet_read(text: str) -> None:
        nonlocal packet_read_text
        sanitized = sanitize_packet_text(text)
        packet_read_records.append(sanitized)
        if packet_read_text is None:
            return
        if packet_read_window is None or not tk.Toplevel.winfo_exists(packet_read_window):
            return
        packet_read_text.configure(state="normal")
        packet_read_text.insert(tk.END, sanitized + "\n")
        packet_read_text.see(tk.END)
        packet_read_text.configure(state="disabled")

    def show_packet_read_window() -> None:
        nonlocal packet_read_window, packet_read_text
        if packet_read_window is not None and tk.Toplevel.winfo_exists(packet_read_window):
            packet_read_window.lift()
            packet_read_window.focus_force()
            return

        packet_read_window = tk.Toplevel(root)
        packet_read_window.title("패킷읽기")
        packet_read_window.geometry("640x480")
        packet_read_window.resizable(True, True)

        packet_frame = ttk.Frame(packet_read_window)
        packet_frame.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        scrollbar = ttk.Scrollbar(packet_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        packet_read_text = tk.Text(packet_frame, wrap="none", state="disabled")
        packet_read_text.pack(side="left", fill="both", expand=True)
        packet_read_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=packet_read_text.yview)

        control_frame = ttk.Frame(packet_read_window)
        control_frame.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(control_frame, text="기록 초기화", command=clear_packet_reads).pack(
            side="right"
        )

        if packet_read_records:
            packet_read_text.configure(state="normal")
            packet_read_text.insert(tk.END, "\n".join(packet_read_records) + "\n")
            packet_read_text.see(tk.END)
            packet_read_text.configure(state="disabled")

        def on_close_packet_read_window() -> None:
            nonlocal packet_read_window, packet_read_text
            if packet_read_text is not None:
                packet_read_text.destroy()
            packet_read_text = None
            window = packet_read_window
            packet_read_window = None
            if window is not None:
                window.destroy()

        packet_read_window.protocol("WM_DELETE_WINDOW", on_close_packet_read_window)

    def process_packet_detection(text: str) -> None:
        nonlocal devlogic_last_detected_at
        nonlocal devlogic_last_packet
        nonlocal devlogic_last_is_new_channel
        nonlocal devlogic_last_alert_message
        nonlocal devlogic_last_alert_packet
        nonlocal ui2_automation_active
        nonlocal ui2_waiting_for_new_channel
        nonlocal ui2_waiting_for_normal_channel
        nonlocal ui2_waiting_for_selection
        append_packet_read(text)
        if "DevLogic" in text:
            devlogic_last_detected_at = time.time()
            (
                devlogic_last_packet,
                devlogic_last_is_new_channel,
                devlogic_last_is_normal_channel,
            ) = _format_devlogic_packet(text)
            forced_new_channel = (
                ui2_automation_active
                and ui2_automation_var.get()
                and ui2_test_new_channel_var.get()
                and devlogic_last_is_normal_channel
            )
            effective_new_channel = devlogic_last_is_new_channel or forced_new_channel
            alert_prefix = "신규채널!!" if devlogic_last_is_new_channel else "채널 감지"
            devlogic_last_alert_message = alert_prefix
            devlogic_last_alert_packet = devlogic_last_packet
            devlogic_packet_var.set(devlogic_last_packet)
            if effective_new_channel:
                new_channel_sound_player.play_once()
            if ui2_automation_active and ui2_automation_var.get():
                if ui2_waiting_for_new_channel and effective_new_channel:
                    ui2_waiting_for_new_channel = False
                    ui2_waiting_for_normal_channel = True
                    ui2_waiting_for_selection = False
                    ui2_f4_automation_task.stop()
                    finish_ui2_set("성공", "일반 채널 대기")
                    beep_notifier.start(3)
                elif ui2_waiting_for_new_channel and devlogic_last_is_normal_channel:
                    finish_ui2_set("실패", "F4 로직 재실행")
                    restart_ui2_f4_logic()
                elif ui2_waiting_for_normal_channel and devlogic_last_is_normal_channel:
                    ui2_waiting_for_normal_channel = False
                    ui2_waiting_for_selection = True
                    set_status_async("일반채널 감지: F5 실행 후 선택창 대기")
                    start_ui2_normal_channel_sequence()
            elif not ui2_automation_var.get():
                ui2_waiting_for_new_channel = False
                ui2_waiting_for_normal_channel = False
                ui2_waiting_for_selection = False
        if "AdminLevel" in text:
            devlogic_last_detected_at = time.time()
            devlogic_last_alert_message = "선택창 감지"
            devlogic_last_alert_packet = ""
            devlogic_packet_var.set("")
            if ui2_automation_active and ui2_waiting_for_selection:
                ui2_waiting_for_selection = False
                set_status_async("선택창 감지: F6 실행 중 (F6 재입력 시 중단)")
                run_on_ui("2", lambda: run_ui2_f6(force_start=True))
        channel_segment_recorder.feed(text)

    def poll_devlogic_alert() -> None:
        interval_ms = get_channel_watch_interval_ms()
        visible = ui_mode.get() == "2" and devlogic_last_detected_at is not None
        if visible:
            elapsed_sec = max(0, int(time.time() - devlogic_last_detected_at))
            elapsed_suffix = f"({elapsed_sec}초 전)"
            if devlogic_last_alert_message and devlogic_last_alert_packet:
                devlogic_alert_var.set(
                    f"{devlogic_last_alert_message} {devlogic_last_alert_packet} {elapsed_suffix}"
                )
            elif devlogic_last_alert_message:
                devlogic_alert_var.set(f"{devlogic_last_alert_message} {elapsed_suffix}")
            else:
                devlogic_alert_var.set("")
        else:
            devlogic_alert_var.set("")
        devlogic_packet_var.set(devlogic_last_alert_packet if visible else "")
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
    packet_read_button.configure(command=show_packet_read_window)
    test_button.configure(command=show_test_window)
    record_button.configure(command=show_ui2_record_window)
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
            def _handle_f6() -> None:
                if ui2_automation_active and ui2_automation_var.get():
                    stop_ui2_automation("자동화 모드: F6 입력으로 중단되었습니다.")
                else:
                    run_ui2_f6()
            run_on_ui("2", _handle_f6)
        elif key == keyboard.Key.f7:
            run_on_ui("1", cycle_pos3_mode)

    def start_hotkey_listener() -> None:
        nonlocal hotkey_listener
        if hotkey_listener is not None:
            return
        hotkey_listener = keyboard.Listener(on_press=on_hotkey_press)
        hotkey_listener.start()

    def on_close() -> None:
        save_app_state(collect_app_state())
        if hotkey_listener is not None:
            hotkey_listener.stop()
        channel_detection_sequence.stop()
        ui2_f4_automation_task.stop()
        ui2_repeater_f5.stop()
        ui2_repeater_f6.stop()
        beep_notifier.stop()
        stop_packet_capture()
        root.destroy()

    start_hotkey_listener()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
