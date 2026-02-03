"""Delay input row widgets."""

from __future__ import annotations

import tkinter as tk


class StepDelayRow(tk.Frame):
    """A row widget for inputting multiple step delays."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        steps: list[tuple[tk.StringVar, str]],
    ) -> None:
        super().__init__(parent)
        self.pack(fill="x", pady=3)

        tk.Label(self, text=title, width=10, anchor="w").pack(side="left")
        for idx, (var, label_text) in enumerate(steps):
            tk.Entry(self, textvariable=var, width=6).pack(side="left", padx=(0, 4))
            tk.Label(self, text=label_text).pack(side="left", padx=(0, 4))
            if idx < len(steps) - 1:
                tk.Label(self, text="-").pack(side="left", padx=(0, 4))


class SingleDelayRow(tk.Frame):
    """A row widget for inputting a single delay value."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        var: tk.StringVar,
        suffix: str = "ms",
    ) -> None:
        super().__init__(parent)
        self.pack(fill="x", pady=3)

        tk.Label(self, text=title, width=10, anchor="w").pack(side="left")
        tk.Entry(self, textvariable=var, width=8).pack(side="left", padx=(0, 6))
        if suffix:
            tk.Label(self, text=suffix).pack(side="left")
