"""Sound playback utilities."""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk


class SoundPlayer:
    """Plays sound files with optional volume scaling."""

    def __init__(self, sound_path: Path, *, volume: float = 1.0) -> None:
        self._sound_path = sound_path
        self._volume = max(0.0, min(volume, 1.0))
        self._winsound = (
            importlib.import_module("winsound")
            if importlib.util.find_spec("winsound")
            else None
        )
        self._cached_wav_bytes: bytes | None = None

    def _load_scaled_wav(self) -> bytes | None:
        """Load and scale the WAV file volume."""
        if self._cached_wav_bytes is not None:
            return self._cached_wav_bytes
        if not self._sound_path.exists():
            return None
        try:
            import audioop
            import io
            import wave
        except ImportError:
            return None
        try:
            with wave.open(str(self._sound_path), "rb") as wav_file:
                params = wav_file.getparams()
                frames = wav_file.readframes(params.nframes)
            if self._volume != 1.0:
                frames = audioop.mul(frames, params.sampwidth, self._volume)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output_wav:
                output_wav.setparams(params)
                output_wav.writeframes(frames)
            self._cached_wav_bytes = buffer.getvalue()
        except (OSError, wave.Error):
            return None
        return self._cached_wav_bytes

    def play_once(self) -> None:
        """Play the sound file once."""
        if not self._sound_path.exists():
            return
        suffix = self._sound_path.suffix.lower()
        if suffix != ".wav":
            return

        def _run() -> None:
            if self._winsound is not None:
                wav_bytes = self._load_scaled_wav()
                if wav_bytes is not None:
                    self._winsound.PlaySound(
                        wav_bytes,
                        self._winsound.SND_MEMORY | self._winsound.SND_ASYNC,
                    )
                    return
                self._winsound.PlaySound(
                    str(self._sound_path),
                    self._winsound.SND_FILENAME | self._winsound.SND_ASYNC,
                )
                return
            if sys.platform == "darwin":
                subprocess.run(
                    ["afplay", "-v", f"{self._volume:.2f}", str(self._sound_path)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        threading.Thread(target=_run, daemon=True).start()


class BeepNotifier:
    """Plays system beeps for a specified duration."""

    def __init__(self, root_widget: "tk.Tk") -> None:
        self._root = root_widget
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._winsound = (
            importlib.import_module("winsound")
            if importlib.util.find_spec("winsound")
            else None
        )

    def start(self, duration_sec: float = 3.0) -> None:
        """Start beeping for the specified duration."""
        self.stop()
        self._stop_event.clear()

        def _run() -> None:
            end_time = time.time() + max(duration_sec, 0)
            while time.time() < end_time and not self._stop_event.is_set():
                if self._winsound is not None:
                    self._winsound.Beep(1200, 200)
                else:
                    self._root.after(0, self._root.bell)
                if self._stop_event.wait(0.1):
                    break

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the beeping."""
        if self._thread is None:
            return
        self._stop_event.set()
