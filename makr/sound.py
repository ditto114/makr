"""크로스플랫폼 오디오 재생 모듈.

audioop 없이 볼륨 조절을 지원합니다.
"""

from __future__ import annotations

import importlib
import importlib.util
import struct
import subprocess
import sys
import threading
from pathlib import Path


class SoundPlayer:
    """WAV 파일 재생을 담당합니다.

    Windows에서는 winsound, macOS에서는 afplay를 사용합니다.
    볼륨 조절은 struct 모듈로 직접 PCM 샘플을 스케일링합니다.
    """

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
        """볼륨이 조절된 WAV 데이터를 로드합니다.

        audioop 대신 struct 모듈을 사용하여 PCM 샘플을 스케일링합니다.
        """
        if self._cached_wav_bytes is not None:
            return self._cached_wav_bytes

        if not self._sound_path.exists():
            return None

        try:
            import io
            import wave
        except ImportError:
            return None

        try:
            with wave.open(str(self._sound_path), "rb") as wav_file:
                params = wav_file.getparams()
                frames = wav_file.readframes(params.nframes)

            if self._volume != 1.0:
                frames = self._scale_samples(frames, params.sampwidth, self._volume)

            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output_wav:
                output_wav.setparams(params)
                output_wav.writeframes(frames)
            self._cached_wav_bytes = buffer.getvalue()
        except (OSError, wave.Error):
            return None

        return self._cached_wav_bytes

    @staticmethod
    def _scale_samples(frames: bytes, sampwidth: int, volume: float) -> bytes:
        """PCM 샘플에 볼륨 스케일을 적용합니다.

        Args:
            frames: PCM 오디오 데이터
            sampwidth: 샘플 너비 (바이트)
            volume: 볼륨 스케일 (0.0 ~ 1.0)

        Returns:
            볼륨이 조절된 PCM 데이터
        """
        if sampwidth == 1:
            # 8-bit unsigned
            fmt = "B"
            max_val = 255
            center = 128
        elif sampwidth == 2:
            # 16-bit signed little-endian
            fmt = "<h"
            max_val = 32767
            center = 0
        elif sampwidth == 4:
            # 32-bit signed little-endian
            fmt = "<i"
            max_val = 2147483647
            center = 0
        else:
            # 지원하지 않는 샘플 너비는 원본 반환
            return frames

        num_samples = len(frames) // sampwidth
        scaled = []

        for i in range(num_samples):
            offset = i * sampwidth
            sample_bytes = frames[offset : offset + sampwidth]
            (sample,) = struct.unpack(fmt, sample_bytes)

            if sampwidth == 1:
                # 8-bit: center around 128
                adjusted = sample - center
                scaled_val = int(adjusted * volume) + center
                scaled_val = max(0, min(max_val, scaled_val))
            else:
                # 16/32-bit signed
                scaled_val = int(sample * volume)
                scaled_val = max(-max_val - 1, min(max_val, scaled_val))

            scaled.append(struct.pack(fmt, scaled_val))

        return b"".join(scaled)

    def play_once(self) -> None:
        """사운드를 한 번 재생합니다."""
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
                # fallback: 볼륨 조절 없이 원본 재생
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
