"""Backward-compatible entry point.

This module re-exports from the new modular structure for backward compatibility.
"""

from __future__ import annotations

# Re-export everything from the new locations for backward compatibility
from makr.core.config import DelayConfig, UiTwoDelayConfig
from makr.core.persistence import (
    APP_STATE_PATH,
    NEW_CHANNEL_SOUND_PATH,
    load_app_state,
    save_app_state,
)
from makr.core.tasks import RepeatingTask, RepeatingClickTask, RepeatingActionTask
from makr.core.sound import SoundPlayer, BeepNotifier
from makr.core.channel import ChannelSegmentRecorder
from makr.controllers.macro_controller import MacroController
from makr.ui.app import MakrApplication, build_gui

import pyautogui

# Restore pyautogui setting
pyautogui.PAUSE = 0

__all__ = [
    "DelayConfig",
    "UiTwoDelayConfig",
    "APP_STATE_PATH",
    "NEW_CHANNEL_SOUND_PATH",
    "load_app_state",
    "save_app_state",
    "RepeatingTask",
    "RepeatingClickTask",
    "RepeatingActionTask",
    "SoundPlayer",
    "BeepNotifier",
    "ChannelSegmentRecorder",
    "MacroController",
    "MakrApplication",
    "build_gui",
]

if __name__ == "__main__":
    build_gui()
