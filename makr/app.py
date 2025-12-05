"""단계별 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, 실행/다시 버튼으로
순차 동작을 제어합니다.
"""

import time
import tkinter as tk
from tkinter import messagebox

import pyautogui


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

    entries: dict[str, tuple[tk.Entry, tk.Entry]] = {}

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

    tk.Label(root, text="좌표는 화면 기준 픽셀 단위로 입력하세요 (X, Y).", fg="#444").pack(pady=(10, 0))

    add_coordinate_row("pos1", "pos1")
    add_coordinate_row("pos2", "pos2")
    add_coordinate_row("pos3", "pos3")

    controller = MacroController(entries, status_var)

    button_frame = tk.Frame(root)
    button_frame.pack(pady=10)

    run_button = tk.Button(button_frame, text="실행", width=10, command=controller.run_step)
    run_button.pack(side="left", padx=5)

    reset_button = tk.Button(button_frame, text="다시", width=10, command=controller.reset_and_run_first)
    reset_button.pack(side="left", padx=5)

    status_label = tk.Label(root, textvariable=status_var, fg="#006400")
    status_label.pack(pady=(0, 10))

    root.mainloop()


if __name__ == "__main__":
    build_gui()
