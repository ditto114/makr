"""UI1 (채변) panel widget."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, TYPE_CHECKING

from makr.ui.widgets.coordinate_row import CoordinateRow, Pos3Row
from makr.ui.widgets.delay_row import StepDelayRow, SingleDelayRow

if TYPE_CHECKING:
    from pynput import mouse


class UI1Panel(tk.Frame):
    """Panel for UI1 (채변) controls."""

    def __init__(
        self,
        parent: tk.Widget,
        saved_state: dict,
        status_var: tk.StringVar,
        root: tk.Tk,
        pos3_mode_var: tk.IntVar,
        pos3_mode_coordinates: dict[int, dict[str, str]],
        newline_var: tk.BooleanVar,
        esc_click_var: tk.BooleanVar,
        delay_vars: dict[str, tk.StringVar],
        get_capture_listener: Callable[[], "mouse.Listener | None"],
        clear_capture_listener: Callable[[], None],
        bg: str = "#ffffff",
    ) -> None:
        super().__init__(parent, bg=bg)
        self.saved_state = saved_state
        self.status_var = status_var
        self.root = root
        self.pos3_mode_var = pos3_mode_var
        self.pos3_mode_coordinates = pos3_mode_coordinates
        self.newline_var = newline_var
        self.esc_click_var = esc_click_var
        self.delay_vars = delay_vars
        self._get_capture_listener = get_capture_listener
        self._clear_capture_listener = clear_capture_listener

        self.entries: dict[str, tuple[tk.Entry, tk.Entry]] = {}
        self._pos3_row: Pos3Row | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the UI components."""
        # Top bar
        ui1_top = tk.Frame(self)
        ui1_top.pack(fill="x", pady=(0, 4))

        self.pos3_mode_label_var = tk.StringVar()
        pos3_mode_label = tk.Label(ui1_top, textvariable=self.pos3_mode_label_var)
        pos3_mode_label.pack(side="left", padx=(12, 0))

        self.pos3_mode_button = tk.Button(ui1_top, text="다음", width=12)
        self.pos3_mode_button.pack(side="left", padx=(6, 0))

        newline_checkbox = tk.Checkbutton(ui1_top, text="줄바꿈", variable=self.newline_var)
        newline_checkbox.pack(side="right", padx=(0, 12))

        esc_click_checkbox = tk.Checkbutton(
            ui1_top, text="Esc를 클릭으로 대체", variable=self.esc_click_var
        )
        esc_click_checkbox.pack(side="right", padx=(0, 6))
        self.newline_checkbox = newline_checkbox

        # Coordinate rows
        saved_coords = self.saved_state.get("coordinates", {})

        self._add_coordinate_row("메뉴", "pos1", saved_coords)
        self._add_coordinate_row("채널", "pos2", saved_coords)
        self._add_pos3_row("열")
        self._add_coordinate_row("∇", "pos4", saved_coords)
        self._add_coordinate_row("Esc", "esc_click", saved_coords)

        # Delay settings
        delay_frame = tk.LabelFrame(self, text="딜레이 설정")
        delay_frame.pack(fill="x", padx=10, pady=(0, 10))

        StepDelayRow(
            delay_frame,
            "(F2)",
            [
                (self.delay_vars["f2_before_esc"], "Esc"),
                (self.delay_vars["f2_before_pos1"], "메뉴"),
                (self.delay_vars["f2_before_pos2"], "채널"),
            ],
        )
        SingleDelayRow(
            delay_frame,
            "채널감시주기",
            self.delay_vars["channel_watch_interval"],
            "ms (기본 20)",
        )
        SingleDelayRow(
            delay_frame,
            "채널타임아웃",
            self.delay_vars["channel_timeout"],
            "ms (기본 700)",
        )
        StepDelayRow(
            delay_frame,
            "(F1-1)",
            [
                (self.delay_vars["f1_before_pos3"], "열"),
                (self.delay_vars["f1_before_enter"], "Enter"),
            ],
        )
        SingleDelayRow(
            delay_frame,
            "F1 반복",
            self.delay_vars["f1_repeat_count"],
            "회",
        )
        StepDelayRow(
            delay_frame,
            "(F1-2)",
            [
                (self.delay_vars["f1_newline_before_pos4"], "∇"),
                (self.delay_vars["f1_newline_before_pos3"], "열"),
                (self.delay_vars["f1_newline_before_enter"], "Enter"),
            ],
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

    def _add_pos3_row(self, label_text: str) -> None:
        """Add the pos3 coordinate row with mode support."""
        self._pos3_row = Pos3Row(
            self,
            label_text,
            self.pos3_mode_var,
            self.pos3_mode_coordinates,
            status_var=self.status_var,
            root=self.root,
            get_mode_name=lambda m: f"{m}열",
            on_capture_start=self._get_capture_listener,
            on_capture_end=self._clear_capture_listener,
        )
        self.entries["pos3"] = self._pos3_row.get_entries()

    def store_current_pos3_mode_values(self) -> None:
        """Store current pos3 values to mode coordinates."""
        if self._pos3_row:
            self._pos3_row.store_current_values()

    def load_pos3_mode_values(self) -> None:
        """Load pos3 values for current mode."""
        if self._pos3_row:
            self._pos3_row.load_mode_values()

    def update_pos3_mode_label(self) -> None:
        """Update the pos3 mode label."""
        self.pos3_mode_label_var.set(f"선택할 열: {self.pos3_mode_var.get()}열")
