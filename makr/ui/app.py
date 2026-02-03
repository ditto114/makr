"""Main application class."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING

import pyautogui
from pynput import keyboard

from makr.core.config import (
    DelayConfig,
    UiTwoDelayConfig,
    DEFAULT_DELAY_F2_BEFORE_ESC_MS,
    DEFAULT_DELAY_F2_BEFORE_POS1_MS,
    DEFAULT_DELAY_F2_BEFORE_POS2_MS,
    DEFAULT_DELAY_F1_BEFORE_POS3_MS,
    DEFAULT_DELAY_F1_BEFORE_ENTER_MS,
    DEFAULT_F1_REPEAT_COUNT,
    DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS4_MS,
    DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS3_MS,
    DEFAULT_DELAY_F1_NEWLINE_BEFORE_ENTER_MS,
    DEFAULT_DELAY_F4_BETWEEN_POS11_POS12_MS,
    DEFAULT_DELAY_F4_BEFORE_ENTER_MS,
    DEFAULT_DELAY_F5_INTERVAL_MS,
    DEFAULT_DELAY_F6_INTERVAL_MS,
    DEFAULT_CHANNEL_WATCH_INTERVAL_MS,
    DEFAULT_CHANNEL_TIMEOUT_MS,
)
from makr.core.persistence import (
    NEW_CHANNEL_SOUND_PATH,
    load_app_state,
    save_app_state,
)
from makr.core.sound import SoundPlayer, BeepNotifier
from makr.core.channel import ChannelSegmentRecorder, format_devlogic_packet
from makr.core.state import DevLogicState, UI2AutomationState
from makr.controllers.macro_controller import MacroController
from makr.controllers.ui2_controller import UI2Controller
from makr.controllers.channel_detection import ChannelDetectionSequence
from makr.ui.styles import TAB_ACTIVE_BG, TAB_INACTIVE_BG, TAB_BORDER, style_tab_button
from makr.ui.panels.ui1_panel import UI1Panel
from makr.ui.panels.ui2_panel import UI2Panel
from makr.ui.windows.test_window import TestWindow
from makr.ui.windows.record_window import RecordWindow
from makr.packet import PacketCaptureManager

if TYPE_CHECKING:
    from pynput import mouse

# Disable pyautogui's default delay
pyautogui.PAUSE = 0


class MakrApplication:
    """Main application class that orchestrates all components."""

    UI1_LABEL_MAP = {
        "pos1": "메뉴",
        "pos2": "채널",
        "pos3": "열",
        "pos4": "∇",
        "esc_click": "Esc 클릭",
    }

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("대칭 전력")
        self.root.attributes("-topmost", True)

        self.saved_state = load_app_state()
        self._capture_listener: "mouse.Listener | None" = None
        self._hotkey_listener: keyboard.Listener | None = None

        self._init_variables()
        self._init_pos3_mode_coordinates()
        self._build_ui()
        self._init_controllers()
        self._init_packet_capture()
        self._setup_hotkeys()

    def _init_variables(self) -> None:
        """Initialize all tkinter variables."""
        self.status_var = tk.StringVar()
        self.devlogic_alert_var = tk.StringVar(value="")
        self.devlogic_packet_var = tk.StringVar(value="")
        self.ui_mode = tk.StringVar(value=str(self.saved_state.get("ui_mode", "1")))

        # UI1 delay variables
        self.f2_before_esc_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f2_before_esc_ms", DEFAULT_DELAY_F2_BEFORE_ESC_MS))
        )
        self.f2_before_pos1_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f2_before_pos1_ms", DEFAULT_DELAY_F2_BEFORE_POS1_MS))
        )
        self.f2_before_pos2_var = tk.StringVar(
            value=str(
                self.saved_state.get(
                    "delay_f2_before_pos2_ms",
                    self.saved_state.get("click_delay_ms", DEFAULT_DELAY_F2_BEFORE_POS2_MS),
                )
            )
        )
        self.f1_before_pos3_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f1_before_pos3_ms", DEFAULT_DELAY_F1_BEFORE_POS3_MS))
        )
        self.f1_before_enter_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f1_before_enter_ms", DEFAULT_DELAY_F1_BEFORE_ENTER_MS))
        )
        self.f1_repeat_count_var = tk.StringVar(
            value=str(self.saved_state.get("f1_repeat_count", DEFAULT_F1_REPEAT_COUNT))
        )
        self.f1_newline_before_pos4_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f1_newline_before_pos4_ms", DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS4_MS))
        )
        self.f1_newline_before_pos3_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f1_newline_before_pos3_ms", DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS3_MS))
        )
        self.f1_newline_before_enter_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f1_newline_before_enter_ms", DEFAULT_DELAY_F1_NEWLINE_BEFORE_ENTER_MS))
        )

        # UI2 delay variables
        self.f4_between_pos11_pos12_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f4_between_pos11_pos12_ms", DEFAULT_DELAY_F4_BETWEEN_POS11_POS12_MS))
        )
        self.f4_before_enter_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f4_before_enter_ms", DEFAULT_DELAY_F4_BEFORE_ENTER_MS))
        )
        self.f5_interval_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f5_interval_ms", DEFAULT_DELAY_F5_INTERVAL_MS))
        )
        self.f6_interval_var = tk.StringVar(
            value=str(self.saved_state.get("delay_f6_interval_ms", DEFAULT_DELAY_F6_INTERVAL_MS))
        )

        # Channel detection variables
        self.channel_watch_interval_var = tk.StringVar(
            value=str(self.saved_state.get("channel_watch_interval_ms", DEFAULT_CHANNEL_WATCH_INTERVAL_MS))
        )
        self.channel_timeout_var = tk.StringVar(
            value=str(self.saved_state.get("channel_timeout_ms", DEFAULT_CHANNEL_TIMEOUT_MS))
        )

        # Mode variables
        self.newline_var = tk.BooleanVar(value=bool(self.saved_state.get("newline_after_pos2", False)))
        self.esc_click_var = tk.BooleanVar(value=bool(self.saved_state.get("esc_click_enabled", False)))

        try:
            pos3_mode_initial = int(self.saved_state.get("pos3_mode", 1))
        except (TypeError, ValueError):
            pos3_mode_initial = 1
        if pos3_mode_initial not in range(1, 7):
            pos3_mode_initial = 1
        self.pos3_mode_var = tk.IntVar(value=pos3_mode_initial)

        self.ui2_automation_var = tk.BooleanVar(
            value=bool(self.saved_state.get("ui2_automation_enabled", False))
        )
        self.ui2_test_new_channel_var = tk.BooleanVar(
            value=bool(self.saved_state.get("ui2_test_new_channel", False))
        )

        # State objects
        self.devlogic_state = DevLogicState()
        self.ui2_state = UI2AutomationState()

    def _init_pos3_mode_coordinates(self) -> None:
        """Initialize pos3 mode coordinates from saved state."""
        self.pos3_mode_coordinates: dict[int, dict[str, str]] = {}
        saved_coordinates = self.saved_state.get("coordinates", {})
        legacy_pos3_coords = saved_coordinates.get("pos3", {})

        for mode in range(1, 7):
            mode_key = f"pos3_{mode}"
            coords = saved_coordinates.get(mode_key, {})
            if not coords and mode == 1 and legacy_pos3_coords:
                coords = legacy_pos3_coords
            self.pos3_mode_coordinates[mode] = {
                "x": str(coords.get("x", "0")),
                "y": str(coords.get("y", "0")),
            }

    def _build_ui(self) -> None:
        """Build the main UI."""
        # Top bar
        top_bar = tk.Frame(self.root)
        top_bar.pack(fill="x", pady=(6, 4))
        action_frame = tk.Frame(top_bar)
        action_frame.pack(side="left", padx=6)
        record_frame = tk.Frame(top_bar)
        record_frame.pack(side="right", padx=6)

        self.packet_capture_button = tk.Button(action_frame, text="패킷캡쳐 시작", width=12)
        self.packet_capture_button.pack(side="left", padx=(0, 6))

        test_button = tk.Button(action_frame, text="채널목록", width=12, command=self._show_test_window)
        test_button.pack(side="left")

        record_button = tk.Button(record_frame, text="월재기록", width=12, command=self._show_record_window)
        record_button.pack(side="right")

        # Content frame with tabs
        content_frame = tk.Frame(self.root)
        content_frame.pack(fill="both", expand=True)

        tab_bar = tk.Frame(content_frame, bg=TAB_ACTIVE_BG)
        tab_bar.pack(fill="x", padx=6, pady=(0, 0))
        tab_button_holder = tk.Frame(tab_bar, bg=TAB_ACTIVE_BG)
        tab_button_holder.pack(side="left")

        panel_frame = tk.Frame(
            content_frame,
            bg=TAB_ACTIVE_BG,
            highlightthickness=1,
            highlightbackground=TAB_BORDER,
        )
        panel_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Tab buttons
        self.tab_button_1 = tk.Button(tab_button_holder, text="채변", width=10, takefocus=True)
        self.tab_button_1.pack(side="left", padx=(0, 6), pady=(0, 0))

        self.tab_button_2 = tk.Button(tab_button_holder, text="월재", width=10, takefocus=True)
        self.tab_button_2.pack(side="left", pady=(0, 0))

        self._bind_tab_activate(self.tab_button_1, "1")
        self._bind_tab_activate(self.tab_button_2, "2")

        # Panels
        ui1_delay_vars = {
            "f2_before_esc": self.f2_before_esc_var,
            "f2_before_pos1": self.f2_before_pos1_var,
            "f2_before_pos2": self.f2_before_pos2_var,
            "f1_before_pos3": self.f1_before_pos3_var,
            "f1_before_enter": self.f1_before_enter_var,
            "f1_repeat_count": self.f1_repeat_count_var,
            "f1_newline_before_pos4": self.f1_newline_before_pos4_var,
            "f1_newline_before_pos3": self.f1_newline_before_pos3_var,
            "f1_newline_before_enter": self.f1_newline_before_enter_var,
            "channel_watch_interval": self.channel_watch_interval_var,
            "channel_timeout": self.channel_timeout_var,
        }

        self.ui1_panel = UI1Panel(
            panel_frame,
            self.saved_state,
            self.status_var,
            self.root,
            self.pos3_mode_var,
            self.pos3_mode_coordinates,
            self.newline_var,
            self.esc_click_var,
            ui1_delay_vars,
            self._get_capture_listener,
            self._clear_capture_listener,
            bg=TAB_ACTIVE_BG,
        )

        ui2_delay_vars = {
            "f4_between_pos11_pos12": self.f4_between_pos11_pos12_var,
            "f4_before_enter": self.f4_before_enter_var,
            "f5_interval": self.f5_interval_var,
            "f6_interval": self.f6_interval_var,
        }

        self.ui2_panel = UI2Panel(
            panel_frame,
            self.saved_state,
            self.status_var,
            self.root,
            self.ui2_automation_var,
            self.ui2_test_new_channel_var,
            ui2_delay_vars,
            self._get_capture_listener,
            self._clear_capture_listener,
            bg=TAB_ACTIVE_BG,
        )

        # Setup pos3 mode controls
        self.ui1_panel.pos3_mode_button.configure(command=self._cycle_pos3_mode)
        self.ui1_panel.newline_checkbox.configure(command=self._enforce_newline_mode)
        self.ui1_panel.update_pos3_mode_label()
        self._apply_newline_for_pos3_mode()

        # Status labels
        status_label = tk.Label(self.root, textvariable=self.status_var, fg="#006400")
        status_label.pack(pady=(0, 4))
        devlogic_label = tk.Label(self.root, textvariable=self.devlogic_alert_var, fg="red")
        devlogic_label.pack(pady=(0, 6))

        # Initialize tab
        self._switch_ui("1")

        # Windows
        self.test_window = TestWindow(self.root, self.status_var)
        self.record_window = RecordWindow(self.root)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_controllers(self) -> None:
        """Initialize controllers."""
        delay_config = DelayConfig(
            f2_before_esc=self._make_delay_getter(self.f2_before_esc_var, "(F2) Esc 전", DEFAULT_DELAY_F2_BEFORE_ESC_MS),
            f2_before_pos1=self._make_delay_getter(self.f2_before_pos1_var, "(F2) 메뉴 전", DEFAULT_DELAY_F2_BEFORE_POS1_MS),
            f2_before_pos2=self._make_delay_getter(self.f2_before_pos2_var, "(F2) 채널 전", DEFAULT_DELAY_F2_BEFORE_POS2_MS),
            f1_before_pos3=self._make_delay_getter(self.f1_before_pos3_var, "(F1-1) 열 전", DEFAULT_DELAY_F1_BEFORE_POS3_MS),
            f1_before_enter=self._make_delay_getter(self.f1_before_enter_var, "(F1-1) Enter 전", DEFAULT_DELAY_F1_BEFORE_ENTER_MS),
            f1_repeat_count=self._make_positive_int_getter(self.f1_repeat_count_var, "(F1) 반복 횟수", DEFAULT_F1_REPEAT_COUNT),
            f1_newline_before_pos4=self._make_delay_getter(self.f1_newline_before_pos4_var, "(F1-2) ∇ 전", DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS4_MS),
            f1_newline_before_pos3=self._make_delay_getter(self.f1_newline_before_pos3_var, "(F1-2) 열 전", DEFAULT_DELAY_F1_NEWLINE_BEFORE_POS3_MS),
            f1_newline_before_enter=self._make_delay_getter(self.f1_newline_before_enter_var, "(F1-2) Enter 전", DEFAULT_DELAY_F1_NEWLINE_BEFORE_ENTER_MS),
        )

        self.macro_controller = MacroController(
            self.ui1_panel.entries,
            self.status_var,
            delay_config,
            self.UI1_LABEL_MAP,
            use_esc_click=self.esc_click_var.get,
        )

        ui2_delay_config = UiTwoDelayConfig(
            f4_between_pos11_pos12=self._make_delay_getter(self.f4_between_pos11_pos12_var, "(F4) ···-🔃 전", DEFAULT_DELAY_F4_BETWEEN_POS11_POS12_MS),
            f4_before_enter=self._make_delay_getter(self.f4_before_enter_var, "(F4) Enter 전", DEFAULT_DELAY_F4_BEFORE_ENTER_MS),
            f5_interval=self._make_delay_getter(self.f5_interval_var, "(F5) 반복 간격", DEFAULT_DELAY_F5_INTERVAL_MS),
            f6_interval=self._make_delay_getter(self.f6_interval_var, "(F6) 반복 간격", DEFAULT_DELAY_F6_INTERVAL_MS),
        )

        self.ui2_controller = UI2Controller(
            self.ui2_panel.entries,
            ui2_delay_config,
            self._set_status_async,
            self.ui2_automation_var,
            self.ui2_test_new_channel_var,
        )
        self.ui2_controller.on_start_new_set = self._start_new_ui2_set
        self.ui2_controller.on_finish_set = self._finish_ui2_set
        self.ui2_controller.on_clear_set_state = self._clear_ui2_set_state
        self.ui2_controller.run_on_ui = self._run_on_ui

        self.channel_detection_sequence = ChannelDetectionSequence(
            self.root,
            self.status_var,
            self.macro_controller,
            self._get_channel_timeout_ms,
            self._get_channel_watch_interval_ms,
        )

        # Sound
        self.new_channel_sound_player = SoundPlayer(NEW_CHANNEL_SOUND_PATH, volume=0.5)
        self.beep_notifier = BeepNotifier(self.root)

        # Channel segment recorder
        self.channel_segment_recorder = ChannelSegmentRecorder(self._handle_captured_pattern)

        # UI2 automation toggle
        if self.ui2_panel.automation_checkbox:
            self.ui2_panel.automation_checkbox.configure(command=self._on_ui2_automation_toggle)

    def _init_packet_capture(self) -> None:
        """Initialize packet capture."""
        self.packet_manager = PacketCaptureManager(
            on_packet=lambda text: self.root.after(0, self._process_packet_detection, text),
            on_error=lambda msg: self.root.after(0, messagebox.showerror, "패킷 캡쳐 오류", msg),
        )
        self._update_packet_capture_button()
        self.packet_capture_button.configure(command=self._toggle_packet_capture)
        self._poll_devlogic_alert()

    def _setup_hotkeys(self) -> None:
        """Setup global hotkeys."""
        if self._hotkey_listener is not None:
            return
        self._hotkey_listener = keyboard.Listener(on_press=self._on_hotkey_press)
        self._hotkey_listener.start()

    # Helper methods
    def _parse_delay_ms(self, var: tk.StringVar, label: str, fallback: int) -> int:
        """Parse a delay value in milliseconds."""
        try:
            delay_ms = int(float(var.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror(f"{label} 오류", f"{label}를 숫자로 입력하세요.")
            delay_ms = fallback
        if delay_ms < 0:
            messagebox.showerror(f"{label} 오류", f"{label}는 0 이상이어야 합니다.")
            delay_ms = 0
        var.set(str(delay_ms))
        return delay_ms

    def _make_delay_getter(self, var: tk.StringVar, label: str, fallback: int):
        """Create a delay getter function."""
        return lambda: self._parse_delay_ms(var, label, fallback)

    def _parse_positive_int(self, var: tk.StringVar, label: str, fallback: int) -> int:
        """Parse a positive integer value."""
        try:
            value = int(float(var.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror(f"{label} 오류", f"{label}를 숫자로 입력하세요.")
            value = fallback
        if value < 1:
            messagebox.showerror(f"{label} 오류", f"{label}는 1 이상이어야 합니다.")
            value = 1
        var.set(str(value))
        return value

    def _make_positive_int_getter(self, var: tk.StringVar, label: str, fallback: int):
        """Create a positive integer getter function."""
        return lambda: self._parse_positive_int(var, label, fallback)

    def _get_channel_watch_interval_ms(self) -> int:
        """Get channel watch interval in milliseconds."""
        return self._parse_delay_ms(self.channel_watch_interval_var, "채널 감시 주기", DEFAULT_CHANNEL_WATCH_INTERVAL_MS)

    def _get_channel_timeout_ms(self) -> int:
        """Get channel timeout in milliseconds."""
        return self._parse_delay_ms(self.channel_timeout_var, "채널 타임아웃", DEFAULT_CHANNEL_TIMEOUT_MS)

    def _set_status_async(self, message: str) -> None:
        """Set status message asynchronously."""
        self.root.after(0, self.status_var.set, message)

    def _get_capture_listener(self) -> "mouse.Listener | None":
        """Get the current capture listener."""
        return self._capture_listener

    def _clear_capture_listener(self) -> None:
        """Clear the capture listener."""
        self._capture_listener = None

    # Tab switching
    def _bind_tab_activate(self, button: tk.Button, mode: str) -> None:
        """Bind tab activation to a button."""
        def _activate(event: tk.Event | None = None) -> None:
            self._switch_ui(mode)

        button.configure(command=_activate)
        button.bind("<Return>", _activate)
        button.bind("<space>", _activate)

    def _switch_ui(self, mode: str) -> None:
        """Switch to the specified UI mode."""
        target = "2" if mode == "2" else "1"
        self.ui_mode.set(target)
        self.ui1_panel.pack_forget()
        self.ui2_panel.pack_forget()
        if target == "1":
            style_tab_button(self.tab_button_1, active=True)
            style_tab_button(self.tab_button_2, active=False)
            self.ui1_panel.pack(fill="both", expand=True)
        else:
            style_tab_button(self.tab_button_1, active=False)
            style_tab_button(self.tab_button_2, active=True)
            self.ui2_panel.pack(fill="both", expand=True)

    def _run_on_ui(self, mode: str, action) -> None:
        """Run an action on the specified UI."""
        def _runner() -> None:
            self._switch_ui(mode)
            action()
        self.root.after(0, _runner)

    # Pos3 mode handling
    def _set_pos3_mode(self, new_mode: int) -> None:
        """Set the pos3 mode."""
        self.ui1_panel.store_current_pos3_mode_values()
        normalized_mode = ((new_mode - 1) % 6) + 1
        self.pos3_mode_var.set(normalized_mode)
        self.ui1_panel.load_pos3_mode_values()
        self.ui1_panel.update_pos3_mode_label()
        self._apply_newline_for_pos3_mode()
        self.status_var.set(f"선택할 열이 {normalized_mode}열로 변경되었습니다.")

    def _cycle_pos3_mode(self) -> None:
        """Cycle to the next pos3 mode."""
        self._set_pos3_mode(self.pos3_mode_var.get() + 1)

    def _apply_newline_for_pos3_mode(self) -> None:
        """Apply newline setting based on pos3 mode."""
        self.newline_var.set(self.pos3_mode_var.get() == 1)

    def _enforce_newline_mode(self) -> None:
        """Enforce newline mode based on pos3 mode."""
        if self.pos3_mode_var.get() == 1 and not self.newline_var.get():
            self.newline_var.set(True)
        elif self.pos3_mode_var.get() != 1 and self.newline_var.get():
            self.newline_var.set(False)

    # UI2 set management
    def _start_new_ui2_set(self) -> None:
        """Start a new UI2 set."""
        self.ui2_state.set_index += 1
        self.ui2_state.current_set_started_at = time.time()
        self._set_status_async(f"{self.ui2_state.set_index}세트 시작")

    def _finish_ui2_set(self, result: str, note: str | None = None) -> None:
        """Finish the current UI2 set."""
        if self.ui2_state.current_set_started_at is None:
            return
        self.record_window.add_item(
            self.ui2_state.set_index,
            self.ui2_state.current_set_started_at,
            result,
        )
        self.ui2_state.current_set_started_at = None
        suffix = f" - {note}" if note else ""
        self._set_status_async(f"{self.ui2_state.set_index}세트 종료 ({result}){suffix}")

    def _clear_ui2_set_state(self) -> None:
        """Clear the UI2 set state."""
        self.ui2_state.current_set_started_at = None

    def _on_ui2_automation_toggle(self) -> None:
        """Handle UI2 automation toggle."""
        if not self.ui2_automation_var.get():
            self.ui2_controller.stop_automation("자동화 모드: 중지되었습니다.")

    # Windows
    def _show_test_window(self) -> None:
        """Show the test window."""
        self.test_window.show()

    def _show_record_window(self) -> None:
        """Show the record window."""
        self.record_window.show()

    # Packet capture
    def _update_packet_capture_button(self) -> None:
        """Update the packet capture button text."""
        text = "패킷캡쳐 중지" if self.packet_manager.running else "패킷캡쳐 시작"
        self.packet_capture_button.configure(text=text)

    def _start_packet_capture(self) -> None:
        """Start packet capture."""
        if self.packet_manager.running:
            return
        try:
            started = self.packet_manager.start()
        except Exception as exc:
            messagebox.showerror("패킷 캡쳐 오류", f"패킷 캡쳐 시작 실패: {exc}")
            self._update_packet_capture_button()
            return

        if not started:
            messagebox.showwarning("패킷 캡쳐", "패킷 캡쳐를 시작하지 못했습니다. scapy 설치 여부를 확인하세요.")
            self._update_packet_capture_button()
            return

        self.status_var.set("패킷 캡쳐가 시작되었습니다.")
        self._update_packet_capture_button()

    def _stop_packet_capture(self) -> None:
        """Stop packet capture."""
        if not self.packet_manager.running:
            return
        try:
            self.packet_manager.stop()
        except Exception:
            messagebox.showwarning("패킷 캡쳐", "패킷 캡쳐 중지 실패")
        else:
            self.status_var.set("패킷 캡쳐가 중지되었습니다.")
        finally:
            self._update_packet_capture_button()

    def _toggle_packet_capture(self) -> None:
        """Toggle packet capture."""
        if self.packet_manager.running:
            self._stop_packet_capture()
        else:
            self._start_packet_capture()

    # Packet detection
    def _handle_captured_pattern(self, content: str) -> None:
        """Handle a captured channel pattern."""
        detected_at = time.time()
        matches, new_names = self.test_window.add_record(content)
        if matches:
            self.channel_detection_sequence.notify_channel_found(
                detected_at=detected_at,
                is_new=bool(new_names),
            )

    def _process_packet_detection(self, text: str) -> None:
        """Process packet detection."""
        if "DevLogic" in text:
            self.devlogic_state.last_detected_at = time.time()
            (
                self.devlogic_state.last_packet,
                self.devlogic_state.last_is_new_channel,
                devlogic_is_normal_channel,
            ) = format_devlogic_packet(text)

            forced_new_channel = (
                self.ui2_controller.state.active
                and self.ui2_automation_var.get()
                and self.ui2_test_new_channel_var.get()
                and devlogic_is_normal_channel
            )
            effective_new_channel = self.devlogic_state.last_is_new_channel or forced_new_channel
            alert_prefix = "신규채널!!" if self.devlogic_state.last_is_new_channel else "채널 감지"
            self.devlogic_state.last_alert_message = alert_prefix
            self.devlogic_state.last_alert_packet = self.devlogic_state.last_packet
            self.devlogic_packet_var.set(self.devlogic_state.last_packet)

            if self.ui2_controller.state.active and self.ui2_automation_var.get():
                if self.ui2_controller.state.waiting_for_new_channel and effective_new_channel:
                    self.new_channel_sound_player.play_once()
                    self.ui2_controller.state.on_new_channel_found()
                    self.ui2_controller.f4_automation_task.stop()
                    self._finish_ui2_set("성공", "일반 채널 대기")
                    self.beep_notifier.start(3)
                elif self.ui2_controller.state.waiting_for_new_channel and devlogic_is_normal_channel:
                    self._finish_ui2_set("실패", "F4 로직 재실행")
                    self.ui2_controller.restart_f4_logic()
                elif self.ui2_controller.state.waiting_for_normal_channel and devlogic_is_normal_channel:
                    self.ui2_controller.state.on_normal_channel_found()
                    self._set_status_async("일반채널 감지: F5 실행 후 선택창 대기")
                    self.ui2_controller.start_normal_channel_sequence()
            elif not self.ui2_automation_var.get():
                self.ui2_controller.state.waiting_for_new_channel = False
                self.ui2_controller.state.waiting_for_normal_channel = False
                self.ui2_controller.state.waiting_for_selection = False

        if "AdminLevel" in text:
            self.devlogic_state.last_detected_at = time.time()
            self.devlogic_state.last_alert_message = "선택창 감지"
            self.devlogic_state.last_alert_packet = ""
            self.devlogic_packet_var.set("")
            if self.ui2_controller.state.active and self.ui2_controller.state.waiting_for_selection:
                self.ui2_controller.state.on_selection_found()
                self._set_status_async("선택창 감지: F6 실행 중 (F6 재입력 시 중단)")
                self._run_on_ui("2", lambda: self.ui2_controller.run_f6(force_start=True))

        self.channel_segment_recorder.feed(text)

    def _poll_devlogic_alert(self) -> None:
        """Poll and update the devlogic alert display."""
        interval_ms = self._get_channel_watch_interval_ms()
        visible = self.ui_mode.get() == "2" and self.devlogic_state.last_detected_at is not None

        if visible:
            elapsed_sec = max(0, int(time.time() - self.devlogic_state.last_detected_at))
            elapsed_suffix = f"({elapsed_sec}초 전)"
            if self.devlogic_state.last_alert_message and self.devlogic_state.last_alert_packet:
                self.devlogic_alert_var.set(
                    f"{self.devlogic_state.last_alert_message} {self.devlogic_state.last_alert_packet} {elapsed_suffix}"
                )
            elif self.devlogic_state.last_alert_message:
                self.devlogic_alert_var.set(f"{self.devlogic_state.last_alert_message} {elapsed_suffix}")
            else:
                self.devlogic_alert_var.set("")
        else:
            self.devlogic_alert_var.set("")
        self.devlogic_packet_var.set(self.devlogic_state.last_alert_packet if visible else "")
        self.root.after(max(interval_ms, 50), self._poll_devlogic_alert)

    # Hotkeys
    def _on_hotkey_press(self, key: keyboard.Key) -> None:
        """Handle global hotkey press."""
        if key == keyboard.Key.f9:
            self._run_on_ui("1", self.macro_controller.reset_and_run_first)
        elif key == keyboard.Key.f10:
            def _toggle_f10() -> None:
                self._switch_ui("1")
                if self.channel_detection_sequence.running:
                    self.channel_detection_sequence.stop()
                    self.status_var.set("F10 매크로가 종료되었습니다.")
                    self.macro_controller._update_status()
                else:
                    self.channel_detection_sequence.start(self.newline_var.get())
            self.root.after(0, _toggle_f10)
        elif key == keyboard.Key.f11:
            self._run_on_ui("2", self.ui2_controller.run_f4)
        elif key == keyboard.Key.f12:
            def _handle_f12() -> None:
                if self.ui2_controller.state.active and self.ui2_automation_var.get():
                    self.ui2_controller.stop_automation("자동화 모드: F12 입력으로 중단되었습니다.")
                else:
                    self.ui2_controller.run_f6()
            self._run_on_ui("2", _handle_f12)

    # State collection
    def _collect_app_state(self) -> dict:
        """Collect current application state for saving."""
        self.ui1_panel.store_current_pos3_mode_values()
        coordinates: dict[str, dict[str, str]] = {}

        for key, (x_entry, y_entry) in {**self.ui1_panel.entries, **self.ui2_panel.entries}.items():
            coordinates[key] = {"x": x_entry.get(), "y": y_entry.get()}

        for mode in range(1, 7):
            coordinates[f"pos3_{mode}"] = self.pos3_mode_coordinates.get(
                mode,
                {"x": "0", "y": "0"},
            )

        return {
            "coordinates": coordinates,
            "ui_mode": self.ui_mode.get(),
            "pos3_mode": self.pos3_mode_var.get(),
            "delay_f2_before_esc_ms": self.f2_before_esc_var.get(),
            "delay_f2_before_pos1_ms": self.f2_before_pos1_var.get(),
            "delay_f2_before_pos2_ms": self.f2_before_pos2_var.get(),
            "delay_f1_before_pos3_ms": self.f1_before_pos3_var.get(),
            "delay_f1_before_enter_ms": self.f1_before_enter_var.get(),
            "f1_repeat_count": self.f1_repeat_count_var.get(),
            "delay_f1_newline_before_pos4_ms": self.f1_newline_before_pos4_var.get(),
            "delay_f1_newline_before_pos3_ms": self.f1_newline_before_pos3_var.get(),
            "delay_f1_newline_before_enter_ms": self.f1_newline_before_enter_var.get(),
            "delay_f4_between_pos11_pos12_ms": self.f4_between_pos11_pos12_var.get(),
            "delay_f4_before_enter_ms": self.f4_before_enter_var.get(),
            "delay_f5_interval_ms": self.f5_interval_var.get(),
            "delay_f6_interval_ms": self.f6_interval_var.get(),
            "channel_watch_interval_ms": self.channel_watch_interval_var.get(),
            "channel_timeout_ms": self.channel_timeout_var.get(),
            "newline_after_pos2": self.newline_var.get(),
            "esc_click_enabled": self.esc_click_var.get(),
            "ui2_automation_enabled": self.ui2_automation_var.get(),
            "ui2_test_new_channel": self.ui2_test_new_channel_var.get(),
        }

    def _on_close(self) -> None:
        """Handle application close."""
        save_app_state(self._collect_app_state())
        if self._hotkey_listener is not None:
            self._hotkey_listener.stop()
        self.channel_detection_sequence.stop()
        self.ui2_controller.f4_automation_task.stop()
        self.ui2_controller.repeater_f5.stop()
        self.ui2_controller.repeater_f6.stop()
        self.beep_notifier.stop()
        self._stop_packet_capture()
        self.root.destroy()

    def run(self) -> None:
        """Run the application."""
        self.root.mainloop()


def build_gui() -> None:
    """Build and run the GUI (backward compatible entry point)."""
    app = MakrApplication()
    app.run()
