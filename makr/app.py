"""단계별 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, 실행/다시 버튼으로
순차 동작을 제어합니다.
"""

from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
from collections import deque
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
    f1_newline_before_pos4: Callable[[], int]
    f1_newline_before_pos3: Callable[[], int]
    f1_newline_before_enter: Callable[[], int]


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
        self.input_logger: MacroInputLogger | None = None
        self._update_status()

    def set_input_logger(self, logger: "MacroInputLogger | None") -> None:
        self.input_logger = logger

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
        if self.input_logger:
            self.input_logger.record_click(label or "클릭", point)

    def _press_key(self, key: str, *, label: str | None = None) -> None:
        pyautogui.press(key)
        if self.input_logger:
            self.input_logger.record_key(label or key, key)

    def _delay_seconds(self, delay_ms: int) -> float:
        return max(delay_ms, 0) / 1000

    def _sleep_ms(self, delay_ms: int) -> None:
        delay_sec = self._delay_seconds(delay_ms)
        if delay_sec:
            time.sleep(delay_sec)

    def run_step(self, *, newline_mode: bool = False) -> None:
        """실행 버튼 콜백: 현재 단계 수행 후 다음 단계로 이동."""
        if self.current_step == 1:
            self._run_step_one()
            self.current_step = 2
        else:
            self._run_step_two(newline_mode=newline_mode)
            self.current_step = 1
        self._update_status()

    def reset_and_run_first(self, *, newline_mode: bool = False) -> None:
        """다시 버튼 콜백: Esc 입력 후 1단계를 재실행."""
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
        if newline_mode:
            pos4 = self._get_point("pos4")
            if pos4 is None:
                return
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
    f2_before_esc_var = tk.StringVar(value=str(saved_state.get("delay_f2_before_esc_ms", "0")))
    f2_before_pos1_var = tk.StringVar(value=str(saved_state.get("delay_f2_before_pos1_ms", "0")))
    f2_before_pos2_var = tk.StringVar(
        value=str(saved_state.get("delay_f2_before_pos2_ms", saved_state.get("click_delay_ms", "100")))
    )
    channel_wait_window_var = tk.StringVar(value=str(saved_state.get("channel_wait_window_ms", "500")))
    f1_before_pos3_var = tk.StringVar(value=str(saved_state.get("delay_f1_before_pos3_ms", "0")))
    f1_before_enter_var = tk.StringVar(value=str(saved_state.get("delay_f1_before_enter_ms", "0")))
    f1_newline_before_pos4_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_pos4_ms", "0"))
    )
    f1_newline_before_pos3_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_pos3_ms", "30"))
    )
    f1_newline_before_enter_var = tk.StringVar(
        value=str(saved_state.get("delay_f1_newline_before_enter_ms", "0"))
    )
    packet_limit_var = tk.StringVar(value=str(saved_state.get("packet_limit", "200")))
    packet_status_var = tk.StringVar(value="패킷 캡쳐 중지됨")
    newline_var = tk.BooleanVar(value=bool(saved_state.get("newline_after_pos2", False)))
    three_digit_channel_var = tk.BooleanVar(
        value=bool(saved_state.get("detect_three_digit_channel", False))
    )
    channel_names: set[str] = set(saved_state.get("channel_names", []))

    entries: dict[str, tuple[tk.Entry, tk.Entry]] = {}
    packet_queue: deque[tuple[int, str]] = deque()
    packet_queue_lock = threading.Lock()
    packet_flush_job: str | None = None
    capture_listener: mouse.Listener | None = None
    hotkey_listener: keyboard.Listener | None = None
    packet_manager = PacketCaptureManager(
        on_packet=lambda text: enqueue_packet_text(text),
        on_error=lambda msg: root.after(0, messagebox.showerror, "패킷 캡쳐 오류", msg),
    )

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

    def get_channel_wait_window_ms() -> int:
        return _parse_delay_ms(channel_wait_window_var, "채널 감지 대기", 500)

    def add_coordinate_row(label_text: str, key: str) -> None:
        frame = tk.Frame(root)
        frame.pack(fill="x", padx=10, pady=5)

        tk.Label(frame, text=label_text, width=8, anchor="w").pack(side="left")
        x_entry = tk.Entry(frame, width=6)
        x_entry.pack(side="left", padx=(0, 4))
        x_entry.insert(0, str(saved_state.get("coordinates", {}).get(key, {}).get("x", "0")))

        y_entry = tk.Entry(frame, width=6)
        y_entry.pack(side="left")
        y_entry.insert(0, str(saved_state.get("coordinates", {}).get(key, {}).get("y", "0")))

        entries[key] = (x_entry, y_entry)

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
            x_entry_local, y_entry_local = entries[target_key]
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
    top_bar.pack(fill="x", pady=(6, 0))
    tk.Checkbutton(top_bar, text="3글자만 탐지", variable=three_digit_channel_var).pack(
        side="right", padx=(0, 12)
    )
    tk.Checkbutton(top_bar, text="줄바꿈", variable=newline_var).pack(side="right", padx=(0, 12))

    tk.Label(root, text="좌표는 화면 기준 픽셀 단위로 입력하세요 (X, Y).", fg="#444").pack(pady=(6, 0))

    add_coordinate_row("pos1", "pos1")
    add_coordinate_row("pos2", "pos2")
    add_coordinate_row("pos3", "pos3")
    add_coordinate_row("pos4", "pos4")

    delay_config = DelayConfig(
        f2_before_esc=_make_delay_getter(f2_before_esc_var, "(F2) Esc 전", 0),
        f2_before_pos1=_make_delay_getter(f2_before_pos1_var, "(F2) pos1 전", 0),
        f2_before_pos2=_make_delay_getter(f2_before_pos2_var, "(F2) pos2 전", 100),
        f1_before_pos3=_make_delay_getter(f1_before_pos3_var, "(F1-1) pos3 전", 0),
        f1_before_enter=_make_delay_getter(f1_before_enter_var, "(F1-1) Enter 전", 0),
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

    controller = MacroController(entries, status_var, delay_config)

    debug_window: tk.Toplevel | None = None
    debug_log_widget: tk.Text | None = None
    debug_logs: list[str] = []
    debug_logs_lock = threading.Lock()

    def append_debug_log(message: str) -> None:
        nonlocal debug_log_widget
        timestamped = f"{format_timestamp(time.time())} - {message}"
        with debug_logs_lock:
            debug_logs.append(timestamped)

        def _write_log() -> None:
            if debug_log_widget is None:
                return
            debug_log_widget.configure(state="normal")
            debug_log_widget.insert(tk.END, f"{timestamped}\n")
            debug_log_widget.see(tk.END)
            debug_log_widget.configure(state="disabled")

        root.after(0, _write_log)

    class MacroInputLogger:
        def __init__(self, log_callback: Callable[[str], None]) -> None:
            self._log_callback = log_callback
            self._start_ms: float | None = None
            self._lock = threading.Lock()

        def start(self) -> None:
            with self._lock:
                self._start_ms = time.perf_counter() * 1000

        def stop(self) -> None:
            with self._lock:
                self._start_ms = None

        def _elapsed_ms(self) -> int | None:
            with self._lock:
                if self._start_ms is None:
                    return None
                return int(time.perf_counter() * 1000 - self._start_ms)

        def record_click(self, label: str, point: tuple[int, int]) -> None:
            elapsed = self._elapsed_ms()
            if elapsed is None:
                return
            x_val, y_val = point
            self._log_callback(
                f"[자동 입력] {label}: {elapsed}ms (클릭 {x_val}, {y_val})"
            )

        def record_key(self, label: str, key: str) -> None:
            elapsed = self._elapsed_ms()
            if elapsed is None:
                return
            self._log_callback(f"[자동 입력] {label}: {elapsed}ms (키 {key})")

    debug_recorder = MacroInputLogger(append_debug_log)

    def close_debug_window() -> None:
        nonlocal debug_window, debug_log_widget
        if debug_window is not None:
            debug_window.destroy()
        debug_window = None
        debug_log_widget = None

    def show_debug_window() -> None:
        nonlocal debug_window, debug_log_widget
        if debug_window is not None and tk.Toplevel.winfo_exists(debug_window):
            debug_window.lift()
            debug_window.focus_force()
            return

        debug_window = tk.Toplevel(root)
        debug_window.title("디버깅")
        debug_window.geometry("400x300")
        debug_window.resizable(True, True)

        info_label = tk.Label(
            debug_window,
            text="F3 동작 중 발생한 마우스/키보드 기록 (ms 단위)",
            anchor="w",
        )
        info_label.pack(fill="x", padx=8, pady=(8, 4))

        log_frame = tk.Frame(debug_window)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        debug_log_widget = tk.Text(log_frame, state="disabled", height=10)
        debug_log_widget.pack(side="left", fill="both", expand=True)
        log_scroll = tk.Scrollbar(log_frame, command=debug_log_widget.yview)
        log_scroll.pack(side="right", fill="y")
        debug_log_widget.configure(yscrollcommand=log_scroll.set)

        with debug_logs_lock:
            for line in debug_logs:
                debug_log_widget.configure(state="normal")
                debug_log_widget.insert(tk.END, f"{line}\n")
                debug_log_widget.configure(state="disabled")

        debug_window.protocol("WM_DELETE_WINDOW", close_debug_window)
        debug_window.focus_force()

    button_frame = tk.Frame(root)
    button_frame.pack(pady=10)

    run_button = tk.Button(button_frame, text="실행 (F1)", width=12, command=controller.run_step)
    run_button.pack(side="left", padx=5)

    reset_button = tk.Button(button_frame, text="다시 (F2)", width=12, command=controller.reset_and_run_first)
    reset_button.pack(side="left", padx=5)

    debug_button = tk.Button(button_frame, text="디버깅", width=12, command=show_debug_window)
    debug_button.pack(side="left", padx=5)

    test_button = tk.Button(button_frame, text="테스트", width=12)
    test_button.pack(side="left", padx=5)

    delay_frame = tk.LabelFrame(root, text="딜레이 설정")
    delay_frame.pack(fill="x", padx=10, pady=(0, 10))

    def add_step_delay_row(title: str, steps: list[tuple[tk.StringVar, str]]) -> None:
        row = tk.Frame(delay_frame)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=title, width=8, anchor="w").pack(side="left")
        for idx, (var, label_text) in enumerate(steps):
            tk.Entry(row, textvariable=var, width=6).pack(side="left", padx=(0, 4))
            tk.Label(row, text=label_text).pack(side="left", padx=(0, 4))
            if idx < len(steps) - 1:
                tk.Label(row, text="-").pack(side="left", padx=(0, 4))

    def add_single_delay_row(title: str, var: tk.StringVar, suffix: str = "ms") -> None:
        row = tk.Frame(delay_frame)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=title, width=8, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=var, width=8).pack(side="left", padx=(0, 6))
        if suffix:
            tk.Label(row, text=suffix).pack(side="left")

    add_step_delay_row(
        "(F2)",
        [
            (f2_before_esc_var, "Esc"),
            (f2_before_pos1_var, "pos1"),
            (f2_before_pos2_var, "pos2"),
        ],
    )
    add_single_delay_row("채널감지대기", channel_wait_window_var, "ms (기본 500)")
    add_step_delay_row(
        "(F1-1)",
        [
            (f1_before_pos3_var, "pos3"),
            (f1_before_enter_var, "Enter"),
        ],
    )
    add_step_delay_row(
        "(F1-2)",
        [
            (f1_newline_before_pos4_var, "pos4"),
            (f1_newline_before_pos3_var, "pos3"),
            (f1_newline_before_enter_var, "Enter"),
        ],
    )

    status_label = tk.Label(root, textvariable=status_var, fg="#006400")
    status_label.pack(pady=(0, 4))

    alert_frame = ttk.Frame(root)
    alert_frame.pack(fill="x", padx=10, pady=(0, 10))
    alert_frame.columnconfigure(0, weight=1)
    alert_frame.columnconfigure(1, weight=1)

    channel_alert_var = tk.StringVar()
    channel_packet_alert_var = tk.StringVar()

    ttk.Label(alert_frame, textvariable=channel_alert_var, anchor="w", foreground="#0a5").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(alert_frame, textvariable=channel_packet_alert_var, anchor="e", foreground="#05a").grid(
        row=0, column=1, sticky="e"
    )

    packet_frame = ttk.LabelFrame(root, text="패킷 캡쳐")
    packet_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    packet_frame.columnconfigure(0, weight=1)
    packet_frame.rowconfigure(4, weight=1)

    packet_status_label = ttk.Label(packet_frame, textvariable=packet_status_var, foreground="#0a5")
    packet_status_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))

    ttk.Label(packet_frame, text="포트").grid(row=1, column=0, sticky="w", padx=8)
    packet_port_var = tk.StringVar(value=str(saved_state.get("packet_port", "32800")))
    packet_port_entry = ttk.Entry(packet_frame, textvariable=packet_port_var, width=10)
    packet_port_entry.grid(row=1, column=1, sticky="w")

    packet_control_frame = ttk.Frame(packet_frame)
    packet_control_frame.grid(row=1, column=2, sticky="e", padx=8)
    start_capture_btn = ttk.Button(packet_control_frame, text="캡쳐 시작")
    stop_capture_btn = ttk.Button(packet_control_frame, text="캡쳐 중지", state="disabled")
    start_capture_btn.grid(row=0, column=0, padx=2)
    stop_capture_btn.grid(row=0, column=1, padx=2)

    retention_frame = ttk.Frame(packet_frame)
    retention_frame.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 0))
    ttk.Label(retention_frame, text="보관 패킷 수").pack(side="left")
    packet_limit_entry = ttk.Entry(retention_frame, textvariable=packet_limit_var, width=8)
    packet_limit_entry.pack(side="left", padx=(4, 10))

    channel_info_btn = ttk.Button(retention_frame, text="채널정보")
    channel_info_btn.pack(side="left")

    packet_tree = ttk.Treeview(packet_frame, columns=("payload",), show="tree", height=10)
    packet_tree.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
    packet_tree_scroll = ttk.Scrollbar(packet_frame, orient="vertical", command=packet_tree.yview)
    packet_tree.configure(yscrollcommand=packet_tree_scroll.set)
    packet_tree_scroll.grid(row=4, column=3, sticky="ns", pady=8)

    packet_counter = 0
    packet_items: deque[str] = deque()
    channel_info_window: tk.Toplevel | None = None
    channel_treeview: ttk.Treeview | None = None
    channel_name_patterns = {
        "flex": re.compile(r"[A-Z]-[가-힣]\d{2,3}"),
        "strict": re.compile(r"[A-Z]-[가-힣]\d{3}"),
    }

    test_window: tk.Toplevel | None = None
    test_treeview: ttk.Treeview | None = None
    test_detail_text: tk.Text | None = None
    test_pattern_table: ttk.Treeview | None = None
    test_records: list[tuple[str, str, str | None, str, list[list[str]]]] = []
    pattern_table_regex = re.compile(r"[A-Z][가-힣]\d{2,3}")

    def format_timestamp(ts: float) -> str:
        ts_int = int(ts)
        millis = int((ts - ts_int) * 1000)
        return time.strftime('%H:%M:%S', time.localtime(ts)) + f".{millis:03d}"

    class ChannelSegmentRecorder:
        anchor_keyword = "ChannelName"

        def __init__(self, on_capture: Callable[[str], None]) -> None:
            self._on_capture = on_capture
            self._buffer = ""
            self._active = False
            self._start_idx = 0
            self._last_anchor_idx = 0
            self._scan_start_idx = 0
            self._found_followup = False

        @staticmethod
        def _normalize(text: str) -> str:
            return re.sub(r"[^A-Za-z0-9가-힣]+", "", text)

        def feed(self, text: str) -> None:
            normalized = self._normalize(text)
            if not normalized:
                return
            self._process(normalized)

        def _process(self, normalized: str) -> None:
            self._buffer += normalized

            while True:
                if not self._active:
                    if not self._activate_from_buffer():
                        break

                if not self._scan_active_segment():
                    break

        def _activate_from_buffer(self) -> bool:
            channel_idx = self._buffer.find(self.anchor_keyword)
            if channel_idx == -1:
                return False

            if channel_idx > 0:
                self._buffer = self._buffer[channel_idx:]
                channel_idx = 0

            self._active = True
            self._start_idx = channel_idx
            self._last_anchor_idx = channel_idx
            self._scan_start_idx = channel_idx + len(self.anchor_keyword)
            self._found_followup = False
            return True

        def _scan_active_segment(self) -> bool:
            while self._active:
                window_limit = self._last_anchor_idx + 100
                next_idx = self._buffer.find(self.anchor_keyword, self._scan_start_idx)

                if next_idx != -1 and next_idx <= window_limit:
                    self._last_anchor_idx = next_idx
                    self._scan_start_idx = next_idx + len(self.anchor_keyword)
                    self._found_followup = True
                    continue

                has_surpassed_window = len(self._buffer) > window_limit
                next_is_beyond_window = next_idx != -1 and next_idx > window_limit

                if not has_surpassed_window and not next_is_beyond_window:
                    return False

                self._capture_segment()
                return True

            return False

        def _capture_segment(self) -> None:
            end_idx = self._last_anchor_idx + len(self.anchor_keyword)
            if self._found_followup:
                capture = self._buffer[self._start_idx:end_idx]
                self._on_capture(capture)

            self._buffer = self._buffer[end_idx:]
            self._active = False
            self._start_idx = 0
            self._last_anchor_idx = 0
            self._scan_start_idx = 0
            self._found_followup = False

    def append_packet_group(
        timestamp_sec: float, payloads: list[str], *, label_prefix: str | None = None
    ) -> None:
        nonlocal packet_counter

        def _summary_text(text: str) -> str:
            first_line = text.splitlines()[0] if text.strip() else "(내용 없음)"
            return (first_line[:80] + "…") if len(first_line) > 80 else first_line

        packet_counter += 1
        prefix = f"{label_prefix} " if label_prefix else ""
        parent_label = f"{packet_counter}. {prefix}{format_timestamp(timestamp_sec)} ({len(payloads)}개)"
        parent_id = packet_tree.insert("", "end", text=parent_label, open=False)

        for payload in payloads:
            summary_id = packet_tree.insert(parent_id, "end", text=_summary_text(payload), open=False)
            for line in payload.splitlines():
                packet_tree.insert(summary_id, "end", text=line if line else "(빈 줄)")

        packet_items.append(parent_id)
        _trim_packet_items()
        packet_tree.see(parent_id)

    def get_packet_limit() -> int:
        try:
            limit = int(float(packet_limit_var.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror("보관 패킷 수", "보관할 패킷 수를 숫자로 입력하세요.")
            limit = 200
        if limit < 1:
            messagebox.showerror("보관 패킷 수", "최소 1개 이상 보관해야 합니다.")
            limit = 1
        packet_limit_var.set(str(limit))
        return limit

    def _trim_packet_items() -> None:
        max_packets = get_packet_limit()
        while len(packet_items) > max_packets:
            oldest_id = packet_items.popleft()
            packet_tree.delete(oldest_id)

    def flush_packet_queue() -> None:
        nonlocal packet_flush_job
        with packet_queue_lock:
            if not packet_queue:
                packet_flush_job = None
                return
            batch = list(packet_queue)
            packet_queue.clear()
            packet_flush_job = None

        grouped_payloads: dict[float, list[str]] = {}
        for timestamp_sec, payload in batch:
            grouped_payloads.setdefault(timestamp_sec, []).append(payload)

        for timestamp_sec, payloads in grouped_payloads.items():
            append_packet_group(timestamp_sec, payloads)

    def schedule_packet_flush() -> None:
        nonlocal packet_flush_job
        if packet_flush_job is not None:
            return
        packet_flush_job = root.after(200, flush_packet_queue)

    def process_packet_detection(text: str) -> None:
        new_channel_logged = detect_channel_names(text)
        detect_channel_packet(text, new_channel_logged)
        channel_segment_recorder.feed(text)

    def enqueue_packet_text(text: str) -> None:
        timestamp_sec = int(time.time())
        with packet_queue_lock:
            packet_queue.append((timestamp_sec, text))
        root.after(0, schedule_packet_flush)
        root.after(0, process_packet_detection, text)

    def collect_app_state() -> dict:
        coordinates: dict[str, dict[str, str]] = {}
        for key, (x_entry, y_entry) in entries.items():
            coordinates[key] = {"x": x_entry.get(), "y": y_entry.get()}
        return {
            "coordinates": coordinates,
            "delay_f2_before_esc_ms": f2_before_esc_var.get(),
            "delay_f2_before_pos1_ms": f2_before_pos1_var.get(),
            "delay_f2_before_pos2_ms": f2_before_pos2_var.get(),
            "delay_f1_before_pos3_ms": f1_before_pos3_var.get(),
            "delay_f1_before_enter_ms": f1_before_enter_var.get(),
            "delay_f1_newline_before_pos4_ms": f1_newline_before_pos4_var.get(),
            "delay_f1_newline_before_pos3_ms": f1_newline_before_pos3_var.get(),
            "delay_f1_newline_before_enter_ms": f1_newline_before_enter_var.get(),
            "channel_wait_window_ms": channel_wait_window_var.get(),
            "packet_port": packet_port_var.get(),
            "packet_limit": packet_limit_var.get(),
            "newline_after_pos2": newline_var.get(),
            "detect_three_digit_channel": three_digit_channel_var.get(),
            "channel_names": sorted(channel_names),
        }

    def get_port_value() -> int | None:
        try:
            port_value = int(packet_port_var.get())
        except ValueError:
            messagebox.showerror("포트 오류", "포트 번호를 숫자로 입력하세요.")
            return None
        if port_value <= 0 or port_value > 65535:
            messagebox.showerror("포트 오류", "포트 번호는 1~65535 사이여야 합니다.")
            return None
        return port_value

    def start_packet_capture() -> None:
        if packet_manager.running:
            messagebox.showinfo("패킷 캡쳐", "이미 캡쳐가 진행 중입니다.")
            return
        port_value = get_port_value()
        if port_value is None:
            return
        try:
            packet_manager.set_port(port_value)
        except ValueError as exc:
            messagebox.showerror("포트 오류", str(exc))
            return
        started = packet_manager.start()
        if not started:
            packet_status_var.set("패킷 캡쳐 시작 실패")
            start_capture_btn.configure(state="normal")
            stop_capture_btn.configure(state="disabled")
            return

        packet_status_var.set(f"포트 {port_value} 캡쳐 중...")
        start_capture_btn.configure(state="disabled")
        stop_capture_btn.configure(state="normal")

    def stop_packet_capture() -> None:
        if not packet_manager.running:
            packet_status_var.set("패킷 캡쳐 중지됨")
            start_capture_btn.configure(state="normal")
            stop_capture_btn.configure(state="disabled")
            return

        packet_status_var.set("패킷 캡쳐 중지 중…")
        start_capture_btn.configure(state="disabled")
        stop_capture_btn.configure(state="disabled")

        def _stop_capture_in_thread() -> None:
            try:
                packet_manager.stop()
            finally:
                root.after(0, _finalize_stop_capture)

        def _finalize_stop_capture() -> None:
            packet_status_var.set("패킷 캡쳐 중지됨")
            start_capture_btn.configure(state="normal")
            stop_capture_btn.configure(state="disabled")

        threading.Thread(target=_stop_capture_in_thread, daemon=True).start()

    start_capture_btn.configure(command=start_packet_capture)
    stop_capture_btn.configure(command=stop_packet_capture)
    channel_info_btn.configure(command=lambda: show_channel_info_window())

    def extract_channel_names(payload: str) -> list[str]:
        normalized = payload.replace("\n", "")
        pattern_key = "strict" if three_digit_channel_var.get() else "flex"
        pattern = channel_name_patterns[pattern_key]
        return [match.group(0) for match in pattern.finditer(normalized)]

    def refresh_channel_treeview() -> None:
        nonlocal channel_treeview
        if channel_treeview is None:
            return
        for item in channel_treeview.get_children():
            channel_treeview.delete(item)
        for idx, name in enumerate(sorted(channel_names), start=1):
            channel_treeview.insert("", "end", text=f"{idx}. {name}")

    def log_new_channel(name: str) -> None:
        timestamp = time.time()
        append_packet_group(timestamp, [f"[새 채널] ({name})"])
        channel_alert_var.set(f"{format_timestamp(timestamp)} 새 채널 감지: {name}")

    def detect_channel_names(payload: str) -> bool:
        new_found = False
        for candidate in extract_channel_names(payload):
            if candidate not in channel_names:
                channel_names.add(candidate)
                new_found = True
                log_new_channel(candidate)
        if new_found:
            refresh_channel_treeview()
        return new_found

    def log_channel_packet(payload: str) -> None:
        timestamp = time.time()
        append_packet_group(timestamp, [f"[ChannelName 감지] {payload}"])
        channel_packet_alert_var.set(f"{format_timestamp(timestamp)} ChannelName 패킷 감지")

    class ChannelDetectionSequence:
        def __init__(self) -> None:
            self.running = False
            self.packet_queue: Queue[tuple[float, bool]] = Queue()
            self.newline_mode = False

        def start(self, newline_mode: bool) -> None:
            if self.running:
                messagebox.showinfo("매크로", "F3 매크로가 이미 실행 중입니다.")
                return
            self.running = True
            self._clear_queue()
            self.newline_mode = newline_mode
            controller.set_input_logger(debug_recorder)
            debug_recorder.start()
            append_debug_log("F3 매크로 시작")
            threading.Thread(target=self._run_sequence, daemon=True).start()

        def stop(self) -> None:
            self.running = False
            self._clear_queue()
            debug_recorder.stop()
            controller.set_input_logger(None)
            append_debug_log("F3 매크로 중단")

        def notify_channel_packet(self, new_channel_logged: bool) -> None:
            if not self.running:
                return
            self.packet_queue.put((time.time(), new_channel_logged))

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
                    self.packet_queue.get_nowait()
                except Empty:
                    break

        def _get_packet(self, timeout: float | None) -> tuple[float, bool] | None:
            if not self.running:
                return None

            if timeout is None:
                interval = 0.1
                while self.running:
                    try:
                        return self.packet_queue.get(timeout=interval)
                    except Empty:
                        continue
                return None

            end_time = time.time() + timeout
            while self.running and time.time() < end_time:
                remaining = max(end_time - time.time(), 0)
                wait_time = min(0.1, remaining)
                try:
                    return self.packet_queue.get(timeout=wait_time)
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

                    self._set_status("F3: ChannelName 문자열을 기다리는 중…")
                    first_packet = self._get_packet(timeout=None)
                    if first_packet is None:
                        break

                    log_detected = first_packet[1]
                    wait_window_sec = self._delay_seconds(get_channel_wait_window_ms())
                    detection_deadline = time.time() + wait_window_sec if log_detected else None
                    should_run_macro = False

                    while self.running:
                        timeout = wait_window_sec
                        if detection_deadline is not None:
                            timeout = max(detection_deadline - time.time(), 0)

                        next_packet = self._get_packet(timeout=timeout)
                        if next_packet is None:
                            if log_detected and detection_deadline is not None:
                                should_run_macro = True
                            break

                        log_detected = log_detected or next_packet[1]
                        if log_detected and detection_deadline is None:
                            detection_deadline = time.time() + wait_window_sec

                        if (
                            log_detected
                            and detection_deadline is not None
                            and time.time() >= detection_deadline
                        ):
                            should_run_macro = True
                            break

                    if not self.running:
                        break

                    if should_run_macro and log_detected:
                        self._set_status("F3: 조건 충족, F1 실행 중…")
                        self._run_on_main(
                            lambda: controller.run_step(newline_mode=self.newline_mode)
                        )
                        break

                    self._set_status("F3: 새 채널 미감지, 재시도…")
            finally:
                self.running = False
                self._run_on_main(controller._update_status)
                debug_recorder.stop()
                controller.set_input_logger(None)
                append_debug_log("F3 매크로 종료")

        def _delay_seconds(self, delay_ms: int) -> float:
            return max(delay_ms, 0) / 1000

    channel_detection_sequence = ChannelDetectionSequence()

    def detect_channel_packet(payload: str, new_channel_logged: bool) -> None:
        if ChannelSegmentRecorder.anchor_keyword in payload:
            log_channel_packet(payload)
            channel_detection_sequence.notify_channel_packet(new_channel_logged)

    def delete_selected_channel() -> None:
        if channel_treeview is None:
            return
        selected_items = channel_treeview.selection()
        if not selected_items:
            messagebox.showinfo("채널 삭제", "삭제할 채널을 선택하세요.")
            return

        removed = False
        for item_id in selected_items:
            text = channel_treeview.item(item_id, "text")
            _, _, channel_name = text.partition(". ")
            target = channel_name or text
            if target in channel_names:
                channel_names.remove(target)
                removed = True

        if removed:
            refresh_channel_treeview()

    def clear_all_channels() -> None:
        if not channel_names:
            messagebox.showinfo("채널 초기화", "삭제할 채널 정보가 없습니다.")
            return
        if not messagebox.askyesno("채널 초기화", "모든 채널 정보를 삭제할까요?"):
            return

        channel_names.clear()
        refresh_channel_treeview()
        status_var.set("채널 정보가 초기화되었습니다.")

    def show_channel_info_window() -> None:
        nonlocal channel_info_window, channel_treeview
        if channel_info_window is not None and tk.Toplevel.winfo_exists(channel_info_window):
            channel_info_window.lift()
            refresh_channel_treeview()
            return
        channel_info_window = tk.Toplevel(root)
        channel_info_window.title("채널 정보")
        channel_info_window.geometry("300x300")
        channel_info_window.resizable(False, True)

        tree = ttk.Treeview(channel_info_window, columns=("name",), show="tree")
        tree.pack(fill="both", expand=True, padx=8, pady=8)
        tree_scroll = ttk.Scrollbar(channel_info_window, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y", padx=(0, 8))

        button_bar = ttk.Frame(channel_info_window)
        button_bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(button_bar, text="초기화", command=clear_all_channels).pack(side="left")
        ttk.Button(button_bar, text="선택 삭제", command=delete_selected_channel).pack(side="right")

        channel_treeview = tree
        refresh_channel_treeview()

        def on_close_channel_window() -> None:
            nonlocal channel_info_window, channel_treeview
            window = channel_info_window
            channel_info_window = None
            channel_treeview = None
            tree_scroll.destroy()
            tree.destroy()
            if window is not None:
                window.destroy()

        channel_info_window.protocol("WM_DELETE_WINDOW", on_close_channel_window)

    def build_pattern_table(text: str) -> tuple[str | None, list[list[str]]]:
        matches = pattern_table_regex.findall(text)
        if not matches:
            return None, []

        col_width = max(len(match) for match in matches)
        rows_for_view: list[list[str]] = []
        formatted_rows: list[str] = []
        for idx in range(0, len(matches), 6):
            chunk = matches[idx : idx + 6]
            padded = chunk + [""] * (6 - len(chunk))
            rows_for_view.append(padded)
            formatted_rows.append(
                " | ".join(cell.ljust(col_width) if cell else "".ljust(col_width) for cell in padded)
            )

        return "\n".join(formatted_rows), rows_for_view

    def update_pattern_table(rows: list[list[str]] | None = None) -> None:
        if test_pattern_table is None:
            return

        for item in test_pattern_table.get_children():
            test_pattern_table.delete(item)

        if not rows:
            test_pattern_table.insert("", "end", values=("(없음)", "", "", "", "", ""))
            return

        for row in rows:
            padded = row + [""] * (6 - len(row))
            test_pattern_table.insert("", "end", values=padded)

    def add_test_record(content: str) -> None:
        timestamp = format_timestamp(time.time())
        table_text, table_rows = build_pattern_table(content)
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
            update_pattern_table(table_rows)

    def update_test_detail(selected_index: int | None = None) -> None:
        if test_detail_text is None:
            return

        test_detail_text.configure(state="normal")
        test_detail_text.delete("1.0", "end")

        if selected_index is None or selected_index < 1 or selected_index > len(test_records):
            test_detail_text.insert("1.0", "기록을 선택하세요.")
            update_pattern_table(None)
        else:
            _, content, table_text, _, table_rows = test_records[selected_index - 1]
            patterns = table_text or "(없음)"
            detail_text = f"{content}\n\n[추출된 패턴]\n{patterns}"
            test_detail_text.insert("1.0", detail_text)
            update_pattern_table(table_rows)

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
        test_records.clear()
        refresh_test_treeview()
        update_pattern_table(None)
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
                "ChannelName 문자열이 감지되면 해당 ChannelName으로부터 정규화된 기준 100자 "
                "내에서 다음 ChannelName을 찾고, 발견된 ChannelName을 새 기준점으로 삼아 "
                "동일한 방식으로 반복 탐색하여 더 이상 ChannelName이 없을 때까지 "
                "기록합니다."
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

    channel_segment_recorder = ChannelSegmentRecorder(add_test_record)

    test_button.configure(command=show_test_window)

    def on_hotkey_press(key: keyboard.Key) -> None:
        if key == keyboard.Key.f1:
            root.after(0, controller.run_step)
        elif key == keyboard.Key.f2:
            root.after(0, controller.reset_and_run_first)
        elif key == keyboard.Key.f3:
            if channel_detection_sequence.running:
                channel_detection_sequence.stop()
                status_var.set("F3 매크로가 종료되었습니다.")
                controller._update_status()
            else:
                channel_detection_sequence.start(newline_var.get())

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
        debug_recorder.stop()
        stop_packet_capture()
        root.destroy()

    start_hotkey_listener()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
