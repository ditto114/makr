"""UI2 (월재) panel widget."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, TYPE_CHECKING

from makr.ui.widgets.coordinate_row import CoordinateRow
from makr.ui.widgets.delay_row import StepDelayRow, SingleDelayRow

if TYPE_CHECKING:
    from pynput import mouse


class UI2Panel(tk.Frame):
    """Panel for UI2 (월재) controls."""

    def __init__(
        self,
        parent: tk.Widget,
        saved_state: dict,
        status_var: tk.StringVar,
        root: tk.Tk,
        automation_var: tk.BooleanVar,
        test_new_channel_var: tk.BooleanVar,
        delay_vars: dict[str, tk.StringVar],
        get_capture_listener: Callable[[], "mouse.Listener | None"],
        clear_capture_listener: Callable[[], None],
        bg: str = "#ffffff",
    ) -> None:
        super().__init__(parent, bg=bg)
        self.saved_state = saved_state
        self.status_var = status_var
        self.root = root
        self.automation_var = automation_var
        self.test_new_channel_var = test_new_channel_var
        self.delay_vars = delay_vars
        self._get_capture_listener = get_capture_listener
        self._clear_capture_listener = clear_capture_listener

        self.entries: dict[str, tuple[tk.Entry, tk.Entry]] = {}
        self.automation_checkbox: tk.Checkbutton | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the UI components."""
        # Top bar
        ui2_top = tk.Frame(self)
        ui2_top.pack(fill="x", pady=(0, 4))

        self.automation_checkbox = tk.Checkbutton(
            ui2_top, text="자동화", variable=self.automation_var
        )
        self.automation_checkbox.pack(side="right", padx=(0, 12))

        test_checkbox = tk.Checkbutton(
            ui2_top, text="테스트", variable=self.test_new_channel_var
        )
        test_checkbox.pack(side="right", padx=(0, 6))

        # Coordinate rows
        saved_coords = self.saved_state.get("coordinates", {})

        self._add_coordinate_row("···", "pos11", saved_coords)
        self._add_coordinate_row("🔃", "pos12", saved_coords)
        self._add_coordinate_row("로그인", "pos13", saved_coords)
        self._add_coordinate_row("캐릭터", "pos14", saved_coords)

        # Delay settings
        delay_frame = tk.LabelFrame(self, text="딜레이 설정")
        delay_frame.pack(fill="x", padx=10, pady=(0, 10))

        StepDelayRow(
            delay_frame,
            "(F4)",
            [
                (self.delay_vars["f4_between_pos11_pos12"], "···-🔃"),
                (self.delay_vars["f4_before_enter"], "Enter 전"),
            ],
        )
        SingleDelayRow(
            delay_frame,
            "(F5)",
            self.delay_vars["f5_interval"],
            "ms (클릭 간격)",
        )
        SingleDelayRow(
            delay_frame,
            "(F6)",
            self.delay_vars["f6_interval"],
            "ms (클릭 간격)",
        )

    def _add_coordinate_row(
        self, label_text: str, key: str, saved_coords: dict
    ) -> None:
        """Add a coordinate input row."""
        coords = saved_coords.get(key, {})
        row = CoordinateRow(
            self,
            label_text,
            initial_x=str(coords.get("x", "0")),
            initial_y=str(coords.get("y", "0")),
            status_var=self.status_var,
            root=self.root,
            on_capture_start=self._get_capture_listener,
            on_capture_end=self._clear_capture_listener,
        )
        self.entries[key] = row.get_entries()
