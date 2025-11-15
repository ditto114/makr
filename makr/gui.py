"""Tkinter 기반 매크로 편집 및 실행 GUI."""
from __future__ import annotations

import datetime
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Optional

from PIL import Image, ImageTk

from .execution import ExecutionContext, ExecutionError, execute_macro
from .macro import Macro, MacroNode
from .storage import load_macro, save_macro

try:
    import pyautogui
except Exception:  # pragma: no cover - GUI 환경이 아닐 수 있음
    pyautogui = None  # type: ignore


DEFAULT_CONFIDENCE = 0.8


def _parse_confidence_value(raw: str, *, default: float = DEFAULT_CONFIDENCE) -> float:
    """문자열 형태의 인식 정확도를 부동소수점 값으로 변환한다."""

    text = (raw or "").strip()
    if not text:
        return default
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:  # pragma: no cover - 사용자 입력 오류
        raise ValueError("인식 정확도는 숫자로 입력해야 합니다.") from exc
    if not 0 <= value <= 1:
        raise ValueError("인식 정확도는 0과 1 사이여야 합니다.")
    return value


def _save_captured_image(image: Image.Image) -> Path:
    """캡쳐 이미지를 실행 폴더에 저장하고 경로를 반환한다."""

    base_dir = Path.cwd()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    counter = 0
    while True:
        suffix = f"_{counter}" if counter else ""
        candidate = base_dir / f"capture_{timestamp}{suffix}.png"
        if not candidate.exists():
            image.save(candidate)
            return candidate
        counter += 1


class ImageCaptureOverlay(tk.Toplevel):
    """화면에서 드래그로 영역을 선택하는 오버레이."""

    def __init__(self, master: tk.Widget, screenshot: Image.Image) -> None:
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(background="#000000")
        self._photo = ImageTk.PhotoImage(screenshot)
        self._region: Optional[tuple[int, int, int, int]] = None
        self._start_x = 0
        self._start_y = 0
        width, height = screenshot.size
        self.geometry(f"{width}x{height}+0+0")
        self.canvas = tk.Canvas(self, highlightthickness=0, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self._rect_id: Optional[int] = None
        # 안내 문구
        self.canvas.create_rectangle(10, 10, 420, 50, fill="#000000", outline="")
        self.canvas.create_text(
            20,
            30,
            text="드래그하여 영역 선택, ESC로 취소",
            fill="#ffffff",
            anchor="w",
            font=("Arial", 12, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", self._on_cancel)

    def capture(self) -> Optional[tuple[int, int, int, int]]:
        self.deiconify()
        self.lift()
        self.grab_set()
        self.focus_force()
        self.wait_window(self)
        return self._region

    def _on_press(self, event: tk.Event) -> None:
        self._start_x = int(event.x)
        self._start_y = int(event.y)
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            self._start_x,
            self._start_y,
            self._start_x,
            self._start_y,
            outline="#00ff88",
            width=2,
        )

    def _on_drag(self, event: tk.Event) -> None:
        if self._rect_id is None:
            return
        current_x = int(event.x)
        current_y = int(event.y)
        self.canvas.coords(self._rect_id, self._start_x, self._start_y, current_x, current_y)

    def _on_release(self, event: tk.Event) -> None:
        if self._rect_id is None:
            self._region = None
        else:
            end_x = int(event.x)
            end_y = int(event.y)
            self._region = (
                min(self._start_x, end_x),
                min(self._start_y, end_y),
                max(self._start_x, end_x),
                max(self._start_y, end_y),
            )
        self.grab_release()
        self.destroy()

    def _on_cancel(self, _event: tk.Event | None = None) -> None:
        self._region = None
        self.grab_release()
        self.destroy()


def capture_image_via_drag(parent: tk.Toplevel) -> Optional[Path]:
    """드래그 방식으로 화면을 캡쳐하고 저장한 파일 경로를 반환한다."""

    if pyautogui is None:
        messagebox.showerror("캡쳐 불가", "pyautogui를 사용할 수 없습니다. GUI 환경을 확인하세요.", parent=parent)
        return None

    try:
        parent.grab_release()
    except tk.TclError:  # pragma: no cover - grab이 설정되지 않은 경우
        pass

    screenshot: Optional[Image.Image] = None
    was_withdrawn = False
    try:
        if hasattr(parent, "withdraw"):
            parent.withdraw()
            was_withdrawn = True
            parent.update_idletasks()
        time.sleep(0.2)
        screenshot = pyautogui.screenshot()
    except Exception as exc:  # pragma: no cover - 환경별 스크린샷 오류
        if was_withdrawn:
            parent.deiconify()
        messagebox.showerror("캡쳐 실패", f"화면을 캡쳐할 수 없습니다: {exc}", parent=parent)
        try:
            parent.grab_set()
        except tk.TclError:
            pass
        parent.lift()
        parent.focus_force()
        return None

    overlay = ImageCaptureOverlay(parent, screenshot)
    region = overlay.capture()

    if was_withdrawn:
        parent.deiconify()
    parent.lift()
    try:
        parent.grab_set()
    except tk.TclError:
        pass
    parent.focus_force()

    if not region:
        return None

    left, top, right, bottom = region
    if right <= left or bottom <= top:
        messagebox.showerror("캡쳐 실패", "유효한 영역을 선택하세요.", parent=parent)
        return None

    cropped = screenshot.crop((left, top, right, bottom))
    try:
        return _save_captured_image(cropped)
    except Exception as exc:  # pragma: no cover - 파일 저장 예외
        messagebox.showerror("저장 오류", f"이미지를 저장할 수 없습니다: {exc}", parent=parent)
        return None


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
        self._build_ui()
        self._refresh_tree()

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

        control_frame = ttk.Frame(right_frame)
        control_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        control_frame.columnconfigure(2, weight=1)

        self.run_button = ttk.Button(control_frame, text="매크로 실행", command=self._start_execution)
        self.run_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.stop_button = ttk.Button(control_frame, text="실행 중지", command=self._stop_execution, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(control_frame, text="매크로 새로 만들기", command=self._new_macro).grid(row=0, column=2, sticky="ew", padx=2)

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

    # 선택 및 세부정보 -----------------------------------------------------
    def _on_tree_select(self, _event: tk.Event) -> None:
        selected = self.tree.selection()
        if not selected:
            self._show_details(None)
            return
        node = self._node_map.get(selected[0])
        self._show_details(node)

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

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

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
        self.type_var = tk.StringVar(value=(self.initial.config.get("type") if self.initial else "wait"))
        type_combo = ttk.Combobox(container, textvariable=self.type_var, state="readonly", values=("wait", "image"))
        type_combo.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        type_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_fields())

        # wait fields
        self.wait_frame = ttk.LabelFrame(container, text="대기 조건")
        self.wait_seconds = tk.DoubleVar(value=self.initial.config.get("seconds", 1.0) if self.initial else 1.0)
        ttk.Label(self.wait_frame, text="대기 시간 (초)").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.wait_frame, textvariable=self.wait_seconds).grid(row=0, column=1, sticky="ew")

        # image fields
        self.image_frame = ttk.LabelFrame(container, text="이미지 조건")
        self.image_path = tk.StringVar(value=self.initial.config.get("image_path", "") if self.initial else "")
        ttk.Label(self.image_frame, text="이미지 경로").grid(row=0, column=0, sticky="w")
        path_entry = ttk.Entry(self.image_frame, textvariable=self.image_path)
        path_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(self.image_frame, text="찾기", command=self._browse_image).grid(row=0, column=2, padx=4)
        ttk.Button(self.image_frame, text="캡쳐", command=self._capture_image).grid(row=0, column=3, padx=4)
        self.image_frame.columnconfigure(1, weight=1)
        self.timeout_var = tk.DoubleVar(value=self.initial.config.get("timeout", 30.0) if self.initial else 30.0)
        ttk.Label(self.image_frame, text="타임아웃 (초)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.image_frame, textvariable=self.timeout_var).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.interval_var = tk.DoubleVar(value=self.initial.config.get("interval", 0.5) if self.initial else 0.5)
        ttk.Label(self.image_frame, text="재시도 간격 (초)").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.image_frame, textvariable=self.interval_var).grid(row=2, column=1, sticky="ew", pady=(6, 0))
        initial_confidence = self.initial.config.get("confidence") if self.initial else None
        if initial_confidence in (None, ""):
            default_confidence = f"{DEFAULT_CONFIDENCE}"
        else:
            default_confidence = str(initial_confidence)
        self.confidence_var = tk.StringVar(value=default_confidence)
        ttk.Label(self.image_frame, text="인식 정확도 (0~1, 선택)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.image_frame, textvariable=self.confidence_var).grid(row=3, column=1, sticky="ew", pady=(6, 0))

        self.wait_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.image_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self._update_fields()

    def _update_fields(self) -> None:
        mode = self.type_var.get()
        if mode == "wait":
            self.wait_frame.tkraise()
            self.wait_frame.grid()
            self.image_frame.grid_remove()
        else:
            self.image_frame.tkraise()
            self.image_frame.grid()
            self.wait_frame.grid_remove()

    def _browse_image(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=(("이미지 파일", "*.png;*.jpg;*.jpeg;*.bmp"), ("모든 파일", "*.*")))
        if path:
            self.image_path.set(path)

    def apply(self) -> None:
        title = self.title_var.get().strip() or "조건"
        condition_type = self.type_var.get()
        if condition_type == "wait":
            seconds = float(self.wait_seconds.get())
            if seconds < 0:
                raise ValueError("대기 시간은 0 이상이어야 합니다.")
            config = {"type": "wait", "seconds": seconds}
        else:
            image_path = self.image_path.get().strip()
            if not image_path:
                raise ValueError("이미지 경로를 입력하세요.")
            config = {
                "type": "image",
                "image_path": image_path,
                "timeout": float(self.timeout_var.get()),
                "interval": float(self.interval_var.get()),
            }
            config["confidence"] = _parse_confidence_value(self.confidence_var.get())
        self.result = DialogResult(title=title, config=config)

    def _capture_image(self) -> None:
        path = capture_image_via_drag(self)
        if path:
            self.image_path.set(str(path))


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
        type_combo = ttk.Combobox(container, textvariable=self.type_var, state="readonly", values=("mouse_click", "keyboard", "image_click"))
        type_combo.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        type_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_fields())

        # mouse click frame
        self.mouse_frame = ttk.LabelFrame(container, text="마우스 클릭")
        self.mouse_mode = tk.StringVar(value=self.initial.config.get("mode", "coordinates") if self.initial else "coordinates")
        ttk.Label(self.mouse_frame, text="클릭 방식").grid(row=0, column=0, sticky="w")
        mode_combo = ttk.Combobox(self.mouse_frame, textvariable=self.mouse_mode, state="readonly", values=("coordinates", "image"))
        mode_combo.grid(row=0, column=1, sticky="ew")
        mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_mouse_fields())
        self.mouse_frame.columnconfigure(1, weight=1)

        self.mouse_x = tk.IntVar(value=int(self.initial.config.get("x", 0)) if self.initial else 0)
        self.mouse_y = tk.IntVar(value=int(self.initial.config.get("y", 0)) if self.initial else 0)
        ttk.Label(self.mouse_frame, text="X 좌표").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_x).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(self.mouse_frame, text="Y 좌표").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_y).grid(row=2, column=1, sticky="ew", pady=(6, 0))

        self.mouse_image_path = tk.StringVar(value=self.initial.config.get("image_path", "") if self.initial else "")
        ttk.Label(self.mouse_frame, text="이미지 경로").grid(row=3, column=0, sticky="w", pady=(6, 0))
        image_entry = ttk.Entry(self.mouse_frame, textvariable=self.mouse_image_path)
        image_entry.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(self.mouse_frame, text="찾기", command=self._browse_mouse_image).grid(row=3, column=2, padx=4, pady=(6, 0))
        ttk.Button(self.mouse_frame, text="캡쳐", command=self._capture_mouse_image).grid(row=3, column=3, padx=4, pady=(6, 0))

        self.mouse_clicks = tk.IntVar(value=int(self.initial.config.get("clicks", 1)) if self.initial else 1)
        ttk.Label(self.mouse_frame, text="클릭 횟수").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_clicks).grid(row=4, column=1, sticky="ew", pady=(6, 0))
        self.mouse_interval = tk.DoubleVar(value=float(self.initial.config.get("interval", 0.1)) if self.initial else 0.1)
        ttk.Label(self.mouse_frame, text="클릭 간격 (초)").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_interval).grid(row=5, column=1, sticky="ew", pady=(6, 0))
        self.mouse_button = tk.StringVar(value=self.initial.config.get("button", "left") if self.initial else "left")
        ttk.Label(self.mouse_frame, text="버튼").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(self.mouse_frame, textvariable=self.mouse_button, state="readonly", values=("left", "right", "middle")).grid(row=6, column=1, sticky="ew", pady=(6, 0))
        initial_mouse_conf = self.initial.config.get("confidence") if self.initial else None
        if initial_mouse_conf in (None, ""):
            mouse_default = f"{DEFAULT_CONFIDENCE}"
        else:
            mouse_default = str(initial_mouse_conf)
        self.mouse_confidence = tk.StringVar(value=mouse_default)
        ttk.Label(self.mouse_frame, text="인식 정확도 (이미지)").grid(row=7, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.mouse_frame, textvariable=self.mouse_confidence).grid(row=7, column=1, sticky="ew", pady=(6, 0))

        # keyboard frame
        self.keyboard_frame = ttk.LabelFrame(container, text="키보드 입력")
        self.keyboard_text = tk.StringVar(value=self.initial.config.get("text", "") if self.initial else "")
        ttk.Label(self.keyboard_frame, text="입력 텍스트").grid(row=0, column=0, sticky="nw")
        ttk.Entry(self.keyboard_frame, textvariable=self.keyboard_text).grid(row=0, column=1, sticky="ew")
        self.keyboard_interval = tk.DoubleVar(value=float(self.initial.config.get("interval", 0.05)) if self.initial else 0.05)
        ttk.Label(self.keyboard_frame, text="입력 간격 (초)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.keyboard_frame, textvariable=self.keyboard_interval).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.keyboard_enter = tk.BooleanVar(value=bool(self.initial.config.get("press_enter", False)) if self.initial else False)
        ttk.Checkbutton(self.keyboard_frame, text="입력 후 Enter", variable=self.keyboard_enter).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.keyboard_frame.columnconfigure(1, weight=1)

        # image click frame (특화)
        self.image_click_frame = ttk.LabelFrame(container, text="이미지 클릭")
        self.image_click_path = tk.StringVar(value=self.initial.config.get("image_path", "") if self.initial else "")
        ttk.Label(self.image_click_frame, text="이미지 경로").grid(row=0, column=0, sticky="w")
        img_entry = ttk.Entry(self.image_click_frame, textvariable=self.image_click_path)
        img_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(self.image_click_frame, text="찾기", command=self._browse_image_click).grid(row=0, column=2, padx=4)
        ttk.Button(self.image_click_frame, text="캡쳐", command=self._capture_image_click).grid(row=0, column=3, padx=4)
        initial_click_conf = self.initial.config.get("confidence") if self.initial else None
        if initial_click_conf in (None, ""):
            click_default = f"{DEFAULT_CONFIDENCE}"
        else:
            click_default = str(initial_click_conf)
        self.image_click_confidence = tk.StringVar(value=click_default)
        ttk.Label(self.image_click_frame, text="인식 정확도").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.image_click_frame, textvariable=self.image_click_confidence).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.image_click_clicks = tk.IntVar(value=int(self.initial.config.get("clicks", 1)) if self.initial else 1)
        ttk.Label(self.image_click_frame, text="클릭 횟수").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.image_click_frame, textvariable=self.image_click_clicks).grid(row=2, column=1, sticky="ew", pady=(6, 0))
        self.image_click_interval = tk.DoubleVar(value=float(self.initial.config.get("interval", 0.1)) if self.initial else 0.1)
        ttk.Label(self.image_click_frame, text="클릭 간격 (초)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.image_click_frame, textvariable=self.image_click_interval).grid(row=3, column=1, sticky="ew", pady=(6, 0))
        self.image_click_button = tk.StringVar(value=self.initial.config.get("button", "left") if self.initial else "left")
        ttk.Label(self.image_click_frame, text="버튼").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(self.image_click_frame, textvariable=self.image_click_button, state="readonly", values=("left", "right", "middle")).grid(row=4, column=1, sticky="ew", pady=(6, 0))
        self.image_click_frame.columnconfigure(1, weight=1)

        self.mouse_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.keyboard_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.image_click_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self._update_fields()
        self._update_mouse_fields()

    def _update_fields(self) -> None:
        mode = self.type_var.get()
        self.mouse_frame.grid_remove()
        self.keyboard_frame.grid_remove()
        self.image_click_frame.grid_remove()
        if mode == "mouse_click":
            self.mouse_frame.grid()
        elif mode == "keyboard":
            self.keyboard_frame.grid()
        else:
            self.image_click_frame.grid()

    def _update_mouse_fields(self) -> None:
        mode = self.mouse_mode.get()
        if mode == "coordinates":
            for row in (1, 2):
                for child in self.mouse_frame.grid_slaves(row=row, column=1):
                    child.configure(state="normal")
            for child in (
                self.mouse_frame.grid_slaves(row=3, column=1)
                + self.mouse_frame.grid_slaves(row=3, column=2)
                + self.mouse_frame.grid_slaves(row=3, column=3)
                + self.mouse_frame.grid_slaves(row=7, column=1)
            ):
                child.configure(state="disabled")
        else:
            for row in (1, 2):
                for child in self.mouse_frame.grid_slaves(row=row, column=1):
                    child.configure(state="disabled")
            for child in (
                self.mouse_frame.grid_slaves(row=3, column=1)
                + self.mouse_frame.grid_slaves(row=3, column=2)
                + self.mouse_frame.grid_slaves(row=3, column=3)
                + self.mouse_frame.grid_slaves(row=7, column=1)
            ):
                child.configure(state="normal")

    def _browse_mouse_image(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=(("이미지 파일", "*.png;*.jpg;*.jpeg;*.bmp"), ("모든 파일", "*.*")))
        if path:
            self.mouse_image_path.set(path)

    def _browse_image_click(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=(("이미지 파일", "*.png;*.jpg;*.jpeg;*.bmp"), ("모든 파일", "*.*")))
        if path:
            self.image_click_path.set(path)

    def apply(self) -> None:
        title = self.title_var.get().strip() or "행동"
        action_type = self.type_var.get()
        if action_type == "mouse_click":
            mode = self.mouse_mode.get()
            config = {
                "type": "mouse_click",
                "mode": mode,
                "clicks": int(self.mouse_clicks.get()),
                "interval": float(self.mouse_interval.get()),
                "button": self.mouse_button.get(),
            }
            if mode == "coordinates":
                config.update({"x": int(self.mouse_x.get()), "y": int(self.mouse_y.get())})
            else:
                image_path = self.mouse_image_path.get().strip()
                if not image_path:
                    raise ValueError("이미지 경로를 입력하세요.")
                config.update({"image_path": image_path})
                config["confidence"] = _parse_confidence_value(self.mouse_confidence.get())
        elif action_type == "keyboard":
            config = {
                "type": "keyboard",
                "text": self.keyboard_text.get(),
                "interval": float(self.keyboard_interval.get()),
                "press_enter": bool(self.keyboard_enter.get()),
            }
        else:
            image_path = self.image_click_path.get().strip()
            if not image_path:
                raise ValueError("이미지 경로를 입력하세요.")
            config = {
                "type": "image_click",
                "image_path": image_path,
                "clicks": int(self.image_click_clicks.get()),
                "interval": float(self.image_click_interval.get()),
                "button": self.image_click_button.get(),
            }
            config["confidence"] = _parse_confidence_value(self.image_click_confidence.get())
        self.result = DialogResult(title=title, config=config)

    def _capture_mouse_image(self) -> None:
        path = capture_image_via_drag(self)
        if path:
            self.mouse_image_path.set(str(path))

    def _capture_image_click(self) -> None:
        path = capture_image_via_drag(self)
        if path:
            self.image_click_path.set(str(path))


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
