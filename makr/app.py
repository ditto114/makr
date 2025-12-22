"""단계별 마우스/키보드 자동화를 위한 간단한 GUI.

macOS에서 최상단에 고정된 창을 제공하며, F1/F2 단축키로
순차 동작을 제어합니다.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Callable

import pyautogui
from makr.packet import PacketCaptureManager
from pynput import keyboard, mouse
from PySide6 import QtCore, QtGui, QtWidgets

APP_STATE_PATH = Path(__file__).with_name("app_state.json")

# pyautogui의 기본 지연(0.1초)을 제거해 클릭 간 딜레이를 사용자 설정값에만 의존하도록 합니다.
pyautogui.PAUSE = 0


def load_app_state() -> dict:
    if not APP_STATE_PATH.exists():
        return {}
    try:
        return json.loads(APP_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_app_state(state: dict) -> None:
    try:
        APP_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        QtWidgets.QMessageBox.warning(None, "설정 저장", "입력값을 저장하는 중 오류가 발생했습니다.")


@dataclass
class DelayConfig:
    f2_before_esc: Callable[[], int]
    f2_before_pos1: Callable[[], int]
    f2_before_pos2: Callable[[], int]
    f1_before_pos3: Callable[[], int]
    f1_before_enter: Callable[[], int]
    f1_newline_before_pos4: Callable[[], int]
    f1_newline_before_pos3: Callable[[], int]
    f1_newline_before_enter: Callable[[], int]


def call_on_main(func: Callable[[], None]) -> None:
    QtCore.QTimer.singleShot(0, func)


class MacroController:
    """실행 순서를 관리하고 GUI 콜백을 제공합니다."""

    def __init__(
        self,
        entries: dict[str, tuple[QtWidgets.QLineEdit, QtWidgets.QLineEdit]],
        status_label: QtWidgets.QLabel,
        delay_config: DelayConfig,
    ) -> None:
        self.entries = entries
        self.status_label = status_label
        self.current_step = 1
        self.delay_config = delay_config
        self._update_status()

    def _update_status(self) -> None:
        self.status_label.setText(f"다음 실행 단계: {self.current_step}단계")

    def _get_point(self, key: str) -> tuple[int, int] | None:
        x_entry, y_entry = self.entries[key]
        try:
            x_val = int(x_entry.text())
            y_val = int(y_entry.text())
        except ValueError:
            QtWidgets.QMessageBox.critical(None, "좌표 오류", f"{key} 좌표를 정수로 입력해주세요.")
            return None
        return x_val, y_val

    def _click_point(self, point: tuple[int, int], *, label: str | None = None) -> None:
        x_val, y_val = point
        pyautogui.click(x_val, y_val)

    def _press_key(self, key: str, *, label: str | None = None) -> None:
        pyautogui.press(key)

    def _delay_seconds(self, delay_ms: int) -> float:
        return max(delay_ms, 0) / 1000

    def _sleep_ms(self, delay_ms: int) -> None:
        delay_sec = self._delay_seconds(delay_ms)
        if delay_sec:
            time.sleep(delay_sec)

    def run_step(self, *, newline_mode: bool = False) -> None:
        """실행 단축키 콜백: 현재 단계 수행 후 다음 단계로 이동."""
        if self.current_step == 1:
            self._run_step_one()
            self.current_step = 2
        else:
            self._run_step_two(newline_mode=newline_mode)
            self.current_step = 1
        self._update_status()

    def reset_and_run_first(self, *, newline_mode: bool = False) -> None:
        """다시 단축키 콜백: Esc 입력 후 1단계를 재실행."""
        self._sleep_ms(self.delay_config.f2_before_esc())
        self._press_key("esc", label="초기화 ESC")
        self.current_step = 1
        self._update_status()
        self._run_step_one()
        self.current_step = 2
        self._update_status()

    def _run_step_one(self) -> None:
        pos1 = self._get_point("pos1")
        pos2 = self._get_point("pos2")
        if pos1 is None or pos2 is None:
            return
        self._sleep_ms(self.delay_config.f2_before_pos1())
        self._click_point(pos1, label="1단계 pos1")
        self._sleep_ms(self.delay_config.f2_before_pos2())
        self._click_point(pos2, label="1단계 pos2")

    def _run_step_two(self, *, newline_mode: bool = False) -> None:
        pos3 = self._get_point("pos3")
        if pos3 is None:
            return
        if newline_mode:
            pos4 = self._get_point("pos4")
            if pos4 is None:
                return
            self._sleep_ms(self.delay_config.f1_newline_before_pos4())
            self._click_point(pos4, label="2단계 pos4")
            self._sleep_ms(self.delay_config.f1_newline_before_pos3())
        else:
            self._sleep_ms(self.delay_config.f1_before_pos3())
        self._click_point(pos3, label="2단계 pos3")
        self._sleep_ms(
            self.delay_config.f1_newline_before_enter()
            if newline_mode
            else self.delay_config.f1_before_enter()
        )
        self._press_key("enter", label="2단계 Enter")


class ChannelSegmentRecorder:
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
        return re.sub(r"[^A-Za-z0-9가-힣]", "-", text)

    def feed(self, text: str) -> None:
        normalized = self._normalize(text)
        if not normalized:
            return
        if self.anchor_keyword in normalized and self._on_channel_activity is not None:
            self._on_channel_activity(time.time())
        self._buffer += normalized
        self._process_buffer()

    def _process_buffer(self) -> None:
        while True:
            anchor_idx = self._buffer.find(self.anchor_keyword)
            if anchor_idx == -1:
                # 불필요한 데이터가 과도하게 쌓이지 않도록 끝부분만 유지
                self._buffer = self._buffer[-len(self.anchor_keyword) :]
                return
            if self._on_channel_activity is not None:
                self._on_channel_activity(time.time())

            search_start = anchor_idx + len(self.anchor_keyword)
            match = self._pattern.search(self._buffer, pos=search_start)
            if match is None:
                # 앵커부터의 문자열만 유지하여 다음 입력을 기다림
                self._buffer = self._buffer[anchor_idx:]
                return

            captured = match.group(0).replace("-", "")
            self._on_capture(captured)

            # 매칭된 구간 이후 데이터를 유지하여 추가 탐색
            self._buffer = self._buffer[match.end() :]


class ChannelDetectionSequence:
    def __init__(self, app: "AppWindow") -> None:
        self.app = app
        self.running = False
        self.detection_queue: Queue[tuple[float, bool]] = Queue()
        self.newline_mode = False
        self.last_detected_at: float | None = None

    def start(self, newline_mode: bool) -> None:
        if self.running:
            QtWidgets.QMessageBox.information(self.app, "매크로", "F3 매크로가 이미 실행 중입니다.")
            return
        self.running = True
        self._clear_queue()
        self.newline_mode = newline_mode
        self.last_detected_at = None
        threading.Thread(target=self._run_sequence, daemon=True).start()

    def stop(self) -> None:
        self.running = False
        self._clear_queue()
        self.last_detected_at = None

    def notify_channel_found(
        self, *, detected_at: float | None = None, is_new: bool
    ) -> None:
        if not self.running:
            return
        timestamp = detected_at or time.time()
        self.detection_queue.put((timestamp, is_new))

    def _run_on_main(self, func: Callable[[], None]) -> None:
        done = threading.Event()

        def _wrapper() -> None:
            try:
                func()
            finally:
                done.set()

        call_on_main(_wrapper)
        done.wait()

    def _set_status(self, message: str) -> None:
        call_on_main(lambda: self.app.status_label.setText(message))

    def _clear_queue(self) -> None:
        while True:
            try:
                self.detection_queue.get_nowait()
            except Empty:
                break

    def _wait_for_detection(self, timeout_sec: float) -> tuple[float, bool] | None:
        if timeout_sec <= 0:
            try:
                return self.detection_queue.get_nowait()
            except Empty:
                return None

        deadline = time.time() + timeout_sec
        while self.running:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                return self.detection_queue.get(timeout=remaining)
            except Empty:
                continue
        return None

    def _run_sequence(self) -> None:
        try:
            while self.running:
                self._set_status("F3: F2 기능 실행 중…")
                self._run_on_main(
                    lambda: self.app.controller.reset_and_run_first(
                        newline_mode=self.newline_mode
                    )
                )

                self._set_status("F3: 채널명 감시 중…")
                self._clear_queue()
                timeout_sec = self._delay_seconds(self.app.get_channel_timeout_ms())
                first_detection = self._wait_for_detection(timeout_sec)
                self.last_detected_at = first_detection[0] if first_detection else None

                if not self.running:
                    break

                if first_detection is None:
                    self._set_status("F3: 채널명이 발견되지 않았습니다. 재시도합니다…")
                    continue

                first_time, is_new = first_detection
                if is_new:
                    self._set_status("F3: 새 채널명 기록, F1 실행 중…")
                    self._run_on_main(
                        lambda: self.app.controller.run_step(
                            newline_mode=self.newline_mode
                        )
                    )
                    break

                watch_interval = self._delay_seconds(self.app.get_channel_watch_interval_ms())
                if watch_interval <= 0:
                    self._set_status("F3: 새 채널명이 없어 재시작합니다…")
                    continue

                deadline = first_time + watch_interval
                new_channel_found = False

                while self.running:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break

                    event = self._wait_for_detection(remaining)
                    if not self.running:
                        break
                    if event is None:
                        break

                    detected_time, event_is_new = event
                    deadline = detected_time + watch_interval
                    self.last_detected_at = detected_time

                    if event_is_new:
                        new_channel_found = True
                        break

                if not self.running:
                    break

                if new_channel_found:
                    self._set_status("F3: 새 채널명 기록, F1 실행 중…")
                    self._run_on_main(
                        lambda: self.app.controller.run_step(
                            newline_mode=self.newline_mode
                        )
                    )
                    break

                self._set_status("F3: 새 채널명이 없어 재시작합니다…")
        finally:
            self.running = False
            self._run_on_main(self.app.controller._update_status)

    def _delay_seconds(self, delay_ms: int) -> float:
        return max(delay_ms, 0) / 1000


class AppWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("단계별 자동화")
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)

        self.saved_state = load_app_state()

        self.status_label = QtWidgets.QLabel()
        self.f2_before_esc_edit = QtWidgets.QLineEdit(str(self.saved_state.get("delay_f2_before_esc_ms", "0")))
        self.f2_before_pos1_edit = QtWidgets.QLineEdit(str(self.saved_state.get("delay_f2_before_pos1_ms", "0")))
        self.f2_before_pos2_edit = QtWidgets.QLineEdit(
            str(self.saved_state.get("delay_f2_before_pos2_ms", self.saved_state.get("click_delay_ms", "100")))
        )
        self.f1_before_pos3_edit = QtWidgets.QLineEdit(str(self.saved_state.get("delay_f1_before_pos3_ms", "0")))
        self.f1_before_enter_edit = QtWidgets.QLineEdit(str(self.saved_state.get("delay_f1_before_enter_ms", "0")))
        self.f1_newline_before_pos4_edit = QtWidgets.QLineEdit(
            str(self.saved_state.get("delay_f1_newline_before_pos4_ms", "0"))
        )
        self.f1_newline_before_pos3_edit = QtWidgets.QLineEdit(
            str(self.saved_state.get("delay_f1_newline_before_pos3_ms", "30"))
        )
        self.f1_newline_before_enter_edit = QtWidgets.QLineEdit(
            str(self.saved_state.get("delay_f1_newline_before_enter_ms", "0"))
        )
        self.channel_watch_interval_edit = QtWidgets.QLineEdit(
            str(self.saved_state.get("channel_watch_interval_ms", "200"))
        )
        self.channel_timeout_edit = QtWidgets.QLineEdit(str(self.saved_state.get("channel_timeout_ms", "5000")))
        self.newline_checkbox = QtWidgets.QCheckBox("줄바꿈")
        self.newline_checkbox.setChecked(bool(self.saved_state.get("newline_after_pos2", False)))

        self.entries: dict[str, tuple[QtWidgets.QLineEdit, QtWidgets.QLineEdit]] = {}
        self.capture_listener: mouse.Listener | None = None
        self.hotkey_listener: keyboard.Listener | None = None

        self.test_window: QtWidgets.QDialog | None = None
        self.test_table: QtWidgets.QTableWidget | None = None
        self.test_detail_text: QtWidgets.QTextEdit | None = None
        self.pattern_table: QtWidgets.QTableWidget | None = None
        self.test_records: list[tuple[str, str, str | None, str, list[list[str]]]] = []
        self.test_channel_names: list[str] = []
        self.test_channel_name_set: set[str] = set()
        self.pattern_table_regex = re.compile(r"[A-Z][가-힣]\d{2,3}")

        self._build_ui()

        self.delay_config = DelayConfig(
            f2_before_esc=self._make_delay_getter(self.f2_before_esc_edit, "(F2) Esc 전", 0),
            f2_before_pos1=self._make_delay_getter(self.f2_before_pos1_edit, "(F2) pos1 전", 0),
            f2_before_pos2=self._make_delay_getter(self.f2_before_pos2_edit, "(F2) pos2 전", 100),
            f1_before_pos3=self._make_delay_getter(self.f1_before_pos3_edit, "(F1-1) pos3 전", 0),
            f1_before_enter=self._make_delay_getter(self.f1_before_enter_edit, "(F1-1) Enter 전", 0),
            f1_newline_before_pos4=self._make_delay_getter(
                self.f1_newline_before_pos4_edit, "(F1-2) pos4 전", 0
            ),
            f1_newline_before_pos3=self._make_delay_getter(
                self.f1_newline_before_pos3_edit, "(F1-2) pos3 전", 30
            ),
            f1_newline_before_enter=self._make_delay_getter(
                self.f1_newline_before_enter_edit, "(F1-2) Enter 전", 0
            ),
        )

        self.controller = MacroController(self.entries, self.status_label, self.delay_config)

        self.channel_detection_sequence = ChannelDetectionSequence(self)
        self.channel_segment_recorder = ChannelSegmentRecorder(
            self.handle_captured_pattern,
            on_channel_activity=self._on_channel_activity,
        )

        self.packet_manager = PacketCaptureManager(
            on_packet=lambda text: call_on_main(lambda: self.process_packet_detection(text)),
            on_error=lambda msg: call_on_main(
                lambda: QtWidgets.QMessageBox.critical(self, "패킷 캡쳐 오류", msg)
            ),
        )

        self.update_packet_capture_button()
        self.packet_capture_button.clicked.connect(self.toggle_packet_capture)

        self.test_button.clicked.connect(self.show_test_window)

        self.start_hotkey_listener()

    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.addStretch()
        top_bar.addWidget(self.newline_checkbox)
        main_layout.addLayout(top_bar)

        info_label = QtWidgets.QLabel("좌표는 화면 기준 픽셀 단위로 입력하세요 (X, Y).")
        info_label.setStyleSheet("color: #444444;")
        main_layout.addWidget(info_label)

        for label_text in ["pos1", "pos2", "pos3", "pos4"]:
            main_layout.addLayout(self._add_coordinate_row(label_text, label_text))

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        self.test_button = QtWidgets.QPushButton("테스트")
        self.test_button.setFixedWidth(120)
        self.packet_capture_button = QtWidgets.QPushButton("패킷캡쳐 시작")
        self.packet_capture_button.setFixedWidth(120)
        button_layout.addWidget(self.test_button)
        button_layout.addWidget(self.packet_capture_button)
        main_layout.addLayout(button_layout)

        delay_group = QtWidgets.QGroupBox("딜레이 설정")
        delay_layout = QtWidgets.QVBoxLayout()
        delay_layout.setSpacing(6)

        delay_layout.addLayout(
            self._add_step_delay_row(
                "(F2)",
                [
                    (self.f2_before_esc_edit, "Esc"),
                    (self.f2_before_pos1_edit, "pos1"),
                    (self.f2_before_pos2_edit, "pos2"),
                ],
            )
        )
        delay_layout.addLayout(
            self._add_single_delay_row("채널감시주기", self.channel_watch_interval_edit, "ms (기본 200)")
        )
        delay_layout.addLayout(
            self._add_single_delay_row("채널타임아웃", self.channel_timeout_edit, "ms (기본 5000)")
        )
        delay_layout.addLayout(
            self._add_step_delay_row(
                "(F1-1)",
                [
                    (self.f1_before_pos3_edit, "pos3"),
                    (self.f1_before_enter_edit, "Enter"),
                ],
            )
        )
        delay_layout.addLayout(
            self._add_step_delay_row(
                "(F1-2)",
                [
                    (self.f1_newline_before_pos4_edit, "pos4"),
                    (self.f1_newline_before_pos3_edit, "pos3"),
                    (self.f1_newline_before_enter_edit, "Enter"),
                ],
            )
        )
        delay_group.setLayout(delay_layout)
        main_layout.addWidget(delay_group)

        self.status_label.setStyleSheet("color: #006400;")
        main_layout.addWidget(self.status_label)

    def _add_coordinate_row(self, label_text: str, key: str) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QtWidgets.QLabel(label_text)
        label.setFixedWidth(40)
        layout.addWidget(label)

        x_entry = QtWidgets.QLineEdit()
        x_entry.setFixedWidth(60)
        x_entry.setText(str(self.saved_state.get("coordinates", {}).get(key, {}).get("x", "0")))
        layout.addWidget(x_entry)

        y_entry = QtWidgets.QLineEdit()
        y_entry.setFixedWidth(60)
        y_entry.setText(str(self.saved_state.get("coordinates", {}).get(key, {}).get("y", "0")))
        layout.addWidget(y_entry)

        self.entries[key] = (x_entry, y_entry)

        register_button = QtWidgets.QPushButton("클릭으로 등록")
        register_button.clicked.connect(lambda: self._start_capture(label_text, key))
        layout.addWidget(register_button)
        layout.addStretch()
        return layout

    def _start_capture(self, label_text: str, key: str) -> None:
        if self.capture_listener is not None and self.capture_listener.running:
            QtWidgets.QMessageBox.information(self, "좌표 등록", "다른 좌표 등록이 진행 중입니다.")
            return

        self.status_label.setText(f"{label_text} 등록: 원하는 위치를 클릭하세요.")
        self.hide()

        def on_click(x: float, y: float, button: mouse.Button, pressed: bool) -> bool:
            if pressed and button == mouse.Button.left:
                call_on_main(lambda: self._finalize_capture(key, int(x), int(y), label_text))
                return False
            return True

        self.capture_listener = mouse.Listener(on_click=on_click)
        self.capture_listener.start()

    def _finalize_capture(self, target_key: str, x_val: int, y_val: int, label_text: str) -> None:
        x_entry_local, y_entry_local = self.entries[target_key]
        x_entry_local.setText(str(x_val))
        y_entry_local.setText(str(y_val))
        self.status_label.setText(f"{label_text} 좌표가 등록되었습니다: ({x_val}, {y_val})")
        self.show()
        self.capture_listener = None

    def _parse_delay_ms(self, edit: QtWidgets.QLineEdit, label: str, fallback: int) -> int:
        try:
            delay_ms = int(float(edit.text()))
        except ValueError:
            QtWidgets.QMessageBox.critical(self, f"{label} 오류", f"{label}를 숫자로 입력하세요.")
            delay_ms = fallback
        if delay_ms < 0:
            QtWidgets.QMessageBox.critical(self, f"{label} 오류", f"{label}는 0 이상이어야 합니다.")
            delay_ms = 0
        edit.setText(str(delay_ms))
        return delay_ms

    def _make_delay_getter(self, edit: QtWidgets.QLineEdit, label: str, fallback: int) -> Callable[[], int]:
        return lambda: self._parse_delay_ms(edit, label, fallback)

    def get_channel_watch_interval_ms(self) -> int:
        return self._parse_delay_ms(self.channel_watch_interval_edit, "채널 감시 주기", 200)

    def get_channel_timeout_ms(self) -> int:
        return self._parse_delay_ms(self.channel_timeout_edit, "채널 타임아웃", 5000)

    def _add_step_delay_row(
        self, title: str, steps: list[tuple[QtWidgets.QLineEdit, str]]
    ) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        title_label = QtWidgets.QLabel(title)
        title_label.setFixedWidth(50)
        row.addWidget(title_label)

        for idx, (edit, label_text) in enumerate(steps):
            edit.setFixedWidth(60)
            row.addWidget(edit)
            row.addWidget(QtWidgets.QLabel(label_text))
            if idx < len(steps) - 1:
                row.addWidget(QtWidgets.QLabel("-"))
        row.addStretch()
        return row

    def _add_single_delay_row(
        self, title: str, edit: QtWidgets.QLineEdit, suffix: str = "ms"
    ) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        title_label = QtWidgets.QLabel(title)
        title_label.setFixedWidth(80)
        row.addWidget(title_label)
        edit.setFixedWidth(80)
        row.addWidget(edit)
        if suffix:
            row.addWidget(QtWidgets.QLabel(suffix))
        row.addStretch()
        return row

    def format_timestamp(self, ts: float) -> str:
        ts_int = int(ts)
        millis = int((ts - ts_int) * 1000)
        return time.strftime('%H:%M:%S', time.localtime(ts)) + f".{millis:03d}"

    def build_pattern_table(self, names: list[str]) -> tuple[str | None, list[list[str]]]:
        if not names:
            return None, []

        col_width = max(len(match) for match in names)
        rows_for_view: list[list[str]] = []
        formatted_rows: list[str] = []
        for idx in range(0, len(names), 6):
            chunk = names[idx : idx + 6]
            padded = chunk + [""] * (6 - len(chunk))
            rows_for_view.append(padded)
            formatted_rows.append(
                " | ".join(cell.ljust(col_width) if cell else "".ljust(col_width) for cell in padded)
            )

        return "\n".join(formatted_rows), rows_for_view

    def update_pattern_table(self) -> None:
        if self.pattern_table is None:
            return

        self.pattern_table.setRowCount(0)

        _, rows = self.build_pattern_table(self.test_channel_names)

        if not rows:
            self.pattern_table.setRowCount(1)
            self.pattern_table.setColumnCount(6)
            self.pattern_table.setVerticalHeaderLabels([])
            self.pattern_table.setHorizontalHeaderLabels([str(i) for i in range(1, 7)])
            self.pattern_table.setItem(0, 0, QtWidgets.QTableWidgetItem("(없음)"))
            return

        self.pattern_table.setRowCount(len(rows))
        self.pattern_table.setColumnCount(6)
        self.pattern_table.setHorizontalHeaderLabels([str(i) for i in range(1, 7)])
        for row_idx, row_values in enumerate(rows):
            padded = row_values + [""] * (6 - len(row_values))
            for col_idx, value in enumerate(padded[:6]):
                self.pattern_table.setItem(row_idx, col_idx, QtWidgets.QTableWidgetItem(value))

    def add_test_record(self, content: str) -> tuple[list[str], list[str]]:
        matches = self.pattern_table_regex.findall(content)
        new_names = [name for name in matches if name not in self.test_channel_name_set]
        if not matches:
            return [], []

        if new_names:
            for name in new_names:
                self.test_channel_name_set.add(name)
                self.test_channel_names.append(name)

            timestamp = self.format_timestamp(time.time())
            table_text, table_rows = self.build_pattern_table(self.test_channel_names)
            display_content = (
                f"{content}\n\n[추출된 패턴]\n{table_text}"
                if table_text
                else content
            )
            self.test_records.append((timestamp, content, table_text, display_content, table_rows))
            if self.test_table is not None:
                index = len(self.test_records)
                self.test_table.insertRow(self.test_table.rowCount())
                self.test_table.setItem(index - 1, 0, QtWidgets.QTableWidgetItem(str(index)))
                self.test_table.setItem(index - 1, 1, QtWidgets.QTableWidgetItem(timestamp))
                self.test_table.setItem(index - 1, 2, QtWidgets.QTableWidgetItem(display_content))
                self.test_table.selectRow(index - 1)
                self.update_test_detail(index)
                self.update_pattern_table()
        return matches, new_names

    def update_test_detail(self, selected_index: int | None = None) -> None:
        if self.test_detail_text is None:
            return

        if selected_index is None or selected_index < 1 or selected_index > len(self.test_records):
            self.test_detail_text.setPlainText("기록을 선택하세요.")
            self.update_pattern_table()
        else:
            _, content, table_text, _, _ = self.test_records[selected_index - 1]
            patterns = table_text or "(없음)"
            detail_text = f"{content}\n\n[추출된 패턴]\n{patterns}"
            self.test_detail_text.setPlainText(detail_text)

        self.update_pattern_table()

    def refresh_test_table(self) -> None:
        if self.test_table is None:
            return
        self.test_table.setRowCount(0)
        for idx, (ts, _, _, display_content, _) in enumerate(self.test_records, start=1):
            row = self.test_table.rowCount()
            self.test_table.insertRow(row)
            self.test_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(idx)))
            self.test_table.setItem(row, 1, QtWidgets.QTableWidgetItem(ts))
            self.test_table.setItem(row, 2, QtWidgets.QTableWidgetItem(display_content))
        if self.test_records:
            self.test_table.selectRow(0)
            self.update_test_detail(1)
        else:
            self.update_test_detail(None)

    def clear_test_records(self) -> None:
        self.test_channel_names.clear()
        self.test_channel_name_set.clear()
        self.test_records.clear()
        self.refresh_test_table()
        self.update_pattern_table()
        self.status_label.setText("테스트 기록이 초기화되었습니다.")

    def show_test_window(self) -> None:
        if self.test_window is not None and self.test_window.isVisible():
            self.test_window.raise_()
            self.test_window.activateWindow()
            self.refresh_test_table()
            return

        self.test_window = QtWidgets.QDialog(self)
        self.test_window.setWindowTitle("테스트")
        self.test_window.resize(520, 500)
        layout = QtWidgets.QVBoxLayout(self.test_window)

        info_label = QtWidgets.QLabel(
            (
                "ChannelName이 포함된 패킷을 정규화한 뒤, 다음 [A-가00- 또는 A-가000-] "
                "형태가 나타날 때까지 기록하고 해당 문자열에서 하이픈(-)을 제거해 "
                "추출합니다."
            )
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.test_table = QtWidgets.QTableWidget()
        self.test_table.setColumnCount(3)
        self.test_table.setHorizontalHeaderLabels(["#", "시간", "기록"])
        self.test_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.test_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.test_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.test_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.test_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.test_table.verticalHeader().setVisible(False)
        layout.addWidget(self.test_table, stretch=1)

        detail_group = QtWidgets.QGroupBox("선택 기록 상세")
        detail_layout = QtWidgets.QVBoxLayout()
        self.test_detail_text = QtWidgets.QTextEdit()
        self.test_detail_text.setReadOnly(True)
        detail_layout.addWidget(self.test_detail_text)
        detail_group.setLayout(detail_layout)
        layout.addWidget(detail_group, stretch=1)

        pattern_group = QtWidgets.QGroupBox("추출된 패턴 표")
        pattern_layout = QtWidgets.QVBoxLayout()
        self.pattern_table = QtWidgets.QTableWidget()
        self.pattern_table.setColumnCount(6)
        self.pattern_table.setHorizontalHeaderLabels([str(i) for i in range(1, 7)])
        self.pattern_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.pattern_table.verticalHeader().setVisible(False)
        pattern_layout.addWidget(self.pattern_table)
        pattern_group.setLayout(pattern_layout)
        layout.addWidget(pattern_group, stretch=1)

        button_bar = QtWidgets.QHBoxLayout()
        button_bar.addStretch()
        clear_button = QtWidgets.QPushButton("기록 초기화")
        clear_button.clicked.connect(self.clear_test_records)
        button_bar.addWidget(clear_button)
        layout.addLayout(button_bar)

        self.refresh_test_table()
        self.update_pattern_table()

        def on_selection_changed() -> None:
            if self.test_table is None:
                return
            selected = self.test_table.selectedItems()
            if not selected:
                self.update_test_detail(None)
                return
            row = selected[0].row()
            self.update_test_detail(row + 1)

        self.test_table.itemSelectionChanged.connect(on_selection_changed)

        def on_close() -> None:
            if self.test_table is not None:
                self.test_table.clearSelection()
            self.test_table = None
            self.test_detail_text = None
            self.pattern_table = None
            self.test_window = None

        self.test_window.finished.connect(on_close)
        self.test_window.show()

    def collect_app_state(self) -> dict:
        coordinates: dict[str, dict[str, str]] = {}
        for key, (x_entry, y_entry) in self.entries.items():
            coordinates[key] = {"x": x_entry.text(), "y": y_entry.text()}
        return {
            "coordinates": coordinates,
            "delay_f2_before_esc_ms": self.f2_before_esc_edit.text(),
            "delay_f2_before_pos1_ms": self.f2_before_pos1_edit.text(),
            "delay_f2_before_pos2_ms": self.f2_before_pos2_edit.text(),
            "delay_f1_before_pos3_ms": self.f1_before_pos3_edit.text(),
            "delay_f1_before_enter_ms": self.f1_before_enter_edit.text(),
            "delay_f1_newline_before_pos4_ms": self.f1_newline_before_pos4_edit.text(),
            "delay_f1_newline_before_pos3_ms": self.f1_newline_before_pos3_edit.text(),
            "delay_f1_newline_before_enter_ms": self.f1_newline_before_enter_edit.text(),
            "channel_watch_interval_ms": self.channel_watch_interval_edit.text(),
            "channel_timeout_ms": self.channel_timeout_edit.text(),
            "newline_after_pos2": self.newline_checkbox.isChecked(),
        }

    def handle_captured_pattern(self, content: str) -> None:
        detected_at = time.time()
        matches, new_names = self.add_test_record(content)
        if matches:
            self.channel_detection_sequence.notify_channel_found(
                detected_at=detected_at,
                is_new=bool(new_names),
            )

    def _on_channel_activity(self, timestamp: float) -> None:
        self.channel_detection_sequence.last_detected_at = timestamp

    def process_packet_detection(self, text: str) -> None:
        self.channel_segment_recorder.feed(text)

    def update_packet_capture_button(self) -> None:
        text = "패킷캡쳐 중지" if self.packet_manager.running else "패킷캡쳐 시작"
        self.packet_capture_button.setText(text)

    def start_packet_capture(self) -> None:
        if self.packet_manager.running:
            return
        try:
            started = self.packet_manager.start()
        except Exception as exc:  # pragma: no cover - 안전망
            QtWidgets.QMessageBox.critical(self, "패킷 캡쳐 오류", f"패킷 캡쳐 시작 실패: {exc}")
            self.update_packet_capture_button()
            return

        if not started:
            QtWidgets.QMessageBox.warning(
                self, "패킷 캡쳐", "패킷 캡쳐를 시작하지 못했습니다. scapy 설치 여부를 확인하세요."
            )
            self.update_packet_capture_button()
            return

        self.status_label.setText("패킷 캡쳐가 시작되었습니다.")
        self.update_packet_capture_button()

    def stop_packet_capture(self) -> None:
        if not self.packet_manager.running:
            return
        try:
            self.packet_manager.stop()
        except Exception:
            QtWidgets.QMessageBox.warning(self, "패킷 캡쳐", "패킷 캡쳐 중지 실패")
        else:
            self.status_label.setText("패킷 캡쳐가 중지되었습니다.")
        finally:
            self.update_packet_capture_button()

    def toggle_packet_capture(self) -> None:
        if self.packet_manager.running:
            self.stop_packet_capture()
        else:
            self.start_packet_capture()

    def start_hotkey_listener(self) -> None:
        if self.hotkey_listener is not None:
            return

        def on_hotkey_press(key: keyboard.Key) -> None:
            if key == keyboard.Key.f1:
                call_on_main(lambda: self.controller.run_step(newline_mode=self.newline_checkbox.isChecked()))
            elif key == keyboard.Key.f2:
                call_on_main(lambda: self.controller.reset_and_run_first(newline_mode=self.newline_checkbox.isChecked()))
            elif key == keyboard.Key.f3:
                if self.channel_detection_sequence.running:
                    self.channel_detection_sequence.stop()
                    self.status_label.setText("F3 매크로가 종료되었습니다.")
                    self.controller._update_status()
                else:
                    self.channel_detection_sequence.start(self.newline_checkbox.isChecked())

        self.hotkey_listener = keyboard.Listener(on_press=on_hotkey_press)
        self.hotkey_listener.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        save_app_state(self.collect_app_state())
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        self.channel_detection_sequence.stop()
        self.stop_packet_capture()
        super().closeEvent(event)


def build_gui() -> None:
    app = QtWidgets.QApplication.instance()
    should_exec = False
    if app is None:
        app = QtWidgets.QApplication([])
        should_exec = True

    window = AppWindow()
    window.show()

    if should_exec:
        app.exec()


if __name__ == "__main__":
    build_gui()
