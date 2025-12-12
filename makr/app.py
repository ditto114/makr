"""단계별 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, 실행/다시 버튼으로
순차 동작을 제어합니다.
"""

import json
import re
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from makr.packet import PacketCaptureManager

import pyautogui
from pynput import keyboard, mouse

APP_STATE_PATH = Path(__file__).with_name("app_state.json")


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


class MacroController:
    """실행 순서를 관리하고 GUI 콜백을 제공합니다."""

    def __init__(
        self,
        entries: dict[str, tuple[tk.Entry, tk.Entry]],
        status_var: tk.StringVar,
        click_delay_provider: Callable[[], int],
        step_transition_delay_provider: Callable[[], int],
    ) -> None:
        self.entries = entries
        self.status_var = status_var
        self.current_step = 1
        self.click_delay_provider = click_delay_provider
        self.step_transition_delay_provider = step_transition_delay_provider
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

    def _click_point(self, point: tuple[int, int]) -> None:
        x_val, y_val = point
        pyautogui.click(x_val, y_val)

    def _delay_seconds(self, delay_ms: int) -> float:
        return max(delay_ms, 0) / 1000

    def run_step(self) -> None:
        """실행 버튼 콜백: 현재 단계 수행 후 다음 단계로 이동."""
        if self.current_step == 1:
            self._run_step_one()
            self.current_step = 2
        else:
            self._run_step_two()
            self.current_step = 1
        self._update_status()

    def reset_and_run_first(self) -> None:
        """다시 버튼 콜백: Esc 입력 후 1단계를 재실행."""
        pyautogui.press("esc")
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
        self._click_point(pos1)
        click_delay_sec = self._delay_seconds(self.click_delay_provider())
        if click_delay_sec:
            time.sleep(click_delay_sec)
        self._click_point(pos2)

    def _run_step_two(self) -> None:
        pos3 = self._get_point("pos3")
        if pos3 is None:
            return
        self._click_point(pos3)
        pyautogui.press("enter")


def build_gui() -> None:
    root = tk.Tk()
    root.title("단계별 자동화")
    root.attributes("-topmost", True)

    saved_state = load_app_state()

    status_var = tk.StringVar()
    click_delay_var = tk.StringVar(value=str(saved_state.get("click_delay_ms", "100")))
    step_transition_delay_var = tk.StringVar(value=str(saved_state.get("step_transition_delay_ms", "200")))
    channel_detection_delay_var = tk.StringVar(
        value=str(saved_state.get("channel_detection_delay_ms", "0"))
    )
    packet_limit_var = tk.StringVar(value=str(saved_state.get("packet_limit", "200")))
    packet_status_var = tk.StringVar(value="패킷 캡쳐 중지됨")
    alert_keywords: list[str] = list(saved_state.get("alert_keywords", []))
    channel_names: set[str] = set(saved_state.get("channel_names", []))

    entries: dict[str, tuple[tk.Entry, tk.Entry]] = {}
    packet_queue: deque[str] = deque()
    packet_queue_lock = threading.Lock()
    packet_flush_job: str | None = None
    channel_cycle_running = False
    channel_waiting_for_packet = False
    capture_listener: mouse.Listener | None = None
    hotkey_listener: keyboard.Listener | None = None
    packet_manager = PacketCaptureManager(
        on_packet=lambda text: enqueue_packet_text(text),
        on_alert=lambda keyword, payload: root.after(0, log_packet_alert, keyword, payload),
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

    def get_click_delay_ms() -> int:
        return _parse_delay_ms(click_delay_var, "1단계 클릭 딜레이", 100)

    def get_step_transition_delay_ms() -> int:
        return _parse_delay_ms(step_transition_delay_var, "1→2단계 전환 딜레이", 200)

    def get_channel_detection_delay_ms() -> int:
        return _parse_delay_ms(channel_detection_delay_var, "Channel 감지 후 실행 딜레이", 0)

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

    tk.Label(root, text="좌표는 화면 기준 픽셀 단위로 입력하세요 (X, Y).", fg="#444").pack(pady=(10, 0))

    add_coordinate_row("pos1", "pos1")
    add_coordinate_row("pos2", "pos2")
    add_coordinate_row("pos3", "pos3")

    controller = MacroController(
        entries,
        status_var,
        click_delay_provider=get_click_delay_ms,
        step_transition_delay_provider=get_step_transition_delay_ms,
    )

    button_frame = tk.Frame(root)
    button_frame.pack(pady=10)

    run_button = tk.Button(button_frame, text="실행 (F1)", width=12, command=controller.run_step)
    run_button.pack(side="left", padx=5)

    reset_button = tk.Button(button_frame, text="다시 (F2)", width=12, command=controller.reset_and_run_first)
    reset_button.pack(side="left", padx=5)

    delay_frame = tk.LabelFrame(root, text="딜레이 설정")
    delay_frame.pack(fill="x", padx=10, pady=(0, 10))

    def add_delay_input(label: str, var: tk.StringVar, description: str) -> None:
        row = tk.Frame(delay_frame)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=label, width=18, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=var, width=8).pack(side="left", padx=(0, 6))
        tk.Label(row, text=description).pack(side="left")

    add_delay_input("1단계 클릭 간 (ms)", click_delay_var, "pos1 → pos2 클릭 사이 지연입니다.")
    add_delay_input(
        "1→2단계 전환 (ms)",
        step_transition_delay_var,
        "반복 실행 시 1단계 후 2단계로 넘어가기 전 대기 시간입니다.",
    )
    add_delay_input(
        "Channel 감지 후 실행 (ms)",
        channel_detection_delay_var,
        "'Channel' 문자열 감지 후 F1 단계 실행까지 대기 시간입니다.",
    )

    status_label = tk.Label(root, textvariable=status_var, fg="#006400")
    status_label.pack(pady=(0, 10))

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

    alert_frame = ttk.LabelFrame(packet_frame, text="패킷 알림")
    alert_frame.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=(6, 0))
    alert_frame.columnconfigure(0, weight=1)
    alert_frame.rowconfigure(1, weight=1)

    alert_entry = ttk.Entry(alert_frame)
    alert_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=6)
    alert_listbox = tk.Listbox(alert_frame, height=4)
    alert_listbox.grid(row=1, column=0, sticky="nsew")
    alert_scroll = ttk.Scrollbar(alert_frame, orient="vertical", command=alert_listbox.yview)
    alert_listbox.configure(yscrollcommand=alert_scroll.set)
    alert_scroll.grid(row=1, column=1, sticky="ns")

    packet_tree = ttk.Treeview(packet_frame, columns=("payload",), show="tree", height=10)
    packet_tree.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
    packet_tree_scroll = ttk.Scrollbar(packet_frame, orient="vertical", command=packet_tree.yview)
    packet_tree.configure(yscrollcommand=packet_tree_scroll.set)
    packet_tree_scroll.grid(row=4, column=3, sticky="ns", pady=8)

    packet_counter = 0
    packet_items: deque[str] = deque()
    channel_info_window: tk.Toplevel | None = None
    channel_treeview: ttk.Treeview | None = None

    def append_packet_payload(payload: str, *, summary: str | None = None) -> None:
        nonlocal packet_counter

        def _summary_text(text: str) -> str:
            first_line = text.splitlines()[0] if text.strip() else "(내용 없음)"
            return (first_line[:80] + "…") if len(first_line) > 80 else first_line

        packet_counter += 1
        parent_text = f"{packet_counter}. {summary or _summary_text(payload)}"
        parent_id = packet_tree.insert("", "end", text=parent_text, open=False)
        for line in payload.splitlines():
            packet_tree.insert(parent_id, "end", text=line if line else "(빈 줄)")
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
        for payload in batch:
            append_packet_payload(payload)

    def schedule_packet_flush() -> None:
        nonlocal packet_flush_job
        if packet_flush_job is not None:
            return
        packet_flush_job = root.after(200, flush_packet_queue)

    def enqueue_packet_text(text: str) -> None:
        with packet_queue_lock:
            packet_queue.append(text)
        root.after(0, schedule_packet_flush)
        root.after(0, handle_channel_detection, text)
        root.after(0, extract_and_store_channel_names, text)

    def log_packet_alert(keyword: str, payload: str) -> None:
        append_packet_payload(payload, summary=f"[알림] '{keyword}' 포함 패킷")
        print(f"[패킷 알림] '{keyword}' 문자열이 포함된 패킷이 감지되었습니다.")

    def refresh_alerts() -> None:
        alert_listbox.delete(0, tk.END)
        for text in alert_keywords:
            alert_listbox.insert(tk.END, text)

    def add_alert_keyword() -> None:
        keyword = alert_entry.get().strip()
        if not keyword:
            messagebox.showinfo("알림 문자열", "등록할 문자열을 입력하세요.")
            return
        if keyword not in alert_keywords:
            alert_keywords.append(keyword)
            refresh_alerts()
            alert_entry.delete(0, tk.END)
        else:
            messagebox.showinfo("알림 문자열", "이미 등록된 문자열입니다.")

    def remove_selected_alert() -> None:
        selection = alert_listbox.curselection()
        if not selection:
            return
        keyword = alert_listbox.get(selection[0])
        alert_keywords.remove(keyword)
        refresh_alerts()

    def collect_app_state() -> dict:
        coordinates: dict[str, dict[str, str]] = {}
        for key, (x_entry, y_entry) in entries.items():
            coordinates[key] = {"x": x_entry.get(), "y": y_entry.get()}
        return {
            "coordinates": coordinates,
            "click_delay_ms": click_delay_var.get(),
            "step_transition_delay_ms": step_transition_delay_var.get(),
            "channel_detection_delay_ms": channel_detection_delay_var.get(),
            "packet_port": packet_port_var.get(),
            "alert_keywords": alert_keywords,
            "packet_limit": packet_limit_var.get(),
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
        packet_manager.set_alerts(alert_keywords)
        packet_manager.start()
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

    ttk.Button(alert_frame, text="문자열 등록", command=add_alert_keyword).grid(
        row=0, column=1, sticky="ew", pady=6
    )
    ttk.Button(alert_frame, text="선택 삭제", command=remove_selected_alert).grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(6, 6)
    )

    refresh_alerts()

    start_capture_btn.configure(command=start_packet_capture)
    stop_capture_btn.configure(command=stop_packet_capture)
    channel_info_btn.configure(command=lambda: show_channel_info_window())

    def run_channel_cycle_once() -> None:
        nonlocal channel_waiting_for_packet
        if not channel_cycle_running:
            return
        controller.reset_and_run_first()
        channel_waiting_for_packet = True
        status_var.set("'Channel' 문자열 포함 패킷을 기다리는 중입니다.")

    def handle_channel_detection(payload: str) -> None:
        nonlocal channel_waiting_for_packet
        if not (channel_cycle_running and channel_waiting_for_packet):
            return
        if "Channel" not in payload:
            return
        channel_waiting_for_packet = False
        status_var.set("'Channel' 패킷 감지! 2단계를 실행합니다.")
        channel_delay_ms = get_channel_detection_delay_ms()

        def _run_step_after_delay() -> None:
            if not channel_cycle_running:
                return
            controller.run_step()
            if channel_cycle_running:
                root.after(0, run_channel_cycle_once)

        root.after(channel_delay_ms, _run_step_after_delay)

    channel_pattern = re.compile(r"[A-Z]-[가-힣]\d{2,3}")

    def extract_channel_candidates(payload: str) -> list[str]:
        candidates: list[str] = []
        search_start = 0
        while True:
            channel_pos = payload.find("Channel", search_start)
            if channel_pos == -1:
                break
            substring = payload[channel_pos + len("Channel") :]
            match = channel_pattern.search(substring)
            if match:
                candidates.append(match.group(0))
                search_start = channel_pos + len("Channel") + match.end()
            else:
                search_start = channel_pos + len("Channel")
        return candidates

    def refresh_channel_treeview() -> None:
        nonlocal channel_treeview
        if channel_treeview is None:
            return
        for item in channel_treeview.get_children():
            channel_treeview.delete(item)
        for idx, name in enumerate(sorted(channel_names), start=1):
            channel_treeview.insert("", "end", text=f"{idx}. {name}")

    def log_new_channel(name: str) -> None:
        append_packet_payload(f"채널명: {name}", summary=f"[채널] 새 채널 감지: {name}")
        status_var.set("새 채널 감지")

    def extract_and_store_channel_names(payload: str) -> None:
        new_found = False
        for candidate in extract_channel_candidates(payload):
            if candidate not in channel_names:
                channel_names.add(candidate)
                new_found = True
                log_new_channel(candidate)
        if new_found:
            refresh_channel_treeview()

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

        channel_treeview = tree
        refresh_channel_treeview()

        def on_close_channel_window() -> None:
            nonlocal channel_info_window, channel_treeview
            channel_info_window = None
            channel_treeview = None
            tree_scroll.destroy()
            tree.destroy()

        channel_info_window.protocol("WM_DELETE_WINDOW", on_close_channel_window)

    def stop_channel_cycle() -> None:
        nonlocal channel_cycle_running, channel_waiting_for_packet
        channel_cycle_running = False
        channel_waiting_for_packet = False
        status_var.set("Channel 감지 반복을 종료했습니다.")

    def start_channel_cycle() -> None:
        nonlocal channel_cycle_running
        if channel_cycle_running:
            status_var.set("Channel 감지 반복이 이미 실행 중입니다.")
            return
        channel_cycle_running = True
        status_var.set("F2 실행 후 'Channel' 감지까지 대기합니다.")
        run_channel_cycle_once()

    def toggle_channel_cycle() -> None:
        if channel_cycle_running:
            stop_channel_cycle()
        else:
            start_channel_cycle()

    def on_hotkey_press(key: keyboard.Key) -> None:
        if key == keyboard.Key.f1:
            root.after(0, controller.run_step)
        elif key == keyboard.Key.f2:
            root.after(0, controller.reset_and_run_first)
        elif key == keyboard.Key.f3:
            root.after(0, toggle_channel_cycle)

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
        stop_packet_capture()
        stop_channel_cycle()
        root.destroy()

    start_hotkey_listener()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
