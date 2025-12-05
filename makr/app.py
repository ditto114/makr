"""단계별 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, 실행/다시 버튼으로
순차 동작을 제어합니다.
"""

import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageTk
import pyautogui
from pynput import keyboard, mouse

from .gui import capture_image_via_drag


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
    image_path_var = tk.StringVar()
    image_preview: tk.Label | None = None

    entries: dict[str, tuple[tk.Entry, tk.Entry]] = {}
    capture_listener: mouse.Listener | None = None
    hotkey_listener: keyboard.Listener | None = None

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

    image_frame = tk.Frame(root, padx=10, pady=10, bd=1, relief="groove")
    image_frame.pack(fill="x", padx=10, pady=(0, 10))

    preview_label = tk.Label(image_frame, text="등록된 이미지가 없습니다.", width=40, anchor="w")
    preview_label.grid(row=0, column=0, columnspan=2, sticky="w")

    preview_canvas = tk.Label(image_frame, text="미리보기 없음", width=50, height=8, relief="sunken", anchor="center")
    preview_canvas.grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")

    def update_preview(path: Path) -> None:
        nonlocal image_preview
        try:
            image = Image.open(path)
        except Exception as exc:  # pragma: no cover - 로컬 파일/이미지 오류 처리
            messagebox.showerror("미리보기 오류", f"이미지를 불러올 수 없습니다: {exc}")
            image_preview = None
            preview_canvas.config(text="미리보기 없음", image="")
            return

        max_width, max_height = 360, 200
        width, height = image.size
        scale = min(max_width / width, max_height / height, 1)
        if scale != 1:
            new_size = (int(width * scale), int(height * scale))
            image = image.resize(new_size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        preview_canvas.config(image=photo, text="")
        preview_canvas.image = photo  # type: ignore[attr-defined]
        image_preview = preview_canvas
        preview_label.config(text=f"등록된 이미지: {path.name}")

    def capture_image() -> None:
        path = capture_image_via_drag(root)
        if not path:
            return
        image_path_var.set(str(path))
        update_preview(path)
        image_click_button.config(state="normal")
        status_var.set(f"이미지가 등록되었습니다: {path}")

    def click_registered_image() -> None:
        image_path = image_path_var.get()
        if not image_path:
            messagebox.showinfo("이미지 필요", "먼저 이미지를 등록해주세요.")
            return
        path = Path(image_path)
        if not path.exists():
            messagebox.showerror("이미지 없음", "등록된 이미지 파일을 찾을 수 없습니다. 다시 캡쳐하세요.")
            image_click_button.config(state="disabled")
            preview_canvas.config(text="미리보기 없음", image="")
            return

        status_var.set("이미지 위치를 찾는 중입니다...")
        try:
            location = pyautogui.locateOnScreen(str(path), confidence=0.8)
        except Exception as exc:  # pragma: no cover - pyautogui 환경 오류
            messagebox.showerror("이미지 검색 오류", f"이미지를 찾을 수 없습니다: {exc}")
            status_var.set("이미지 검색에 실패했습니다.")
            return

        if not location:
            messagebox.showwarning("미검출", "화면에서 이미지를 찾지 못했습니다.")
            status_var.set("이미지를 찾지 못했습니다.")
            return

        center = pyautogui.center(location)
        pyautogui.click(center.x, center.y)
        status_var.set(f"이미지 위치 클릭 완료: ({center.x}, {center.y})")

    image_button = tk.Button(image_frame, text="이미지", width=10, command=capture_image)
    image_button.grid(row=2, column=0, pady=(8, 0), sticky="w")

    image_click_button = tk.Button(
        image_frame, text="이미지 클릭", width=12, command=click_registered_image, state="disabled"
    )
    image_click_button.grid(row=2, column=1, pady=(8, 0), sticky="e")
    image_frame.columnconfigure(0, weight=1)
    image_frame.columnconfigure(1, weight=1)

    status_label = tk.Label(root, textvariable=status_var, fg="#006400")
    status_label.pack(pady=(0, 10))

    def on_hotkey_press(key: keyboard.Key) -> None:
        if key == keyboard.Key.f1:
            root.after(0, controller.run_step)
        elif key == keyboard.Key.f2:
            root.after(0, controller.reset_and_run_first)

    def start_hotkey_listener() -> None:
        nonlocal hotkey_listener
        if hotkey_listener is not None:
            return
        hotkey_listener = keyboard.Listener(on_press=on_hotkey_press)
        hotkey_listener.start()

    def on_close() -> None:
        if hotkey_listener is not None:
            hotkey_listener.stop()
        root.destroy()

    start_hotkey_listener()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
