"""단계별 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, 실행/다시 버튼으로
순차 동작을 제어합니다.
"""

import time
import tkinter as tk
from tkinter import messagebox, ttk

from makr.packet import PacketCaptureManager

import pyautogui
from pynput import keyboard, mouse


class MacroController:
    """실행 순서를 관리하고 GUI 콜백을 제공합니다."""

    def __init__(self, entries: dict[str, tuple[tk.Entry, tk.Entry]], status_var: tk.StringVar) -> None:
        self.entries = entries
        self.status_var = status_var
        self.current_step = 1
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
        time.sleep(0.1)
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

    status_var = tk.StringVar()
    repeat_delay_var = tk.StringVar(value="750")
    packet_status_var = tk.StringVar(value="패킷 캡쳐 중지됨")
    repeat_running = False
    repeat_job_id: str | None = None
    alert_keywords: list[str] = []

    entries: dict[str, tuple[tk.Entry, tk.Entry]] = {}
    capture_listener: mouse.Listener | None = None
    hotkey_listener: keyboard.Listener | None = None
    packet_manager = PacketCaptureManager(
        on_packet=lambda text: root.after(0, append_packet_text, text),
        on_alert=lambda keyword, payload: root.after(0, log_packet_alert, keyword, payload),
        on_error=lambda msg: root.after(0, messagebox.showerror, "패킷 캡쳐 오류", msg),
    )

    def add_coordinate_row(label_text: str, key: str) -> None:
        frame = tk.Frame(root)
        frame.pack(fill="x", padx=10, pady=5)

        tk.Label(frame, text=label_text, width=8, anchor="w").pack(side="left")
        x_entry = tk.Entry(frame, width=6)
        x_entry.pack(side="left", padx=(0, 4))
        x_entry.insert(0, "0")

        y_entry = tk.Entry(frame, width=6)
        y_entry.pack(side="left")
        y_entry.insert(0, "0")

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

    controller = MacroController(entries, status_var)

    button_frame = tk.Frame(root)
    button_frame.pack(pady=10)

    run_button = tk.Button(button_frame, text="실행 (F1)", width=12, command=controller.run_step)
    run_button.pack(side="left", padx=5)

    reset_button = tk.Button(button_frame, text="다시 (F2)", width=12, command=controller.reset_and_run_first)
    reset_button.pack(side="left", padx=5)

    delay_frame = tk.Frame(root)
    delay_frame.pack(fill="x", padx=10)

    tk.Label(delay_frame, text="F3 반복 딜레이 (ms)", width=16, anchor="w").pack(side="left")
    delay_entry = tk.Entry(delay_frame, textvariable=repeat_delay_var, width=8)
    delay_entry.pack(side="left", padx=(0, 6))
    tk.Label(delay_frame, text="반복 실행 사이 대기 시간을 설정합니다.").pack(side="left")

    status_label = tk.Label(root, textvariable=status_var, fg="#006400")
    status_label.pack(pady=(0, 10))

    packet_frame = ttk.LabelFrame(root, text="패킷 캡쳐")
    packet_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    packet_frame.columnconfigure(0, weight=1)
    packet_frame.rowconfigure(3, weight=1)

    packet_status_label = ttk.Label(packet_frame, textvariable=packet_status_var, foreground="#0a5")
    packet_status_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))

    ttk.Label(packet_frame, text="포트").grid(row=1, column=0, sticky="w", padx=8)
    packet_port_var = tk.StringVar(value="32800")
    packet_port_entry = ttk.Entry(packet_frame, textvariable=packet_port_var, width=10)
    packet_port_entry.grid(row=1, column=1, sticky="w")

    packet_control_frame = ttk.Frame(packet_frame)
    packet_control_frame.grid(row=1, column=2, sticky="e", padx=8)
    start_capture_btn = ttk.Button(packet_control_frame, text="캡쳐 시작")
    stop_capture_btn = ttk.Button(packet_control_frame, text="캡쳐 중지", state="disabled")
    start_capture_btn.grid(row=0, column=0, padx=2)
    stop_capture_btn.grid(row=0, column=1, padx=2)

    alert_frame = ttk.LabelFrame(packet_frame, text="패킷 알림")
    alert_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=8, pady=(6, 0))
    alert_frame.columnconfigure(0, weight=1)
    alert_frame.rowconfigure(1, weight=1)

    alert_entry = ttk.Entry(alert_frame)
    alert_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=6)
    alert_listbox = tk.Listbox(alert_frame, height=4)
    alert_listbox.grid(row=1, column=0, sticky="nsew")
    alert_scroll = ttk.Scrollbar(alert_frame, orient="vertical", command=alert_listbox.yview)
    alert_listbox.configure(yscrollcommand=alert_scroll.set)
    alert_scroll.grid(row=1, column=1, sticky="ns")

    packet_text = tk.Text(packet_frame, wrap="word", height=8, state="disabled")
    packet_text.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
    packet_text_scroll = ttk.Scrollbar(packet_frame, orient="vertical", command=packet_text.yview)
    packet_text.configure(yscrollcommand=packet_text_scroll.set)
    packet_text_scroll.grid(row=3, column=3, sticky="ns", pady=8)

    def append_packet_text(text: str) -> None:
        packet_text.configure(state="normal")
        packet_text.insert(tk.END, text if text.endswith("\n") else text + "\n")
        packet_text.see(tk.END)
        packet_text.configure(state="disabled")

    def log_packet_alert(keyword: str, payload: str) -> None:
        append_packet_text(f"[알림] '{keyword}' 포함 패킷 감지: {payload}\n")
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
        packet_manager.stop()
        packet_status_var.set("패킷 캡쳐 중지됨")
        start_capture_btn.configure(state="normal")
        stop_capture_btn.configure(state="disabled")

    ttk.Button(alert_frame, text="문자열 등록", command=add_alert_keyword).grid(
        row=0, column=1, sticky="ew", pady=6
    )
    ttk.Button(alert_frame, text="선택 삭제", command=remove_selected_alert).grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(6, 6)
    )

    start_capture_btn.configure(command=start_packet_capture)
    stop_capture_btn.configure(command=stop_packet_capture)

    def on_hotkey_press(key: keyboard.Key) -> None:
        if key == keyboard.Key.f1:
            root.after(0, controller.run_step)
        elif key == keyboard.Key.f2:
            root.after(0, controller.reset_and_run_first)
        elif key == keyboard.Key.f3:
            root.after(0, toggle_repeat)

    def get_repeat_delay_ms() -> int:
        try:
            delay_ms = int(float(repeat_delay_var.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror("반복 딜레이 오류", "반복 딜레이를 숫자로 입력하세요.")
            delay_ms = 750
            repeat_delay_var.set(str(delay_ms))
        if delay_ms < 0:
            messagebox.showerror("반복 딜레이 오류", "반복 딜레이는 0 이상이어야 합니다.")
            delay_ms = 0
            repeat_delay_var.set("0")
        return delay_ms

    def schedule_next_repeat() -> None:
        nonlocal repeat_job_id
        delay_ms = get_repeat_delay_ms()
        repeat_job_id = root.after(delay_ms, run_repeat_cycle)

    def run_repeat_cycle() -> None:
        if not repeat_running:
            return
        controller.reset_and_run_first()

        def run_first_step_after_delay() -> None:
            if not repeat_running:
                return
            controller.run_step()
            if repeat_running:
                schedule_next_repeat()

        root.after(200, run_first_step_after_delay)

    def stop_repeat() -> None:
        nonlocal repeat_running, repeat_job_id
        repeat_running = False
        if repeat_job_id is not None:
            root.after_cancel(repeat_job_id)
            repeat_job_id = None
        status_var.set("반복 실행을 종료했습니다.")

    def start_repeat() -> None:
        nonlocal repeat_running
        repeat_running = True
        delay_ms = get_repeat_delay_ms()
        status_var.set(f"F2 → F1 반복을 시작합니다. (딜레이 {delay_ms}ms)")
        run_repeat_cycle()

    def toggle_repeat() -> None:
        if repeat_running:
            stop_repeat()
        else:
            start_repeat()

    def start_hotkey_listener() -> None:
        nonlocal hotkey_listener
        if hotkey_listener is not None:
            return
        hotkey_listener = keyboard.Listener(on_press=on_hotkey_press)
        hotkey_listener.start()

    def on_close() -> None:
        if hotkey_listener is not None:
            hotkey_listener.stop()
        stop_packet_capture()
        stop_repeat()
        root.destroy()

    start_hotkey_listener()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
