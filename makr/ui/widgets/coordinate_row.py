"""Coordinate input row widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from pynput import mouse


class CoordinateRow(tk.Frame):
    """A row widget for inputting x/y coordinates with a capture button."""

    def __init__(
        self,
        parent: tk.Widget,
        label_text: str,
        initial_x: str = "0",
        initial_y: str = "0",
        status_var: tk.StringVar | None = None,
        root: tk.Tk | None = None,
        on_capture_start: Callable[[], "mouse.Listener | None"] | None = None,
        on_capture_end: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.label_text = label_text
        self.status_var = status_var
        self.root = root
        self._on_capture_start = on_capture_start
        self._on_capture_end = on_capture_end
        self._capture_listener: "mouse.Listener | None" = None

        self.pack(fill="x", padx=10, pady=5)

        tk.Label(self, text=label_text, width=8, anchor="w").pack(side="left")

        self.x_entry = tk.Entry(self, width=6)
        self.x_entry.pack(side="left", padx=(0, 4))
        self.x_entry.insert(0, initial_x)

        self.y_entry = tk.Entry(self, width=6)
        self.y_entry.pack(side="left")
        self.y_entry.insert(0, initial_y)

        self.register_button = tk.Button(self, text="좌표등록", command=self._start_capture)
        self.register_button.pack(side="left", padx=(6, 0))

    def get_entries(self) -> tuple[tk.Entry, tk.Entry]:
        """Return the x and y entry widgets."""
        return self.x_entry, self.y_entry

    def get_point(self) -> tuple[int, int] | None:
        """Get the current coordinates or None if invalid."""
        try:
            x_val = int(self.x_entry.get())
            y_val = int(self.y_entry.get())
        except ValueError:
            messagebox.showerror("좌표 오류", f"{self.label_text} 좌표를 정수로 입력해주세요.")
            return None
        return x_val, y_val

    def set_point(self, x: int, y: int) -> None:
        """Set the coordinate values."""
        self.x_entry.delete(0, tk.END)
        self.x_entry.insert(0, str(x))
        self.y_entry.delete(0, tk.END)
        self.y_entry.insert(0, str(y))

    def _start_capture(self) -> None:
        """Start coordinate capture mode."""
        from pynput import mouse as pynput_mouse

        if self._on_capture_start:
            existing = self._on_capture_start()
            if existing is not None and existing.running:
                messagebox.showinfo("좌표 등록", "다른 좌표 등록이 진행 중입니다.")
                return

        if self.status_var:
            self.status_var.set(f"{self.label_text} 등록: 원하는 위치를 클릭하세요.")
        if self.root:
            self.root.withdraw()

        def on_click(x: float, y: float, button: pynput_mouse.Button, pressed: bool) -> bool:
            if pressed and button == pynput_mouse.Button.left:
                if self.root:
                    self.root.after(0, self._finalize_capture, int(x), int(y))
                return False
            return True

        self._capture_listener = pynput_mouse.Listener(on_click=on_click)
        self._capture_listener.start()

    def _finalize_capture(self, x_val: int, y_val: int) -> None:
        """Finalize the capture with the given coordinates."""
        self.set_point(x_val, y_val)
        if self.status_var:
            self.status_var.set(f"{self.label_text} 좌표가 등록되었습니다: ({x_val}, {y_val})")
        if self.root:
            self.root.deiconify()
        self._capture_listener = None
        if self._on_capture_end:
            self._on_capture_end()


class Pos3Row(tk.Frame):
    """A specialized coordinate row for pos3 with mode support."""

    def __init__(
        self,
        parent: tk.Widget,
        label_text: str,
        mode_var: tk.IntVar,
        mode_coordinates: dict[int, dict[str, str]],
        status_var: tk.StringVar | None = None,
        root: tk.Tk | None = None,
        get_mode_name: Callable[[int], str] | None = None,
        on_capture_start: Callable[[], "mouse.Listener | None"] | None = None,
        on_capture_end: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.label_text = label_text
        self.mode_var = mode_var
        self.mode_coordinates = mode_coordinates
        self.status_var = status_var
        self.root = root
        self._get_mode_name = get_mode_name or (lambda m: f"{m}열")
        self._on_capture_start = on_capture_start
        self._on_capture_end = on_capture_end
        self._capture_listener: "mouse.Listener | None" = None

        self.pack(fill="x", padx=10, pady=5)

        tk.Label(self, text=label_text, width=8, anchor="w").pack(side="left")

        self.x_entry = tk.Entry(self, width=6)
        self.x_entry.pack(side="left", padx=(0, 4))

        self.y_entry = tk.Entry(self, width=6)
        self.y_entry.pack(side="left")

        self._load_mode_values()

        self.register_button = tk.Button(self, text="좌표등록", command=self._start_capture)
        self.register_button.pack(side="left", padx=(6, 0))

    def get_entries(self) -> tuple[tk.Entry, tk.Entry]:
        """Return the x and y entry widgets."""
        return self.x_entry, self.y_entry

    def get_point(self) -> tuple[int, int] | None:
        """Get the current coordinates or None if invalid."""
        try:
            x_val = int(self.x_entry.get())
            y_val = int(self.y_entry.get())
        except ValueError:
            messagebox.showerror("좌표 오류", f"{self.label_text} 좌표를 정수로 입력해주세요.")
            return None
        return x_val, y_val

    def set_point(self, x: int, y: int) -> None:
        """Set the coordinate values."""
        self.x_entry.delete(0, tk.END)
        self.x_entry.insert(0, str(x))
        self.y_entry.delete(0, tk.END)
        self.y_entry.insert(0, str(y))

    def _load_mode_values(self) -> None:
        """Load coordinate values for the current mode."""
        mode = self.mode_var.get()
        coords = self.mode_coordinates.get(mode, {"x": "0", "y": "0"})
        self.x_entry.delete(0, tk.END)
        self.x_entry.insert(0, coords["x"])
        self.y_entry.delete(0, tk.END)
        self.y_entry.insert(0, coords["y"])

    def load_mode_values(self) -> None:
        """Public method to reload mode values."""
        self._load_mode_values()

    def store_current_values(self) -> None:
        """Store current values to mode_coordinates."""
        mode = self.mode_var.get()
        self.mode_coordinates[mode] = {
            "x": self.x_entry.get(),
            "y": self.y_entry.get(),
        }

    def _start_capture(self) -> None:
        """Start coordinate capture mode."""
        from pynput import mouse as pynput_mouse

        if self._on_capture_start:
            existing = self._on_capture_start()
            if existing is not None and existing.running:
                messagebox.showinfo("좌표 등록", "다른 좌표 등록이 진행 중입니다.")
                return

        mode = self.mode_var.get()
        if self.status_var:
            self.status_var.set(
                f"{self.label_text}({self._get_mode_name(mode)}) 등록: 원하는 위치를 클릭하세요."
            )
        if self.root:
            self.root.withdraw()

        def on_click(x: float, y: float, button: pynput_mouse.Button, pressed: bool) -> bool:
            if pressed and button == pynput_mouse.Button.left:
                if self.root:
                    self.root.after(0, self._finalize_capture, int(x), int(y))
                return False
            return True

        self._capture_listener = pynput_mouse.Listener(on_click=on_click)
        self._capture_listener.start()

    def _finalize_capture(self, x_val: int, y_val: int) -> None:
        """Finalize the capture with the given coordinates."""
        mode = self.mode_var.get()
        self.mode_coordinates[mode] = {"x": str(x_val), "y": str(y_val)}
        self.set_point(x_val, y_val)
        if self.status_var:
            self.status_var.set(
                f"{self.label_text}({self._get_mode_name(mode)}) 좌표가 등록되었습니다: ({x_val}, {y_val})"
            )
        if self.root:
            self.root.deiconify()
        self._capture_listener = None
        if self._on_capture_end:
            self._on_capture_end()
