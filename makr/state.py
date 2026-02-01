"""UI2 자동화 상태 관리 클래스.

nonlocal 변수들을 캡슐화하여 상태 전이 로직을 명확하게 합니다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class UI2AutomationState:
    """UI2 자동화 상태를 캡슐화합니다.

    이전에 nonlocal로 관리되던 6개의 상태 변수를 하나의 클래스로 통합합니다.
    """

    active: bool = False
    waiting_for_new_channel: bool = False
    waiting_for_normal_channel: bool = False
    waiting_for_selection: bool = False
    set_index: int = 0
    current_set_started_at: float | None = None

    def reset(self) -> None:
        """자동화 상태를 초기화합니다."""
        self.active = False
        self.waiting_for_new_channel = False
        self.waiting_for_normal_channel = False
        self.waiting_for_selection = False

    def start_new_set(self) -> float:
        """새 세트를 시작하고 시작 시간을 반환합니다."""
        self.set_index += 1
        self.current_set_started_at = time.time()
        return self.current_set_started_at

    def clear_set_state(self) -> None:
        """현재 세트 상태만 초기화합니다."""
        self.current_set_started_at = None

    def finish_set(self) -> float | None:
        """세트를 종료하고 시작 시간을 반환합니다.

        Returns:
            세트 시작 시간. 세트가 시작되지 않았으면 None.
        """
        started_at = self.current_set_started_at
        self.current_set_started_at = None
        return started_at

    def start_waiting_for_new_channel(self) -> None:
        """새 채널 대기 상태로 전환합니다."""
        self.active = True
        self.waiting_for_new_channel = True
        self.waiting_for_normal_channel = False
        self.waiting_for_selection = False

    def transition_to_normal_channel_wait(self) -> None:
        """일반 채널 대기 상태로 전환합니다."""
        self.waiting_for_new_channel = False
        self.waiting_for_normal_channel = True
        self.waiting_for_selection = False

    def transition_to_selection_wait(self) -> None:
        """선택창 대기 상태로 전환합니다."""
        self.waiting_for_normal_channel = False
        self.waiting_for_selection = True

    def clear_selection_wait(self) -> None:
        """선택창 대기 상태를 해제합니다."""
        self.waiting_for_selection = False

    def clear_all_waits(self) -> None:
        """모든 대기 상태를 해제합니다."""
        self.waiting_for_new_channel = False
        self.waiting_for_normal_channel = False
        self.waiting_for_selection = False


@dataclass
class DevLogicState:
    """DevLogic 패킷 감지 상태를 관리합니다."""

    last_detected_at: float | None = None
    last_packet: str = ""
    last_is_new_channel: bool = False
    last_alert_message: str = ""
    last_alert_packet: str = ""

    def update(
        self,
        *,
        packet: str,
        is_new_channel: bool,
        alert_message: str,
        alert_packet: str,
    ) -> None:
        """감지 상태를 업데이트합니다."""
        self.last_detected_at = time.time()
        self.last_packet = packet
        self.last_is_new_channel = is_new_channel
        self.last_alert_message = alert_message
        self.last_alert_packet = alert_packet

    def update_admin_level(self) -> None:
        """AdminLevel 감지 시 상태를 업데이트합니다."""
        self.last_detected_at = time.time()
        self.last_alert_message = "선택창 감지"
        self.last_alert_packet = ""

    def reset(self) -> None:
        """상태를 초기화합니다."""
        self.last_detected_at = None
        self.last_packet = ""
        self.last_is_new_channel = False
        self.last_alert_message = ""
        self.last_alert_packet = ""
