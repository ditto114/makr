"""Test window (채널목록) implementation."""

from __future__ import annotations

import re
import time
import tkinter as tk
from tkinter import ttk
from typing import Callable

from makr.core.state import TestRecord


def format_timestamp(ts: float) -> str:
    """Format a timestamp as HH:MM:SS.mmm."""
    ts_int = int(ts)
    millis = int((ts - ts_int) * 1000)
    return time.strftime("%H:%M:%S", time.localtime(ts)) + f".{millis:03d}"


class TestWindow:
    """Manages the test window (채널목록) for channel pattern recording."""

    PATTERN_REGEX = re.compile(r"[A-Z][가-힣]\d{2,3}")

    def __init__(
        self,
        root: tk.Tk,
        status_var: tk.StringVar,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.status_var = status_var
        self._on_close = on_close
        self.window: tk.Toplevel | None = None
        self.treeview: ttk.Treeview | None = None
        self.detail_text: tk.Text | None = None
        self.pattern_table: ttk.Treeview | None = None

        self.records: list[TestRecord] = []
        self.channel_names: list[str] = []
        self.channel_name_set: set[str] = set()

    def show(self) -> None:
        """Show the test window."""
        if self.window is not None and tk.Toplevel.winfo_exists(self.window):
            self.window.lift()
            self.window.focus_force()
            self._refresh_treeview()
            return

        self.window = tk.Toplevel(self.root)
        self.window.title("채널목록")
        self.window.geometry("520x500")
        self.window.resizable(True, True)

        info_label = ttk.Label(
            self.window,
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
            self.window,
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

        scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 8))

        detail_frame = ttk.LabelFrame(self.window, text="선택 기록 상세")
        detail_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical")
        detail_scroll.pack(side="right", fill="y")
        detail_text = tk.Text(detail_frame, height=6, wrap="none", state="disabled")
        detail_text.pack(fill="both", expand=True)
        detail_text.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.configure(command=detail_text.yview)

        pattern_frame = ttk.LabelFrame(self.window, text="추출된 패턴 표")
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
        pattern_scroll = ttk.Scrollbar(
            pattern_frame, orient="vertical", command=pattern_table.yview
        )
        pattern_table.configure(yscrollcommand=pattern_scroll.set)
        pattern_scroll.pack(side="right", fill="y")

        button_bar = ttk.Frame(self.window)
        button_bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(button_bar, text="기록 초기화", command=self._clear_records).pack(
            side="right"
        )

        self.treeview = tree
        self.detail_text = detail_text
        self.pattern_table = pattern_table
        self._refresh_treeview()

        tree.bind("<<TreeviewSelect>>", self._on_select_record)
        self.window.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        """Close the window and clean up."""
        if self.treeview is not None:
            for item in self.treeview.get_children():
                self.treeview.delete(item)
        self.treeview = None
        if self.detail_text is not None:
            self.detail_text.destroy()
        self.detail_text = None
        if self.pattern_table is not None:
            for item in self.pattern_table.get_children():
                self.pattern_table.delete(item)
            self.pattern_table.destroy()
        self.pattern_table = None
        window = self.window
        self.window = None
        if window is not None:
            window.destroy()
        if self._on_close:
            self._on_close()

    def add_record(self, content: str) -> tuple[list[str], list[str]]:
        """Add a test record and return (all_matches, new_matches)."""
        matches = self.PATTERN_REGEX.findall(content)
        new_names = [name for name in matches if name not in self.channel_name_set]
        if not matches:
            return [], []

        if new_names:
            for name in new_names:
                self.channel_name_set.add(name)
                self.channel_names.append(name)

            timestamp = format_timestamp(time.time())
            table_text, table_rows = self._build_pattern_table(self.channel_names)
            display_content = (
                f"{content}\n\n[추출된 패턴]\n{table_text}" if table_text else content
            )
            record = TestRecord(
                timestamp=timestamp,
                content=content,
                table_text=table_text,
                display_content=display_content,
                table_rows=table_rows,
            )
            self.records.append(record)

            if self.treeview is not None:
                index = len(self.records)
                item_id = self.treeview.insert(
                    "", "end", values=(index, timestamp, display_content)
                )
                self.treeview.selection_set(item_id)
                self._update_detail(index)
                self._update_pattern_table()

        return matches, new_names

    def _build_pattern_table(
        self, names: list[str]
    ) -> tuple[str | None, list[list[str]]]:
        """Build the pattern table from names."""
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
                " | ".join(
                    cell.ljust(col_width) if cell else "".ljust(col_width)
                    for cell in padded
                )
            )

        return "\n".join(formatted_rows), rows_for_view

    def _update_pattern_table(self) -> None:
        """Update the pattern table display."""
        if self.pattern_table is None:
            return

        for item in self.pattern_table.get_children():
            self.pattern_table.delete(item)

        _, rows = self._build_pattern_table(self.channel_names)

        if not rows:
            self.pattern_table.insert("", "end", values=("(없음)", "", "", "", "", ""))
            return

        for row in rows:
            padded = row + [""] * (6 - len(row))
            self.pattern_table.insert("", "end", values=padded)

    def _update_detail(self, selected_index: int | None = None) -> None:
        """Update the detail text for the selected record."""
        if self.detail_text is None:
            return

        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")

        if (
            selected_index is None
            or selected_index < 1
            or selected_index > len(self.records)
        ):
            self.detail_text.insert("1.0", "기록을 선택하세요.")
            self._update_pattern_table()
        else:
            record = self.records[selected_index - 1]
            patterns = record.table_text or "(없음)"
            detail = f"{record.content}\n\n[추출된 패턴]\n{patterns}"
            self.detail_text.insert("1.0", detail)

        self._update_pattern_table()
        self.detail_text.configure(state="disabled")

    def _refresh_treeview(self) -> None:
        """Refresh the treeview contents."""
        if self.treeview is None:
            return
        for item in self.treeview.get_children():
            self.treeview.delete(item)
        for idx, record in enumerate(self.records, start=1):
            self.treeview.insert(
                "", "end", values=(idx, record.timestamp, record.display_content)
            )
        self._update_detail(1 if self.records else None)

    def _clear_records(self) -> None:
        """Clear all records."""
        self.channel_names.clear()
        self.channel_name_set.clear()
        self.records.clear()
        self._refresh_treeview()
        self._update_pattern_table()
        self.status_var.set("테스트 기록이 초기화되었습니다.")

    def _on_select_record(self, event: tk.Event) -> None:
        """Handle record selection."""
        if self.treeview is None:
            return
        selection = self.treeview.selection()
        if not selection:
            self._update_detail(None)
            return
        item_id = selection[0]
        values = self.treeview.item(item_id, "values")
        try:
            idx = int(values[0])
        except (ValueError, IndexError):
            self._update_detail(None)
            return
        self._update_detail(idx)
