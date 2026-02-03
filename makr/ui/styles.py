"""UI styles and color constants."""

from __future__ import annotations

import tkinter as tk

# Tab styling constants
TAB_ACTIVE_BG = "#ffffff"
TAB_INACTIVE_BG = "#e6e6e6"
TAB_BORDER = "#bdbdbd"


def style_tab_button(button: tk.Button, *, active: bool) -> None:
    """Apply tab styling to a button.

    Args:
        button: The button widget to style.
        active: Whether the tab is currently active.
    """
    if active:
        button.configure(
            bg=TAB_ACTIVE_BG,
            fg="#000000",
            relief="solid",
            bd=1,
            highlightthickness=0,
            activebackground=TAB_ACTIVE_BG,
            activeforeground="#000000",
        )
    else:
        button.configure(
            bg=TAB_INACTIVE_BG,
            fg="#555555",
            relief="ridge",
            bd=1,
            highlightthickness=0,
            activebackground="#dcdcdc",
            activeforeground="#333333",
        )
