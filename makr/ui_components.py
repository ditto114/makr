"""UI 위젯 컴포넌트 클래스.

build_gui()의 내부 함수들을 재사용 가능한 클래스로 분리합니다.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from pynput import mouse


class CoordinateRow:
    """좌표 입력 행 위젯."""

    def __init__(
        self,
        parent: tk.Widget,
        label_text: str,
        key: str,
        target_entries: dict[str, tuple[tk.Entry, tk.Entry]],
        initial_x: str = "0",
        initial_y: str = "0",
        *,
        status_var: tk.StringVar,
        root: tk.Tk,
        get_capture_listener: Callable[[], mouse.Listener | None],
        set_capture_listener: Callable[[mouse.Listener | None], None],
    ) -> None:
        """좌표 입력 행을 생성합니다.

        Args:
            parent: 부모 위젯
            label_text: 라벨 텍스트
            key: 좌표 키
            target_entries: 좌표 입력 필드를 저장할 딕셔너리
            initial_x: X 좌표 초기값
            initial_y: Y 좌표 초기값
            status_var: 상태 표시 변수
            root: 루트 윈도우
            get_capture_listener: 현재 캡처 리스너를 반환하는 함수
            set_capture_listener: 캡처 리스너를 설정하는 함수
        """
        self._label_text = label_text
        self._key = key
        self._target_entries = target_entries
        self._status_var = status_var
        self._root = root
        self._get_capture_listener = get_capture_listener
        self._set_capture_listener = set_capture_listener

        frame = tk.Frame(parent)
        frame.pack(fill="x", padx=10, pady=5)

        tk.Label(frame, text=label_text, width=8, anchor="w").pack(side="left")

        self._x_entry = tk.Entry(frame, width=6)
        self._x_entry.pack(side="left", padx=(0, 4))
        self._x_entry.insert(0, initial_x)

        self._y_entry = tk.Entry(frame, width=6)
        self._y_entry.pack(side="left")
        self._y_entry.insert(0, initial_y)

        target_entries[key] = (self._x_entry, self._y_entry)

        register_button = tk.Button(frame, text="좌표등록", command=self._start_capture)
        register_button.pack(side="left", padx=(6, 0))

    def _start_capture(self) -> None:
        """좌표 캡처를 시작합니다."""
        from tkinter import messagebox

        capture_listener = self._get_capture_listener()
        if capture_listener is not None and capture_listener.running:
            messagebox.showinfo("좌표 등록", "다른 좌표 등록이 진행 중입니다.")
            return

        self._status_var.set(f"{self._label_text} 등록: 원하는 위치를 클릭하세요.")
        self._root.withdraw()

        def on_click(x: float, y: float, button: mouse.Button, pressed: bool) -> bool:
            if pressed and button == mouse.Button.left:
                self._root.after(0, self._finalize_capture, int(x), int(y))
                return False
            return True

        listener = mouse.Listener(on_click=on_click)
        self._set_capture_listener(listener)
        listener.start()

    def _finalize_capture(self, x_val: int, y_val: int) -> None:
        """좌표 캡처를 완료합니다."""
        self._x_entry.delete(0, tk.END)
        self._x_entry.insert(0, str(x_val))
        self._y_entry.delete(0, tk.END)
        self._y_entry.insert(0, str(y_val))
        self._status_var.set(f"{self._label_text} 좌표가 등록되었습니다: ({x_val}, {y_val})")
        self._root.deiconify()
        self._set_capture_listener(None)


class Pos3Row:
    """pos3 모드 좌표 입력 행 위젯."""

    def __init__(
        self,
        parent: tk.Widget,
        label_text: str,
        target_entries: dict[str, tuple[tk.Entry, tk.Entry]],
        pos3_mode_var: tk.IntVar,
        pos3_mode_coordinates: dict[int, dict[str, str]],
        *,
        status_var: tk.StringVar,
        root: tk.Tk,
        get_capture_listener: Callable[[], mouse.Listener | None],
        set_capture_listener: Callable[[mouse.Listener | None], None],
        get_pos3_mode_name: Callable[[int], str],
    ) -> None:
        """pos3 모드 좌표 입력 행을 생성합니다."""
        self._label_text = label_text
        self._pos3_mode_var = pos3_mode_var
        self._pos3_mode_coordinates = pos3_mode_coordinates
        self._status_var = status_var
        self._root = root
        self._get_capture_listener = get_capture_listener
        self._set_capture_listener = set_capture_listener
        self._get_pos3_mode_name = get_pos3_mode_name

        frame = tk.Frame(parent)
        frame.pack(fill="x", padx=10, pady=5)

        tk.Label(frame, text=label_text, width=8, anchor="w").pack(side="left")

        self._x_entry = tk.Entry(frame, width=6)
        self._x_entry.pack(side="left", padx=(0, 4))

        self._y_entry = tk.Entry(frame, width=6)
        self._y_entry.pack(side="left")

        target_entries["pos3"] = (self._x_entry, self._y_entry)
        self._load_mode_values()

        register_button = tk.Button(frame, text="좌표등록", command=self._start_capture)
        register_button.pack(side="left", padx=(6, 0))

    def _load_mode_values(self) -> None:
        """현재 모드의 좌표를 로드합니다."""
        mode = self._pos3_mode_var.get()
        coords = self._pos3_mode_coordinates.get(mode, {"x": "0", "y": "0"})
        self._x_entry.delete(0, tk.END)
        self._x_entry.insert(0, coords["x"])
        self._y_entry.delete(0, tk.END)
        self._y_entry.insert(0, coords["y"])

    def _start_capture(self) -> None:
        """좌표 캡처를 시작합니다."""
        from tkinter import messagebox

        capture_listener = self._get_capture_listener()
        if capture_listener is not None and capture_listener.running:
            messagebox.showinfo("좌표 등록", "다른 좌표 등록이 진행 중입니다.")
            return

        mode = self._pos3_mode_var.get()
        mode_name = self._get_pos3_mode_name(mode)
        self._status_var.set(f"{self._label_text}({mode_name}) 등록: 원하는 위치를 클릭하세요.")
        self._root.withdraw()

        def on_click(x: float, y: float, button: mouse.Button, pressed: bool) -> bool:
            if pressed and button == mouse.Button.left:
                self._root.after(0, self._finalize_capture, int(x), int(y))
                return False
            return True

        listener = mouse.Listener(on_click=on_click)
        self._set_capture_listener(listener)
        listener.start()

    def _finalize_capture(self, x_val: int, y_val: int) -> None:
        """좌표 캡처를 완료합니다."""
        mode = self._pos3_mode_var.get()
        self._pos3_mode_coordinates[mode] = {"x": str(x_val), "y": str(y_val)}
        self._x_entry.delete(0, tk.END)
        self._x_entry.insert(0, str(x_val))
        self._y_entry.delete(0, tk.END)
        self._y_entry.insert(0, str(y_val))
        mode_name = self._get_pos3_mode_name(mode)
        self._status_var.set(
            f"{self._label_text}({mode_name}) 좌표가 등록되었습니다: ({x_val}, {y_val})"
        )
        self._root.deiconify()
        self._set_capture_listener(None)

    def reload_mode_values(self) -> None:
        """외부에서 모드 변경 시 호출하여 좌표를 다시 로드합니다."""
        self._load_mode_values()


class DelaySettingsFrame:
    """딜레이 설정 프레임."""

    def __init__(self, parent: tk.Widget, title: str) -> None:
        """딜레이 설정 프레임을 생성합니다.

        Args:
            parent: 부모 위젯
            title: 프레임 타이틀
        """
        self._frame = tk.LabelFrame(parent, text=title)
        self._frame.pack(fill="x", padx=10, pady=(0, 10))

    def add_step_delay_row(
        self,
        title: str,
        steps: list[tuple[tk.StringVar, str]],
    ) -> None:
        """단계별 딜레이 입력 행을 추가합니다.

        Args:
            title: 행 타이틀
            steps: (변수, 라벨) 튜플 리스트
        """
        row = tk.Frame(self._frame)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=title, width=10, anchor="w").pack(side="left")
        for idx, (var, label_text) in enumerate(steps):
            tk.Entry(row, textvariable=var, width=6).pack(side="left", padx=(0, 4))
            tk.Label(row, text=label_text).pack(side="left", padx=(0, 4))
            if idx < len(steps) - 1:
                tk.Label(row, text="-").pack(side="left", padx=(0, 4))

    def add_single_delay_row(
        self,
        title: str,
        var: tk.StringVar,
        suffix: str = "ms",
    ) -> None:
        """단일 딜레이 입력 행을 추가합니다.

        Args:
            title: 행 타이틀
            var: 입력 변수
            suffix: 단위 접미사
        """
        row = tk.Frame(self._frame)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=title, width=10, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=var, width=8).pack(side="left", padx=(0, 6))
        if suffix:
            tk.Label(row, text=suffix).pack(side="left")


class TabPanel:
    """탭 패널 관리 클래스."""

    TAB_ACTIVE_BG = "#ffffff"
    TAB_INACTIVE_BG = "#e6e6e6"
    TAB_BORDER = "#bdbdbd"

    def __init__(
        self,
        content_frame: tk.Frame,
        ui_mode: tk.StringVar,
    ) -> None:
        """탭 패널을 생성합니다.

        Args:
            content_frame: 콘텐츠 프레임
            ui_mode: UI 모드 변수
        """
        self._ui_mode = ui_mode

        tab_bar = tk.Frame(content_frame, bg=self.TAB_ACTIVE_BG)
        tab_bar.pack(fill="x", padx=6, pady=(0, 0))

        tab_button_holder = tk.Frame(tab_bar, bg=self.TAB_ACTIVE_BG)
        tab_button_holder.pack(side="left")

        self._panel_frame = tk.Frame(
            content_frame,
            bg=self.TAB_ACTIVE_BG,
            highlightthickness=1,
            highlightbackground=self.TAB_BORDER,
        )
        self._panel_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._ui1_frame = tk.Frame(self._panel_frame, bg=self.TAB_ACTIVE_BG)
        self._ui2_frame = tk.Frame(self._panel_frame, bg=self.TAB_ACTIVE_BG)

        self._tab_button_1 = tk.Button(
            tab_button_holder,
            text="채변",
            width=10,
            takefocus=True,
        )
        self._tab_button_1.pack(side="left", padx=(0, 6), pady=(0, 0))

        self._tab_button_2 = tk.Button(
            tab_button_holder,
            text="월재",
            width=10,
            takefocus=True,
        )
        self._tab_button_2.pack(side="left", pady=(0, 0))

        self._bind_tab_activate(self._tab_button_1, "1")
        self._bind_tab_activate(self._tab_button_2, "2")

    def _style_tab_button(self, button: tk.Button, *, active: bool) -> None:
        """탭 버튼 스타일을 설정합니다."""
        if active:
            button.configure(
                bg=self.TAB_ACTIVE_BG,
                fg="#000000",
                relief="solid",
                bd=1,
                highlightthickness=0,
                activebackground=self.TAB_ACTIVE_BG,
                activeforeground="#000000",
            )
        else:
            button.configure(
                bg=self.TAB_INACTIVE_BG,
                fg="#555555",
                relief="ridge",
                bd=1,
                highlightthickness=0,
                activebackground="#dcdcdc",
                activeforeground="#333333",
            )

    def _bind_tab_activate(self, button: tk.Button, mode: str) -> None:
        """탭 버튼에 활성화 이벤트를 바인딩합니다."""

        def _activate(event: tk.Event[tk.Widget] | None = None) -> None:
            self.switch_ui(mode)

        button.configure(command=_activate)
        button.bind("<Return>", _activate)
        button.bind("<space>", _activate)

    def switch_ui(self, mode: str) -> None:
        """UI 모드를 전환합니다.

        Args:
            mode: "1" 또는 "2"
        """
        target = "2" if mode == "2" else "1"
        self._ui_mode.set(target)
        self._ui1_frame.pack_forget()
        self._ui2_frame.pack_forget()
        if target == "1":
            self._style_tab_button(self._tab_button_1, active=True)
            self._style_tab_button(self._tab_button_2, active=False)
            self._ui1_frame.pack(fill="both", expand=True)
        else:
            self._style_tab_button(self._tab_button_1, active=False)
            self._style_tab_button(self._tab_button_2, active=True)
            self._ui2_frame.pack(fill="both", expand=True)

    @property
    def ui1_frame(self) -> tk.Frame:
        """UI1 프레임을 반환합니다."""
        return self._ui1_frame

    @property
    def ui2_frame(self) -> tk.Frame:
        """UI2 프레임을 반환합니다."""
        return self._ui2_frame
