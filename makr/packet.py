from __future__ import annotations

"""Scapy를 활용한 패킷 캡쳐 및 알림 관리."""

import threading
from typing import Callable, Iterable, List, Set


class PacketCaptureError(RuntimeError):
    """패킷 캡쳐 초기화 실패 시 사용되는 예외."""


class PacketCaptureManager:
    """포트 32800 패킷을 캡쳐하고 알림 문자열을 감지한다."""

    def __init__(
        self,
        on_packet: Callable[[str], None],
        on_alert: Callable[[str, str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._on_packet = on_packet
        self._on_alert = on_alert
        self._on_error = on_error
        self._sniffer = None
        self._alerts: Set[str] = set()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._sniffer and getattr(self._sniffer, "running", False))

    def set_alerts(self, alerts: Iterable[str]) -> None:
        with self._lock:
            self._alerts = {text for text in alerts if text}

    def start(self) -> None:
        if self.running:
            return
        try:
            from scapy.all import AsyncSniffer, Raw
        except Exception:  # pragma: no cover - scapy 미설치 환경
            self._on_error("scapy가 설치되어 있지 않아 패킷 캡쳐를 시작할 수 없습니다.")
            return

        def handle_packet(packet) -> None:  # type: ignore[no-untyped-def]
            if not packet.haslayer(Raw):
                return
            raw_payload = bytes(packet[Raw].load)
            if not raw_payload:
                return
            try:
                decoded = raw_payload.decode("utf-8")
            except UnicodeDecodeError:
                decoded = raw_payload.decode("utf-8", errors="ignore")
            self._on_packet(decoded)
            self._check_alerts(decoded)

        try:
            self._sniffer = AsyncSniffer(
                filter="port 32800",
                prn=handle_packet,
                store=False,
            )
            self._sniffer.start()
        except Exception as exc:  # pragma: no cover - scapy 내부 오류
            self._sniffer = None
            self._on_error(f"패킷 캡쳐를 시작하지 못했습니다: {exc}")

    def stop(self) -> None:
        if not self.running:
            return
        try:
            self._sniffer.stop()  # type: ignore[union-attr]
        except Exception:
            self._on_error("패킷 캡쳐 중지를 완료하지 못했습니다.")
        finally:
            self._sniffer = None

    def _check_alerts(self, payload: str) -> None:
        with self._lock:
            alerts: List[str] = [text for text in self._alerts if text in payload]
        for text in alerts:
            self._on_alert(text, payload)
