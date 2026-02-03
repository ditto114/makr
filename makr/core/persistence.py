"""Path utilities and state persistence functions."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tkinter import messagebox


def _get_user_state_path() -> Path:
    """Return the path to the user's app state file."""
    if sys.platform.startswith("win"):
        base_dir = Path(
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or Path.home() / "AppData" / "Local"
        )
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    else:
        base_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base_dir / "makr" / "app_state.json"


def _get_package_resource_path(relative_path: str) -> Path:
    """Return path to a package resource file."""
    if hasattr(sys, "_MEIPASS"):
        base_dir = Path(getattr(sys, "_MEIPASS")) / "makr"
    else:
        base_dir = Path(__file__).resolve().parent.parent
    return base_dir / relative_path


def _get_new_channel_sound_path() -> Path:
    """Return path to the new channel notification sound."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "new.wav"
    return _get_package_resource_path("new.wav")


APP_STATE_PATH = _get_user_state_path()
NEW_CHANNEL_SOUND_PATH = _get_new_channel_sound_path()


def load_app_state() -> dict:
    """Load application state from the JSON file."""
    if not APP_STATE_PATH.exists():
        return {}
    try:
        return json.loads(APP_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_app_state(state: dict) -> None:
    """Save application state to the JSON file."""
    try:
        APP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        APP_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        messagebox.showwarning("설정 저장", "입력값을 저장하는 중 오류가 발생했습니다.")
