"""Tkinter 기반 매크로 편집 및 실행 GUI."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from .execution import ExecutionContext, ExecutionError, execute_macro
from .macro import Macro, MacroNode
from .packet import PacketCaptureManager
from .storage import load_macro, save_macro

try:
    import pyautogui
except Exception:  # pragma: no cover - GUI 환경이 아닐 수 있음
    pyautogui = None  # type: ignore


class MacroEditorApp(tk.Tk):
    """매크로 제작 및 실행을 위한 메인 애플리케이션."""

    def __init__(self) -> None:
        super().__init__()
        self.title("makr - 매크로 에디터")
        self.geometry("1100x720")
        self.macro = Macro()
        self._node_map: Dict[str, MacroNode] = {}
        self._execution_thread: Optional[threading.Thread] = None
        self._execution_context: Optional[ExecutionContext] = None
        self._execution_error: Optional[Exception] = None
        self._log_index = 0
        self._dragging_item: Optional[str] = None
        self._drag_target: Optional[str] = None
        self._drag_insert_after = False
        self._drag_moved = False
        self.packet_status_var = tk.StringVar(value="패킷 캡쳐 중지됨")
        self._packet_alerts: List[str] = []
        self._build_ui()
        self._refresh_tree()
        self._init_packet_capture_manager()

    def destroy(self) -> None:
        if hasattr(self, "packet_capture_manager"):
            self.packet_capture_manager.stop()
        super().destroy()

    # UI 구성 ---------------------------------------------------------------
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._create_menu()

        left_frame = ttk.Frame(self, padding=10)
        left_frame.grid(row=0, column=0, sticky="nsew")
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)

        tree_frame = ttk.Frame(left_frame)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_frame, selectmode="browse")
        self.tree.heading("#0", text="매크로 단계")
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click, add="+")
        self.tree.bind("<ButtonPress-1>", self._on_tree_button_press, add="+")
        self.tree.bind("<B1-Motion>", self._on_tree_drag, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_button_release, add="+")

        button_frame = ttk.Frame(left_frame)
        button_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for i in range(3):
            button_frame.columnconfigure(i, weight=1)

        ttk.Button(button_frame, text="조건 추가", command=self._add_condition).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(button_frame, text="행동 추가", command=self._add_action).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(button_frame, text="반복 블럭", command=self._add_loop).grid(row=0, column=2, sticky="ew", padx=2)
        ttk.Button(button_frame, text="선택 편집", command=self._edit_selected).grid(row=1, column=0, sticky="ew", padx=2, pady=(6, 0))
        ttk.Button(button_frame, text="선택 삭제", command=self._delete_selected).grid(row=1, column=1, sticky="ew", padx=2, pady=(6, 0))
        ttk.Button(button_frame, text="로그 초기화", command=self._clear_log).grid(row=1, column=2, sticky="ew", padx=2, pady=(6, 0))

        right_frame = ttk.Frame(self, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)
        right_frame.rowconfigure(2, weight=1)

        detail_group = ttk.LabelFrame(right_frame, text="세부 정보")
        detail_group.grid(row=0, column=0, sticky="nsew")
        detail_group.columnconfigure(0, weight=1)

        self.detail_title = ttk.Label(detail_group, text="선택된 노드가 없습니다.", font=("Arial", 12, "bold"))
        self.detail_title.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))

        self.detail_text = tk.Text(detail_group, height=10, wrap="word", state="disabled")
        self.detail_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        log_group = ttk.LabelFrame(right_frame, text="실행 로그")
        log_group.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        log_group.columnconfigure(0, weight=1)
        log_group.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_group, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        log_scroll = ttk.Scrollbar(log_group, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.grid(row=0, column=1, sticky="ns", pady=8)

        packet_group = ttk.LabelFrame(right_frame, text="패킷 캡쳐")
        packet_group.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        packet_group.columnconfigure(0, weight=1)
        packet_group.columnconfigure(1, weight=1)
        packet_group.rowconfigure(3, weight=1)

        ttk.Label(packet_group, textvariable=self.packet_status_var, foreground="#0a5").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4)
        )

        control_frame = ttk.Frame(packet_group)
        control_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8)
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        self.packet_start_button = ttk.Button(
            control_frame, text="캡쳐 시작", command=self._start_packet_capture
        )
        self.packet_start_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.packet_stop_button = ttk.Button(
            control_frame, text="캡쳐 중지", command=self._stop_packet_capture, state="disabled"
        )
        self.packet_stop_button.grid(row=0, column=1, sticky="ew", padx=2)

        alert_frame = ttk.LabelFrame(packet_group, text="패킷 알림")
        alert_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(6, 0))
        alert_frame.columnconfigure(0, weight=1)
        alert_frame.rowconfigure(1, weight=1)
        self.alert_entry = ttk.Entry(alert_frame)
        self.alert_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=6)
        ttk.Button(alert_frame, text="문자열 등록", command=self._add_alert_keyword).grid(
            row=0, column=1, sticky="ew", pady=6
        )
        self.alert_listbox = tk.Listbox(alert_frame, height=4)
        self.alert_listbox.grid(row=1, column=0, sticky="nsew")
        alert_scroll = ttk.Scrollbar(alert_frame, orient="vertical", command=self.alert_listbox.yview)
        self.alert_listbox.configure(yscrollcommand=alert_scroll.set)
        alert_scroll.grid(row=1, column=1, sticky="ns")
        ttk.Button(alert_frame, text="선택 삭제", command=self._remove_selected_alert).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 6)
        )

        self.packet_text_display = tk.Text(packet_group, wrap="word", height=6, state="disabled")
        self.packet_text_display.grid(row=3, column=0, sticky="nsew", padx=8, pady=8)
        packet_scroll = ttk.Scrollbar(packet_group, orient="vertical", command=self.packet_text_display.yview)
        self.packet_text_display.configure(yscrollcommand=packet_scroll.set)
        packet_scroll.grid(row=3, column=1, sticky="ns", pady=8)

        control_frame = ttk.Frame(right_frame)
        control_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        control_frame.columnconfigure(2, weight=1)

        self.run_button = ttk.Button(control_frame, text="매크로 실행", command=self._start_execution)
        self.run_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.stop_button = ttk.Button(control_frame, text="실행 중지", command=self._stop_execution, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(control_frame, text="매크로 새로 만들기", command=self._new_macro).grid(row=0, column=2, sticky="ew", padx=2)

    def _init_packet_capture_manager(self) -> None:
        self.packet_capture_manager = PacketCaptureManager(
            on_packet=self._threadsafe_on_packet,
            on_alert=self._threadsafe_on_packet_alert,
            on_error=self._threadsafe_on_packet_error,
        )

    def _create_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="새 매크로", command=self._new_macro)
        file_menu.add_command(label="열기...", command=self._load_macro)
        file_menu.add_command(label="저장...", command=self._save_macro)
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self.destroy)
        menubar.add_cascade(label="파일", menu=file_menu)

        self.config(menu=menubar)

    # 트리뷰 업데이트 -------------------------------------------------------
    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._node_map.clear()
        for node in self.macro.nodes:
            self._insert_tree_node(node, "")

    def _insert_tree_node(self, node: MacroNode, parent: str) -> None:
        label = self._format_node(node)
        tree_id = self.tree.insert(parent, "end", text=label, open=True)
        self._node_map[tree_id] = node
        for child in node.children:
            self._insert_tree_node(child, tree_id)

    def _format_node(self, node: MacroNode) -> str:
        prefix = {
            "condition": "[조건]",
            "action": "[행동]",
            "loop": "[반복]",
        }.get(node.kind, "[알수없음]")
        return f"{prefix} {node.title}"

    def _get_node_list_for_parent(self, parent_id: str) -> List[MacroNode]:
        if not parent_id:
            return self.macro.nodes
        parent_node = self._node_map.get(parent_id)
        return parent_node.children if parent_node else self.macro.nodes

    # 선택 및 세부정보 -----------------------------------------------------
    def _on_tree_select(self, _event: tk.Event) -> None:
        selected = self.tree.selection()
        if not selected:
            self._show_details(None)
            return
        node = self._node_map.get(selected[0])
        self._show_details(node)

    def _on_tree_double_click(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        self._edit_selected()

    def _on_tree_button_press(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        self._dragging_item = item if item else None
        self._drag_target = None
        self._drag_insert_after = False
        self._drag_moved = False
        if item:
            self.tree.selection_set(item)

    def _on_tree_drag(self, event: tk.Event) -> None:
        if not self._dragging_item:
            return
        self._drag_moved = True
        target = self.tree.identify_row(event.y)
        if not target:
            self._drag_target = None
            return
        self._drag_target = target
        bbox = self.tree.bbox(target)
        if bbox:
            _, y, _, height = bbox
            self._drag_insert_after = event.y > (y + height / 2)
        else:
            self._drag_insert_after = False
        self.tree.selection_set(target)

    def _on_tree_button_release(self, _event: tk.Event) -> None:
        try:
            if self._dragging_item and self._drag_moved and self._drag_target:
                self._perform_drag_drop()
        finally:
            self._clear_drag_state()

    def _perform_drag_drop(self) -> None:
        if not self._dragging_item or not self._drag_target:
            return
        if self._dragging_item == self._drag_target:
            return
        parent_drag = self.tree.parent(self._dragging_item)
        parent_target = self.tree.parent(self._drag_target)
        if parent_drag != parent_target:
            return
        drag_node = self._node_map.get(self._dragging_item)
        target_node = self._node_map.get(self._drag_target)
        if not drag_node or not target_node:
            return
        node_list = self._get_node_list_for_parent(parent_drag)
        if drag_node not in node_list or target_node not in node_list:
            return
        drag_index = node_list.index(drag_node)
        target_index = node_list.index(target_node)
        node_list.pop(drag_index)
        if self._drag_insert_after:
            if drag_index < target_index:
                insert_index = target_index
            else:
                insert_index = target_index + 1
        else:
            if drag_index < target_index:
                insert_index = max(target_index - 1, 0)
            else:
                insert_index = target_index
        insert_index = max(0, min(insert_index, len(node_list)))
        node_list.insert(insert_index, drag_node)
        self._refresh_tree()
        self._reselect_node(drag_node)

    def _reselect_node(self, node: MacroNode) -> None:
        for tree_id, mapped in self._node_map.items():
            if mapped is node:
                self.tree.selection_set(tree_id)
                self.tree.see(tree_id)
                self._show_details(node)
                break

    def _clear_drag_state(self) -> None:
        self._dragging_item = None
        self._drag_target = None
        self._drag_insert_after = False
        self._drag_moved = False

    def _show_details(self, node: Optional[MacroNode]) -> None:
        if node is None:
            self.detail_title.config(text="선택된 노드가 없습니다.")
            self._set_detail_text("노드를 선택하면 설정이 표시됩니다.")
            return
        self.detail_title.config(text=f"{node.title}")
        description_lines = [f"종류: {node.kind}"]
        for key, value in node.config.items():
            description_lines.append(f"- {key}: {value}")
        if node.kind == "loop":
            description_lines.append(f"포함된 단계: {len(node.children)}개")
        self._set_detail_text("\n".join(description_lines))

    def _set_detail_text(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("end", text)
        self.detail_text.configure(state="disabled")

    # 노드 추가/편집/삭제 --------------------------------------------------
    def _resolve_parent(self) -> Optional[MacroNode]:
        selected = self.tree.selection()
        if not selected:
            return None
        tree_id = selected[0]
        node = self._node_map[tree_id]
        if node.kind == "loop":
            return node
        parent_id = self.tree.parent(tree_id)
        if parent_id:
            return self._node_map[parent_id]
        return None

    def _resolve_selected_node(self) -> Optional[MacroNode]:
        selected = self.tree.selection()
        if not selected:
            return None
        return self._node_map.get(selected[0])

    def _add_condition(self) -> None:
        dialog = ConditionDialog(self, title="조건 추가")
        result = dialog.show()
        if not result:
            return
        node = MacroNode(title=result.title, kind="condition", config=result.config)
        parent = self._resolve_parent()
        self.macro.add_node(node, parent)
        self._refresh_tree()

    def _add_action(self) -> None:
        dialog = ActionDialog(self, title="행동 추가")
        result = dialog.show()
        if not result:
            return
        node = MacroNode(title=result.title, kind="action", config=result.config)
        parent = self._resolve_parent()
        self.macro.add_node(node, parent)
        self._refresh_tree()

    def _add_loop(self) -> None:
        dialog = LoopDialog(self, title="반복 블럭 추가")
        result = dialog.show()
        if not result:
            return
        node = MacroNode(title=result.title, kind="loop", config=result.config)
        parent = self._resolve_parent()
        self.macro.add_node(node, parent)
        self._refresh_tree()

    def _delete_selected(self) -> None:
        node = self._resolve_selected_node()
        if not node:
            return
        if messagebox.askyesno("삭제 확인", f"'{node.title}' 노드를 삭제할까요?"):
            self.macro.remove_node(node)
            self._refresh_tree()
            self._show_details(None)

    def _edit_selected(self) -> None:
        node = self._resolve_selected_node()
        if not node:
            return
        if node.kind == "condition":
            dialog = ConditionDialog(self, title="조건 편집", initial=node)
        elif node.kind == "action":
            dialog = ActionDialog(self, title="행동 편집", initial=node)
        elif node.kind == "loop":
            dialog = LoopDialog(self, title="반복 편집", initial=node)
        else:
            messagebox.showerror("오류", "지원되지 않는 노드 유형입니다.")
            return
        result = dialog.show()
        if not result:
            return
        node.title = result.title
        node.config = result.config
        self._refresh_tree()
        self._show_details(node)

    # 매크로 파일 관리 ----------------------------------------------------
    def _new_macro(self) -> None:
        if messagebox.askyesno("새 매크로", "현재 매크로를 초기화할까요?"):
            self.macro = Macro()
            self._refresh_tree()
            self._show_details(None)
            self._clear_log()

    def _save_macro(self) -> None:
        path = filedialog.asksaveasfilename(
            title="매크로 저장",
            defaultextension=".json",
            filetypes=(("JSON 파일", "*.json"), ("모든 파일", "*.*")),
        )
        if not path:
            return
        save_macro(self.macro, path)
        messagebox.showinfo("저장 완료", "매크로가 저장되었습니다.")

    def _load_macro(self) -> None:
        path = filedialog.askopenfilename(
            title="매크로 열기",
            filetypes=(("JSON 파일", "*.json"), ("모든 파일", "*.*")),
        )
        if not path:
            return
        try:
            self.macro = load_macro(path)
            self._refresh_tree()
            self._show_details(None)
            self._clear_log()
        except Exception as exc:  # pragma: no cover - 파일 오류 시 사용자 피드백
            messagebox.showerror("불러오기 실패", f"매크로를 불러올 수 없습니다:\n{exc}")

    # 로그 및 실행 --------------------------------------------------------
    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._log_index = 0
        self._clear_packet_view()

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self._maybe_update_packet_view(line)

    def _clear_packet_view(self) -> None:
        if not hasattr(self, "packet_text_display"):
            return
        self.packet_text_display.configure(state="normal")
        self.packet_text_display.delete("1.0", "end")
        self.packet_text_display.configure(state="disabled")

    def _maybe_update_packet_view(self, line: str) -> None:
        if "수신 내용:" not in line:
            return
        marker = "수신 내용:"
        marker_index = line.find(marker)
        if marker_index == -1:
            return
        content = line[marker_index + len(marker) :].strip()
        self.packet_text_display.configure(state="normal")
        self.packet_text_display.insert("end", content + "\n")
        self.packet_text_display.see("end")
        self.packet_text_display.configure(state="disabled")

    def _threadsafe_on_packet(self, payload: str) -> None:
        self.after(0, lambda: self._display_captured_packet(payload))

    def _threadsafe_on_packet_alert(self, keyword: str, payload: str) -> None:
        self.after(0, lambda: self._handle_packet_alert(keyword, payload))

    def _threadsafe_on_packet_error(self, message: str) -> None:
        self.after(0, lambda: self._handle_packet_error(message))

    def _display_captured_packet(self, payload: str) -> None:
        if not payload:
            return
        self.packet_text_display.configure(state="normal")
        self.packet_text_display.insert("end", payload + "\n")
        self.packet_text_display.see("end")
        self.packet_text_display.configure(state="disabled")

    def _handle_packet_alert(self, keyword: str, payload: str) -> None:
        self._append_log(f"패킷 알림: '{keyword}' 문자열이 감지되었습니다.")
        self._display_captured_packet(payload)

    def _handle_packet_error(self, message: str) -> None:
        self.packet_status_var.set("패킷 캡쳐 오류")
        self._append_log(f"[패킷 오류] {message}")
        self.packet_start_button.configure(state="normal")
        self.packet_stop_button.configure(state="disabled")

    def _start_packet_capture(self) -> None:
        self.packet_capture_manager.set_alerts(self._packet_alerts)
        self.packet_capture_manager.start()
        if self.packet_capture_manager.running:
            self.packet_status_var.set("패킷 캡쳐 실행 중 (포트 32800)")
            self.packet_start_button.configure(state="disabled")
            self.packet_stop_button.configure(state="normal")
        else:
            self.packet_status_var.set("패킷 캡쳐 시작 실패")

    def _stop_packet_capture(self) -> None:
        self.packet_capture_manager.stop()
        self.packet_status_var.set("패킷 캡쳐 중지됨")
        self.packet_start_button.configure(state="normal")
        self.packet_stop_button.configure(state="disabled")

    def _add_alert_keyword(self) -> None:
        text = self.alert_entry.get().strip()
        if not text:
            messagebox.showinfo("알림 등록", "알림에 사용할 문자열을 입력하세요.")
            return
        if text in self._packet_alerts:
            messagebox.showinfo("알림 등록", "이미 등록된 문자열입니다.")
            return
        self._packet_alerts.append(text)
        self.alert_listbox.insert("end", text)
        self.packet_capture_manager.set_alerts(self._packet_alerts)
        self.alert_entry.delete(0, "end")

    def _remove_selected_alert(self) -> None:
        selection = list(self.alert_listbox.curselection())
        if not selection:
            return
        for index in reversed(selection):
            text = self.alert_listbox.get(index)
            self.alert_listbox.delete(index)
            if text in self._packet_alerts:
                self._packet_alerts.remove(text)
        self.packet_capture_manager.set_alerts(self._packet_alerts)

    def _start_execution(self) -> None:
        if self._execution_thread and self._execution_thread.is_alive():
            messagebox.showwarning("실행 중", "이미 매크로가 실행 중입니다.")
            return
        if not self.macro.nodes:
            messagebox.showinfo("안내", "실행할 매크로 단계가 없습니다.")
            return
        self._clear_log()
        self._execution_context = ExecutionContext()
        self._execution_error = None
        self._execution_thread = threading.Thread(target=self._run_macro_thread, daemon=True)
        self._execution_thread.start()
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.after(200, self._poll_log)

    def _run_macro_thread(self) -> None:
        assert self._execution_context is not None
        try:
            execute_macro(self.macro, self._execution_context)
        except ExecutionError as exc:
            self._execution_error = exc
            self._execution_context.log.add(f"오류 발생: {exc}")
        except Exception as exc:  # pragma: no cover - 예기치 못한 오류
            self._execution_error = exc
            self._execution_context.log.add(f"예기치 못한 오류: {exc}")

    def _poll_log(self) -> None:
        if not self._execution_context:
            return
        lines = self._execution_context.log.lines
        while self._log_index < len(lines):
            self._append_log(lines[self._log_index])
            self._log_index += 1
        if self._execution_thread and self._execution_thread.is_alive():
            self.after(200, self._poll_log)
        else:
            self.run_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            if self._execution_error:
                messagebox.showerror("실행 오류", str(self._execution_error))
            else:
                messagebox.showinfo("실행 완료", "매크로 실행이 완료되었습니다.")

    def _stop_execution(self) -> None:
        if self._execution_context:
            self._execution_context.request_stop()
        self.stop_button.configure(state="disabled")


# ---------------------------------------------------------------------------
@dataclass
class DialogResult:
    title: str
    config: dict
    children: Optional[list] = None


class BaseDialog(tk.Toplevel):
    """공통 다이얼로그 기반 클래스."""

    def __init__(self, master: tk.Widget, title: str) -> None:
        super().__init__(master)
        self.withdraw()
        self.transient(master)
        self.title(title)
        self.result: Optional[DialogResult] = None
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def body(self, container: ttk.Frame) -> None:  # pragma: no cover - 서브클래스 구현
        raise NotImplementedError

    def apply(self) -> None:  # pragma: no cover - 서브클래스 구현
        raise NotImplementedError

    def show(self) -> Optional[DialogResult]:
        container = ttk.Frame(self, padding=10)
        container.grid(row=0, column=0)
        self.body(container)
        button_frame = ttk.Frame(container)
        button_frame.grid(row=999, column=0, columnspan=2, pady=(10, 0), sticky="ew")
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        ttk.Button(button_frame, text="확인", command=self._on_ok).grid(row=0, column=0, padx=4)
        ttk.Button(button_frame, text="취소", command=self._on_cancel).grid(row=0, column=1, padx=4)
        self.update_idletasks()
        self._center_over_master()
        self.deiconify()
        self.grab_set()
        self.lift()
        self.focus_force()
        self.wait_window(self)
        return self.result

    def _on_ok(self) -> None:
        try:
            self.apply()
        except ValueError as exc:
            messagebox.showerror("입력 오류", str(exc), parent=self)
            return
        self.grab_release()
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()

    def _center_over_master(self) -> None:
        master_widget = self.master if isinstance(self.master, tk.Misc) else None
        if master_widget is None:
            master_widget = self.winfo_toplevel()
        try:
            master_widget.update_idletasks()
            master_width = master_widget.winfo_width()
            master_height = master_widget.winfo_height()
            master_x = master_widget.winfo_rootx()
            master_y = master_widget.winfo_rooty()
        except tk.TclError:
            master_width = master_height = 0
            master_x = master_y = 0

        width = self.winfo_width()
        height = self.winfo_height()
        if not master_width or not master_height:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            x = int((screen_width - width) / 2)
            y = int((screen_height - height) / 2)
        else:
            x = master_x + max((master_width - width) // 2, 0)
            y = master_y + max((master_height - height) // 2, 0)
        self.geometry(f"+{x}+{y}")


class ConditionDialog(BaseDialog):
    def __init__(self, master: tk.Widget, title: str, initial: Optional[MacroNode] = None) -> None:
        self.initial = initial
        super().__init__(master, title)

    def body(self, container: ttk.Frame) -> None:
        container.columnconfigure(1, weight=1)
        ttk.Label(container, text="이름").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar(value=self.initial.title if self.initial else "조건")
        ttk.Entry(container, textvariable=self.title_var).grid(row=0, column=1, sticky="ew")

        ttk.Label(container, text="조건 유형").grid(row=1, column=0, sticky="w", pady=(8, 0))
        initial_type = self.initial.config.get("type") if self.initial else "wait"
        if initial_type not in {"wait"}:
            initial_type = "wait"
        self.type_var = tk.StringVar(value=initial_type)
        type_combo = ttk.Combobox(
            container,
            textvariable=self.type_var,
            state="readonly",
            values=("wait",),
        )
        type_combo.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        type_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_fields())

        self.wait_frame = ttk.LabelFrame(container, text="대기 조건")
        self.wait_seconds = tk.DoubleVar(value=self.initial.config.get("seconds", 1.0) if self.initial else 1.0)
        ttk.Label(self.wait_frame, text="대기 시간 (초)").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.wait_frame, textvariable=self.wait_seconds).grid(row=0, column=1, sticky="ew")

        self.wait_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self._update_fields()

    def _update_fields(self) -> None:
        mode = self.type_var.get()
        self.wait_frame.grid_remove()
        if mode == "wait":
            self.wait_frame.grid()

    def apply(self) -> None:
        title = self.title_var.get().strip() or "조건"
        condition_type = self.type_var.get()
        if condition_type == "wait":
            seconds = float(self.wait_seconds.get())
            if seconds < 0:
                raise ValueError("대기 시간은 0 이상이어야 합니다.")
            config = {"type": "wait", "seconds": seconds}
        else:
            raise ValueError("지원되지 않는 조건 유형입니다.")
        self.result = DialogResult(title=title, config=config)


class ActionDialog(BaseDialog):
    def __init__(self, master: tk.Widget, title: str, initial: Optional[MacroNode] = None) -> None:
        self.initial = initial
        super().__init__(master, title)

    def body(self, container: ttk.Frame) -> None:
        container.columnconfigure(1, weight=1)
        ttk.Label(container, text="이름").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar(value=self.initial.title if self.initial else "행동")
        ttk.Entry(container, textvariable=self.title_var).grid(row=0, column=1, sticky="ew")

        ttk.Label(container, text="행동 유형").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.type_var = tk.StringVar(value=(self.initial.config.get("type") if self.initial else "mouse_click"))
        type_combo = ttk.Combobox(container, textvariable=self.type_var, state="readonly", values=("mouse_click", "keyboard"))
        type_combo.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        type_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_fields())

        self.mouse_frame = ttk.LabelFrame(container, text="마우스 클릭")
        self.mouse_x = tk.IntVar(value=int(self.initial.config.get("x", 0)) if self.initial else 0)
        self.mouse_y = tk.IntVar(value=int(self.initial.config.get("y", 0)) if self.initial else 0)
        self.mouse_clicks = tk.IntVar(value=int(self.initial.config.get("clicks", 1)) if self.initial else 1)
        self.mouse_interval = tk.DoubleVar(value=float(self.initial.config.get("interval", 0.1)) if self.initial else 0.1)
        self.mouse_button = tk.StringVar(value=self.initial.config.get("button", "left") if self.initial else "left")
        ttk.Label(self.mouse_frame, text="X 좌표").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_x).grid(row=0, column=1, sticky="ew")
        ttk.Label(self.mouse_frame, text="Y 좌표").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_y).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(self.mouse_frame, text="클릭 횟수").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_clicks).grid(row=2, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(self.mouse_frame, text="클릭 간격 (초)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_interval).grid(row=3, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(self.mouse_frame, text="버튼").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(self.mouse_frame, textvariable=self.mouse_button, state="readonly", values=("left", "right", "middle"), width=10).grid(row=4, column=1, sticky="w", pady=(6, 0))
        self.mouse_frame.columnconfigure(1, weight=1)

        self.keyboard_frame = ttk.LabelFrame(container, text="키보드 입력")
        self.keyboard_text = tk.StringVar(value=self.initial.config.get("text", "") if self.initial else "")
        self.keyboard_interval = tk.DoubleVar(value=float(self.initial.config.get("interval", 0.05)) if self.initial else 0.05)
        self.keyboard_enter = tk.BooleanVar(value=bool(self.initial.config.get("press_enter", False)) if self.initial else False)
        ttk.Label(self.keyboard_frame, text="입력 텍스트").grid(row=0, column=0, sticky="nw")
        ttk.Entry(self.keyboard_frame, textvariable=self.keyboard_text).grid(row=0, column=1, sticky="ew")
        ttk.Label(self.keyboard_frame, text="입력 간격 (초)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.keyboard_frame, textvariable=self.keyboard_interval).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(self.keyboard_frame, text="입력 후 Enter", variable=self.keyboard_enter).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.keyboard_frame.columnconfigure(1, weight=1)

        self.mouse_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.keyboard_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self._update_fields()

    def _update_fields(self) -> None:
        mode = self.type_var.get()
        self.mouse_frame.grid_remove()
        self.keyboard_frame.grid_remove()
        if mode == "mouse_click":
            self.mouse_frame.grid()
        else:
            self.keyboard_frame.grid()

    def apply(self) -> None:
        title = self.title_var.get().strip() or "행동"
        action_type = self.type_var.get()
        if action_type == "mouse_click":
            config = {
                "type": "mouse_click",
                "x": int(self.mouse_x.get()),
                "y": int(self.mouse_y.get()),
                "clicks": int(self.mouse_clicks.get()),
                "interval": float(self.mouse_interval.get()),
                "button": self.mouse_button.get(),
            }
        else:
            config = {
                "type": "keyboard",
                "text": self.keyboard_text.get(),
                "interval": float(self.keyboard_interval.get()),
                "press_enter": bool(self.keyboard_enter.get()),
            }
        self.result = DialogResult(title=title, config=config)


class LoopDialog(BaseDialog):
    def __init__(self, master: tk.Widget, title: str, initial: Optional[MacroNode] = None) -> None:
        self.initial = initial
        super().__init__(master, title)

    def body(self, container: ttk.Frame) -> None:
        container.columnconfigure(1, weight=1)
        ttk.Label(container, text="이름").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar(value=self.initial.title if self.initial else "반복")
        ttk.Entry(container, textvariable=self.title_var).grid(row=0, column=1, sticky="ew")

        ttk.Label(container, text="반복 횟수").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.repeat_var = tk.IntVar(value=int(self.initial.config.get("repeat", 2)) if self.initial else 2)
        ttk.Entry(container, textvariable=self.repeat_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))

    def apply(self) -> None:
        title = self.title_var.get().strip() or "반복"
        repeat = int(self.repeat_var.get())
        if repeat <= 0:
            raise ValueError("반복 횟수는 1 이상이어야 합니다.")
        config = {"repeat": repeat}
        self.result = DialogResult(title=title, config=config)


def main() -> None:
    app = MacroEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
