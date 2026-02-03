"""State management dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DevLogicState:
    """State for DevLogic packet detection."""

    last_detected_at: float | None = None
    last_packet: str = ""
    last_is_new_channel: bool = False
    last_alert_message: str = ""
    last_alert_packet: str = ""

    def reset(self) -> None:
        """Reset all state to defaults."""
        self.last_detected_at = None
        self.last_packet = ""
        self.last_is_new_channel = False
        self.last_alert_message = ""
        self.last_alert_packet = ""


@dataclass
class UI2AutomationState:
    """State for UI2 automation."""

    active: bool = False
    waiting_for_new_channel: bool = False
    waiting_for_normal_channel: bool = False
    waiting_for_selection: bool = False
    set_index: int = 0
    current_set_started_at: float | None = None

    def reset(self) -> None:
        """Reset automation state (not set_index)."""
        self.active = False
        self.waiting_for_new_channel = False
        self.waiting_for_normal_channel = False
        self.waiting_for_selection = False
        self.current_set_started_at = None

    def start_automation(self) -> None:
        """Start a new automation cycle."""
        self.active = True
        self.waiting_for_new_channel = True
        self.waiting_for_normal_channel = False
        self.waiting_for_selection = False

    def on_new_channel_found(self) -> None:
        """Handle new channel detection."""
        self.waiting_for_new_channel = False
        self.waiting_for_normal_channel = True
        self.waiting_for_selection = False

    def on_normal_channel_found(self) -> None:
        """Handle normal channel detection."""
        self.waiting_for_normal_channel = False
        self.waiting_for_selection = True

    def on_selection_found(self) -> None:
        """Handle selection window detection."""
        self.waiting_for_selection = False


@dataclass
class UI2RecordItem:
    """Record item for UI2 set history."""

    set_no: int
    started_at: str
    result: str


@dataclass
class TestRecord:
    """Test window record item."""

    timestamp: str
    content: str
    table_text: str | None
    display_content: str
    table_rows: list[list[str]] = field(default_factory=list)
