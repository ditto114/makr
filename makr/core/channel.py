"""Channel detection and recording utilities."""

from __future__ import annotations

import re
import time
from typing import Callable


def format_devlogic_packet(packet_text: str) -> tuple[str, bool, bool]:
    """Format a DevLogic packet and determine channel type.

    Returns:
        Tuple of (display_text, is_new_channel, is_normal_channel)
    """
    start = packet_text.find("DevLogic")
    if start == -1:
        return "", False, False
    segment_start = start + len("DevLogic")
    segment = packet_text[segment_start : segment_start + 25]
    sanitized = re.sub(r"[^0-9A-Za-z가-힣]", "-", segment)
    display = sanitized[:25]
    if not display:
        return "", False, False
    has_alpha = bool(re.search(r"[A-Za-z]", display))
    has_digit = bool(re.search(r"[0-9]", display))
    has_korean = bool(re.search(r"[가-힣]", display))
    is_normal_channel = has_alpha and has_digit and has_korean
    is_new_channel = not is_normal_channel
    return display, is_new_channel, is_normal_channel


class ChannelSegmentRecorder:
    """Records and parses channel name segments from packet data."""

    anchor_keyword = "ChannelName"

    def __init__(
        self,
        on_capture: Callable[[str], None],
        on_channel_activity: Callable[[float], None] | None = None,
    ) -> None:
        self._on_capture = on_capture
        self._on_channel_activity = on_channel_activity
        self._buffer = ""
        self._pattern = re.compile(r"[A-Z]-[가-힣]\d{2,3}-")

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text by replacing non-alphanumeric characters with hyphens."""
        return re.sub(r"[^A-Za-z0-9가-힣]", "-", text)

    def feed(self, text: str) -> None:
        """Feed packet data to the recorder."""
        normalized = self._normalize(text)
        if not normalized:
            return
        if self.anchor_keyword in normalized and self._on_channel_activity is not None:
            self._on_channel_activity(time.time())
        self._buffer += normalized
        self._process_buffer()

    def _process_buffer(self) -> None:
        """Process the internal buffer looking for channel patterns."""
        while True:
            anchor_idx = self._buffer.find(self.anchor_keyword)
            if anchor_idx == -1:
                # Keep only the tail to avoid missing partial keywords
                self._buffer = self._buffer[-len(self.anchor_keyword) :]
                return
            if self._on_channel_activity is not None:
                self._on_channel_activity(time.time())

            search_start = anchor_idx + len(self.anchor_keyword)
            match = self._pattern.search(self._buffer, pos=search_start)
            if match is None:
                # Keep from anchor onwards for next feed
                self._buffer = self._buffer[anchor_idx:]
                return

            captured = match.group(0).replace("-", "")
            self._on_capture(captured)

            # Continue processing from after the match
            self._buffer = self._buffer[match.end() :]
