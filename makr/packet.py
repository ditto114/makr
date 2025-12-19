from __future__ import annotations

"""Scapy를 활용한 패킷 캡쳐 관리."""

import threading
from typing import Callable


class PacketCaptureError(RuntimeError):
    """패킷 캡쳐 초기화 실패 시 사용되는 예외."""


class PacketCaptureManager:
    """지정된 포트의 패킷을 캡쳐한다."""

    def __init__(
        self,
        on_packet: Callable[[str], None],
        on_error: Callable[[str], None],
        port: int = 32800,
    ) -> None:
        self._on_packet = on_packet
        self._on_error = on_error
        self._sniffer = None
        self._lock = threading.Lock()
        self._port = port

    @property
    def running(self) -> bool:
        with self._lock:
            return self._is_running(self._sniffer)

    @property
    def port(self) -> int:
        return self._port

    def set_port(self, port: int) -> None:
        if port <= 0 or port > 65535:
            raise ValueError("포트 번호는 1~65535 사이의 정수여야 합니다.")
        self._port = port

    def start(self) -> bool:
        with self._lock:
            if self._is_running(self._sniffer):
                return True
        try:
            from scapy.all import AsyncSniffer, Raw
        except Exception:  # pragma: no cover - scapy 미설치 환경
            self._on_error("scapy가 설치되어 있지 않아 패킷 캡쳐를 시작할 수 없습니다.")
            return False

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

        try:
            sniffer = AsyncSniffer(
                filter=f"port {self._port}",
                prn=handle_packet,
                store=False,
            )
            sniffer.start()
        except Exception as exc:  # pragma: no cover - scapy 내부 오류
            self._on_error(f"패킷 캡쳐를 시작하지 못했습니다: {exc}")
            return False

        with self._lock:
            self._sniffer = sniffer
            is_running = self._is_running(self._sniffer)
        if not is_running:
            with self._lock:
                self._sniffer = None
            self._on_error("패킷 캡쳐를 시작하지 못했습니다: 스니퍼가 활성화되지 않았습니다.")
            return False

        return True

    def stop(self) -> None:
        with self._lock:
            sniffer = self._sniffer
            self._sniffer = None

        if sniffer is None:
            return

        try:
            sniffer.stop(join=False)  # type: ignore[arg-type]
        except TypeError:
            try:
                sniffer.stop()  # type: ignore[call-arg]
            except Exception:
                self._on_error("패킷 캡쳐 중지를 완료하지 못했습니다.")
                return
        except Exception:
            self._on_error("패킷 캡쳐 중지를 완료하지 못했습니다.")
            return

        self._join_sniffer_nonblocking(sniffer)

    def _is_running(self, sniffer) -> bool:  # type: ignore[no-untyped-def]
        return bool(sniffer and getattr(sniffer, "running", False))

    def _join_sniffer_nonblocking(self, sniffer) -> None:  # type: ignore[no-untyped-def]
        def _wait_for_stop() -> None:
            try:
                thread = getattr(sniffer, "thread", None)
                if thread and thread.is_alive():
                    thread.join(timeout=1.5)
            except Exception:
                # 조인 과정의 예외는 UI를 멈추지 않도록 무시
                return

        threading.Thread(target=_wait_for_stop, daemon=True).start()
