"""Configuration dataclasses and application constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class DelayConfig:
    """UI1 (채변) delay configuration callbacks."""

    f2_before_esc: Callable[[], int]
    f2_before_pos1: Callable[[], int]
    f2_before_pos2: Callable[[], int]
    f1_before_pos3: Callable[[], int]
    f1_before_enter: Callable[[], int]
    f1_repeat_count: Callable[[], int]
    f1_newline_before_pos4: Callable[[], int]
    f1_newline_before_pos3: Callable[[], int]
    f1_newline_before_enter: Callable[[], int]


@dataclass
class UiTwoDelayConfig:
    """UI2 (월재) delay configuration callbacks."""

    f4_between_pos11_pos12: Callable[[], int]
    f4_before_enter: Callable[[], int]
    f5_interval: Callable[[], int]
    f6_interval: Callable[[], int]


# Application-wide constants
DEFAULT_DELAY_F2_BEFORE_ESC_MS = 0
DEFAULT_DELAY_F2_BEFORE_POS1_MS = 55
DEFAULT_DELAY_F2_BEFORE_POS2_MS = 55
DEFAULT_DELAY_F1_BEFORE_POS3_MS = 15
DEFAULT_DELAY_F1_BEFORE_ENTER_MS = 15
DEFAULT_F1_REPEAT_COUNT = 8
DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS4_MS = 170
DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS3_MS = 30
DEFAULT_DELAY_F1_NEWLINE_BEFORE_ENTER_MS = 15
DEFAULT_DELAY_F4_BETWEEN_POS11_POS12_MS = 25
DEFAULT_DELAY_F4_BEFORE_ENTER_MS = 55
DEFAULT_DELAY_F5_INTERVAL_MS = 25
DEFAULT_DELAY_F6_INTERVAL_MS = 25
DEFAULT_CHANNEL_WATCH_INTERVAL_MS = 20
DEFAULT_CHANNEL_TIMEOUT_MS = 700
