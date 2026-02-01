"""공통 유틸리티 함수.

중복 함수를 통합하고 재사용 가능한 헬퍼를 제공합니다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox


def get_point(
    entries: dict[str, tuple[tk.Entry, tk.Entry]],
    key: str,
    label: str,
) -> tuple[int, int] | None:
    """좌표 입력 필드에서 정수 좌표를 추출합니다.

    Args:
        entries: 좌표 입력 필드 딕셔너리 {key: (x_entry, y_entry)}
        key: 좌표 키
        label: 오류 메시지에 표시할 라벨

    Returns:
        (x, y) 좌표 튜플. 파싱 실패 시 None.
    """
    x_entry, y_entry = entries[key]
    try:
        x_val = int(x_entry.get())
        y_val = int(y_entry.get())
    except ValueError:
        messagebox.showerror("좌표 오류", f"{label} 좌표를 정수로 입력해주세요.")
        return None
    return x_val, y_val


def delay_to_seconds(delay_ms: int) -> float:
    """밀리초를 초로 변환합니다.

    Args:
        delay_ms: 밀리초 단위 딜레이

    Returns:
        초 단위 딜레이 (음수는 0으로 처리)
    """
    return max(delay_ms, 0) / 1000


def sleep_ms(delay_ms: int) -> None:
    """밀리초 단위로 대기합니다.

    Args:
        delay_ms: 대기할 밀리초
    """
    import time

    delay_sec = delay_to_seconds(delay_ms)
    if delay_sec:
        time.sleep(delay_sec)
