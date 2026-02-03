"""Record window (월재기록) implementation."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Callable

from makr.core.state import UI2RecordItem


def format_timestamp(ts: float) -> str:
    """Format a timestamp as HH:MM:SS.mmm."""
    ts_int = int(ts)
    millis = int((ts - ts_int) * 1000)
    return time.strftime("%H:%M:%S", time.localtime(ts)) + f".{millis:03d}"


class RecordWindow:
    """Manages the record window (월재기록) for UI2 set history."""

    def __init__(
        self,
        root: tk.Tk,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self._on_close = on_close
        self.window: tk.Toplevel | None = None
        self.treeview: ttk.Treeview | None = None

        self.items: list[UI2RecordItem] = []

    def show(self) -> None:
        """Show the record window."""
        if self.window is not None and tk.Toplevel.winfo_exists(self.window):
            self.window.lift()
            self.window.focus_force()
            self._refresh_treeview()
            return

        self.window = tk.Toplevel(self.root)
        self.window.title("월재기록")
        self.window.geometry("360x320")
        self.window.resizable(True, True)

        info_label = ttk.Label(
            self.window,
            text="세트 종료 시점마다 시작시간과 결과를 기록합니다.",
            wraplength=320,
            justify="left",
        )
        info_label.pack(fill="x", padx=8, pady=(8, 4))

        tree = ttk.Treeview(
            self.window,
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

        scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 8))

        self.treeview = tree
        self._refresh_treeview()
        self.window.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        """Close the window and clean up."""
        if self.treeview is not None:
            for item in self.treeview.get_children():
                self.treeview.delete(item)
        self.treeview = None
        window = self.window
        self.window = None
        if window is not None:
            window.destroy()
        if self._on_close:
            self._on_close()

    def add_item(self, set_no: int, started_at: float, result: str) -> None:
        """Add a record item."""
        timestamp = format_timestamp(started_at)
        item = UI2RecordItem(set_no=set_no, started_at=timestamp, result=result)
        self.items.append(item)
        if self.treeview is not None:
            self.treeview.insert(
                "",
                "end",
                text=f"{set_no}세트",
                values=(timestamp, result),
            )

    def _refresh_treeview(self) -> None:
        """Refresh the treeview contents."""
        if self.treeview is None:
            return
        for item in self.treeview.get_children():
            self.treeview.delete(item)
        for record_item in self.items:
            self.treeview.insert(
                "",
                "end",
                text=f"{record_item.set_no}세트",
                values=(record_item.started_at, record_item.result),
            )
