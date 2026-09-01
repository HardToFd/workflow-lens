#!/usr/bin/env python3
"""Native Windows desktop GUI for the Markdown workflow."""

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Dict, List, Optional

from server import ApiError, STAGES, WorkflowWorkspace, default_workspace


INK = "#18221f"
MUTED = "#66716d"
PAPER = "#f4f2ec"
PANEL = "#fffefa"
PANEL_ALT = "#faf8f3"
LINE = "#dedbd1"
ACCENT = "#0f766e"
ACCENT_DARK = "#075d56"
ACCENT_SOFT = "#d9efeb"
WARM = "#e86a33"
WARM_SOFT = "#fae7dc"
DANGER = "#b42318"
CAPABILITY_LABELS = {
    "自动检测": "自动检测｜推荐，按代理实际能力选择",
    "档位1": "档位 1｜全能力自动执行",
    "档位2": "档位 2｜文件可读写，命令人工执行",
    "档位3": "档位 3｜纯对话，全部人工中继",
}


class WorkflowDesk:
    def __init__(self, root: tk.Tk, app: WorkflowWorkspace):
        self.root = root
        self.app = app
        self.tasks = []  # type: List[Dict[str, Any]]
        self.filtered_tasks = []  # type: List[Dict[str, Any]]
        self.current_id = None  # type: Optional[str]
        self.current_artifact = None  # type: Optional[str]
        self._refresh_after_id = None  # type: Optional[str]

        self.search = tk.StringVar()
        self.title = tk.StringVar(value="请选择需求")
        self.task_id = tk.StringVar(value="")
        self.phase = tk.StringVar(value="-")
        self.status = tk.StringVar(value="未开始")
        self.task_count = tk.StringVar(value="0 个需求")
        self.artifact_title = tk.StringVar(value="产物")
        self.prompt = tk.StringVar(value="")
        self.artifact_tabs = {}  # type: Dict[str, ttk.Button]
        self.stage_labels = []  # type: List[tk.Label]

        self._configure_window()
        self._build_layout()
        self.search.trace_add("write", lambda *_: self._render_task_list())
        self.refresh_tasks()
        self._schedule_auto_refresh()

    def _configure_window(self) -> None:
        self.root.title("Workflow Desk V2 — " + self.app.root.name)
        self.root.geometry("1380x860")
        self.root.minsize(1060, 680)
        self.root.configure(background=PAPER)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 9))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=PAPER)
        style.configure("Header.TFrame", background=PANEL)
        style.configure("Card.TFrame", background=PANEL, bordercolor=LINE, borderwidth=1, relief="solid")
        style.configure("TLabel", background=PAPER, foreground=INK)
        style.configure("HeaderTitle.TLabel", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("HeaderSub.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 21, "bold"))
        style.configure("Eyebrow.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 8, "bold"))
        style.configure("Section.TLabel", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Mono.TLabel", background=PANEL, foreground=MUTED, font=("Consolas", 9))
        style.configure("TButton", background=PANEL, foreground=INK, bordercolor=LINE, padding=(12, 8), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("TButton", background=[("active", PANEL_ALT), ("pressed", "#eceae3")], bordercolor=[("focus", ACCENT)])
        style.configure("Primary.TButton", background=INK, foreground="white", bordercolor=INK, padding=(14, 9))
        style.map("Primary.TButton", background=[("active", "#2a3733"), ("pressed", "#101714")], foreground=[("disabled", "#b8bfbc")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT, padding=(14, 9))
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("pressed", "#064e49")])
        style.configure("Action.TButton", background=WARM_SOFT, foreground="#75401f", bordercolor="#efc6ad", padding=(11, 9))
        style.map("Action.TButton", background=[("active", "#f7d9c8")])
        style.configure("Tab.TButton", background=PANEL, foreground=MUTED, bordercolor=LINE, padding=(4, 6), font=("Microsoft YaHei UI", 8, "bold"))
        style.configure("TabActive.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT, padding=(4, 6), font=("Microsoft YaHei UI", 8, "bold"))
        style.map("TabActive.TButton", background=[("active", ACCENT_DARK)])
        style.configure("TEntry", fieldbackground=PANEL, foreground=INK, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=(9, 8))
        style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=INK, bordercolor=LINE, padding=(8, 6))
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK, bordercolor=LINE, rowheight=32, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background=PANEL_ALT, foreground=MUTED, bordercolor=LINE, padding=(9, 8), font=("Microsoft YaHei UI", 8, "bold"))
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", INK)])
        style.configure("TPanedwindow", background=PAPER)
        style.configure("Sash", sashthickness=8, background=PAPER)
        style.configure("TScrollbar", background="#d4d1c8", troughcolor=PANEL, bordercolor=PANEL, arrowcolor=MUTED)
        style.configure("TNotebook", background=PAPER, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_ALT, foreground=MUTED, padding=(16, 9), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", PANEL), ("active", ACCENT_SOFT)], foreground=[("selected", INK)])
        style.configure("Panel.TCheckbutton", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 9))
        style.map("Panel.TCheckbutton", background=[("active", PANEL)])

    def _build_layout(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 13))
        header.pack(fill="x")

        brand = ttk.Frame(header, style="Header.TFrame")
        brand.pack(side="left")
        tk.Label(
            brand,
            text="WF",
            bg=INK,
            fg="white",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=10,
            pady=8,
            borderwidth=0,
        ).pack(side="left", padx=(0, 11))
        brand_text = ttk.Frame(brand, style="Header.TFrame")
        brand_text.pack(side="left")
        ttk.Label(brand_text, text="Workflow Desk", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(brand_text, text="Markdown 工作流操作台", style="HeaderSub.TLabel").pack(anchor="w")

        controls = ttk.Frame(header, style="Header.TFrame")
        controls.pack(side="right")
        ttk.Label(controls, text=str(self.app.root), style="HeaderSub.TLabel").pack(side="left", padx=(0, 14))
        ttk.Button(controls, text="设置", command=self.open_settings).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="刷新", command=self.refresh_tasks).pack(side="left")
        ttk.Button(controls, text="新建需求", command=self.open_new_prd, style="Primary.TButton").pack(side="left", padx=(8, 0))

        panes = ttk.Panedwindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=16, pady=16)

        left = ttk.Frame(panes, width=265, padding=16, style="Card.TFrame")
        center = ttk.Frame(panes, padding=20, style="Card.TFrame")
        right = ttk.Frame(panes, width=310, padding=16, style="Card.TFrame")
        panes.add(left, weight=1)
        panes.add(center, weight=4)
        panes.add(right, weight=1)

        left_head = ttk.Frame(left, style="Header.TFrame")
        left_head.pack(fill="x")
        ttk.Label(left_head, text="需求", style="Section.TLabel").pack(side="left")
        ttk.Label(left_head, textvariable=self.task_count, style="Muted.TLabel").pack(side="right")
        ttk.Label(left, text="搜索需求", style="Muted.TLabel").pack(anchor="w", pady=(16, 5))
        ttk.Entry(left, textvariable=self.search).pack(fill="x", pady=(0, 12))
        list_frame = ttk.Frame(left, style="Header.TFrame")
        list_frame.pack(fill="both", expand=True)
        self.task_list = tk.Listbox(
            list_frame,
            width=28,
            activestyle="none",
            exportselection=False,
            bg=PANEL,
            fg=INK,
            selectbackground=ACCENT_SOFT,
            selectforeground=INK,
            font=("Microsoft YaHei UI", 9),
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            selectborderwidth=0,
        )
        task_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.task_list.yview)
        self.task_list.configure(yscrollcommand=task_scroll.set)
        self.task_list.pack(side="left", fill="both", expand=True)
        task_scroll.pack(side="right", fill="y")
        self.task_list.bind("<<ListboxSelect>>", self._on_task_selected)

        ttk.Label(center, text="当前需求", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(center, textvariable=self.title, style="Title.TLabel").pack(anchor="w", pady=(3, 7))
        meta = ttk.Frame(center, style="Header.TFrame")
        meta.pack(fill="x")
        ttk.Label(meta, textvariable=self.task_id, style="Mono.TLabel").pack(side="left", padx=(0, 10))
        self.phase_badge = tk.Label(meta, textvariable=self.phase, bg=ACCENT_SOFT, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 8, "bold"), padx=9, pady=4, borderwidth=0)
        self.phase_badge.pack(side="left", padx=(0, 7))
        self.status_badge = tk.Label(meta, textvariable=self.status, bg="#eceae3", fg=INK, font=("Microsoft YaHei UI", 8, "bold"), padx=9, pady=4, borderwidth=0)
        self.status_badge.pack(side="left")

        stage_frame = tk.Frame(center, bg=PANEL, borderwidth=0)
        stage_frame.pack(fill="x", pady=(16, 18))
        for index, stage in enumerate(STAGES):
            stage_frame.columnconfigure(index, weight=1)
            label = tk.Label(
                stage_frame,
                text=stage,
                bg=PANEL_ALT,
                fg=MUTED,
                font=("Microsoft YaHei UI", 8, "bold"),
                padx=7,
                pady=7,
                highlightthickness=1,
                highlightbackground=LINE,
            )
            label.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 3, 0 if index == 5 else 3))
            self.stage_labels.append(label)

        ttk.Separator(center).pack(fill="x", pady=(0, 16))
        project_head = ttk.Frame(center, style="Header.TFrame")
        project_head.pack(fill="x")
        ttk.Label(project_head, text="项目状态", style="Section.TLabel").pack(side="left")
        ttk.Label(project_head, text="阶段、分支与闸口概览", style="Muted.TLabel").pack(side="right")
        self.projects = ttk.Treeview(
            center,
            columns=("project", "phase", "branch", "gate", "status"),
            show="headings",
            height=4,
        )
        for key, label, width in (
            ("project", "项目", 160),
            ("phase", "阶段", 70),
            ("branch", "分支", 180),
            ("gate", "闸口 C", 120),
            ("status", "状态", 120),
        ):
            self.projects.heading(key, text=label)
            self.projects.column(key, width=width, minwidth=60, stretch=True)
        self.projects.pack(fill="x", pady=(8, 18))

        artifact_header = ttk.Frame(center, style="Header.TFrame")
        artifact_header.pack(fill="x")
        ttk.Label(artifact_header, textvariable=self.artifact_title, style="Section.TLabel").pack(side="left")
        self.artifact_buttons = ttk.Frame(center, style="Header.TFrame")
        self.artifact_buttons.pack(fill="x", pady=(8, 0))
        self.artifact_text = scrolledtext.ScrolledText(
            center,
            wrap="word",
            font=("Consolas", 10),
            bg=PANEL,
            fg="#27322f",
            insertbackground=INK,
            selectbackground=ACCENT_SOFT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=LINE,
            padx=16,
            pady=14,
        )
        self.artifact_text.pack(fill="both", expand=True, pady=(7, 0))
        self.artifact_text.configure(state="disabled")

        ttk.Label(right, text="待人工动作", style="Section.TLabel").pack(anchor="w")
        self.actions = ttk.Frame(right, style="Header.TFrame")
        self.actions.pack(fill="x", pady=(8, 16))

        ttk.Separator(right).pack(fill="x", pady=(0, 16))

        ttk.Label(right, text="继续执行", style="Section.TLabel").pack(anchor="w")
        ttk.Label(right, textvariable=self.prompt, wraplength=270, justify="left", style="Muted.TLabel").pack(fill="x", pady=(8, 7))
        ttk.Button(right, text="复制提示词", command=self.copy_prompt).pack(anchor="w", pady=(0, 16))

        ttk.Separator(right).pack(fill="x", pady=(0, 16))

        ttk.Label(right, text="Git 状态", style="Section.TLabel").pack(anchor="w")
        self.git_text = scrolledtext.ScrolledText(right, width=36, height=8, wrap="word", font=("Consolas", 8), bg=PANEL_ALT, fg="#39433f", relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=LINE, padx=9, pady=8)
        self.git_text.pack(fill="both", expand=True, pady=(8, 16))
        self.git_text.configure(state="disabled")

        ttk.Label(right, text="本次操作日志", style="Section.TLabel").pack(anchor="w")
        self.log_text = scrolledtext.ScrolledText(right, width=36, height=6, wrap="word", font=("Consolas", 8), bg=PANEL_ALT, fg="#39433f", relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=LINE, padx=9, pady=8)
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text.configure(state="disabled")

    @staticmethod
    def _set_text(widget: scrolledtext.ScrolledText, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    @staticmethod
    def _style_input(widget: tk.Text) -> None:
        widget.configure(
            bg=PANEL,
            fg=INK,
            insertbackground=INK,
            selectbackground=ACCENT_SOFT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
            padx=9,
            pady=8,
        )

    def _show_error(self, error: Exception) -> None:
        message = error.message if isinstance(error, ApiError) else str(error)
        messagebox.showerror("Workflow Desk", message, parent=self.root)

    def refresh_tasks(self, select_id: Optional[str] = None) -> None:
        try:
            self.tasks = self.app.list_tasks()
            target = select_id or self.current_id
            self._render_task_list(target)
        except Exception as error:
            self._show_error(error)

    def _filtered(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        query = self.search.get().strip().lower()
        return [
            task for task in tasks if not query or query in task["id"].lower() or query in task["title"].lower()
        ]

    @staticmethod
    def _task_signature(tasks: List[Dict[str, Any]]) -> tuple:
        return tuple(
            sorted(
                (
                    task["id"],
                    task["title"],
                    task["phase"],
                    task["status"],
                    task.get("project_count", 0),
                    task.get("revision") or task.get("updated_at", ""),
                )
                for task in tasks
            )
        )

    def _render_task_list(
        self,
        select_id: Optional[str] = None,
        preferred_artifact: Optional[str] = None,
        refresh_aux: bool = True,
        prepared: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.filtered_tasks = self._filtered(self.tasks)
        self.task_count.set("{} 个需求".format(len(self.filtered_tasks)))
        self.task_list.delete(0, "end")
        for task in self.filtered_tasks:
            self.task_list.insert("end", "{}  ·  {}".format(task["title"], task["phase"]))
        if not self.filtered_tasks:
            self._clear_task()
            return
        index = next((i for i, task in enumerate(self.filtered_tasks) if task["id"] == select_id), 0)
        self.task_list.selection_set(index)
        self.task_list.see(index)
        task_id = self.filtered_tasks[index]["id"]
        if prepared is None:
            self.load_task(task_id, preferred_artifact, refresh_aux)
        else:
            self._display_task(task_id, prepared, refresh_aux)

    def _on_task_selected(self, _event=None) -> None:
        selection = self.task_list.curselection()
        if selection:
            self.load_task(self.filtered_tasks[selection[0]]["id"])

    def _prepare_task(self, task_id: str, preferred_artifact: Optional[str] = None) -> Dict[str, Any]:
        detail = self.app.task_detail(task_id)
        available = [
            artifact
            for artifact in detail["artifacts"]
            if artifact["exists"] and artifact.get("readable", True)
        ]
        selected = None
        artifact = None
        if available:
            preferred = next((item for item in available if item["name"] == preferred_artifact), None)
            state = next((item for item in available if item["name"] == "state.md"), None)
            ordered = []
            for item in (preferred, state) + tuple(available):
                if item is not None and item not in ordered:
                    ordered.append(item)
            for item in ordered:
                try:
                    artifact = self.app.read_artifact(task_id, item["name"])
                    selected = item
                    break
                except Exception:
                    continue
        return {"detail": detail, "available": available, "selected": selected, "artifact": artifact}

    def load_task(
        self,
        task_id: str,
        preferred_artifact: Optional[str] = None,
        refresh_aux: bool = True,
        show_errors: bool = True,
    ) -> None:
        try:
            self._display_task(task_id, self._prepare_task(task_id, preferred_artifact), refresh_aux)
        except Exception as error:
            if show_errors:
                self._show_error(error)

    def _display_task(self, task_id: str, prepared: Dict[str, Any], refresh_aux: bool) -> None:
        detail = prepared["detail"]
        self.current_id = task_id
        self.title.set(detail["title"])
        top = detail["top"]
        phase = top.get("phase", "未开始")
        status = top.get("status", "仅有 PRD")
        self.task_id.set(task_id)
        self.phase.set(phase)
        self.status.set(status)
        self._update_stage_rail(phase)
        self._update_status_badge(status)
        self.prompt.set(detail["run_prompt"])

        self.projects.delete(*self.projects.get_children())
        for project in detail["projects"]:
            self.projects.insert(
                "",
                "end",
                values=(
                    project.get("project", ""),
                    project.get("phase", ""),
                    project.get("branch", ""),
                    project.get("gate_c", ""),
                    project.get("row_status", ""),
                ),
            )

        for child in self.artifact_buttons.winfo_children():
            child.destroy()
        self.artifact_tabs.clear()
        for item in prepared["available"]:
            button = ttk.Button(
                self.artifact_buttons,
                text=item["label"],
                width=6,
                style="Tab.TButton",
                command=lambda name=item["name"]: self.show_artifact(name),
            )
            button.pack(side="left", padx=(0, 4))
            self.artifact_tabs[item["name"]] = button
        selected = prepared["selected"]
        if selected:
            artifact = prepared["artifact"]
            self.current_artifact = selected["name"]
            self.artifact_title.set(artifact["label"])
            for tab_name, button in self.artifact_tabs.items():
                button.configure(style="TabActive.TButton" if tab_name == self.current_artifact else "Tab.TButton")
            self._set_text(self.artifact_text, artifact["content"])
        else:
            self.current_artifact = None
            self.artifact_title.set("产物")
            self._set_text(self.artifact_text, "暂无产物")

        self._render_actions(detail["actions"])
        if refresh_aux:
            self.refresh_side_panels()

    def _clear_task(self) -> None:
        self.current_id = None
        self.current_artifact = None
        self.title.set("请选择需求")
        self.task_id.set("")
        self.phase.set("-")
        self.status.set("未开始")
        self.prompt.set("")
        self._update_stage_rail("-")
        self._update_status_badge("未开始")
        self.projects.delete(*self.projects.get_children())
        for child in self.artifact_buttons.winfo_children():
            child.destroy()
        self.artifact_tabs.clear()
        self.artifact_title.set("产物")
        self._set_text(self.artifact_text, "暂无产物")
        self._render_actions([])

    def _schedule_auto_refresh(self) -> None:
        if self._refresh_after_id is None:
            self._refresh_after_id = self.root.after(3000, self._auto_refresh)

    def _auto_refresh(self) -> None:
        self._refresh_after_id = None
        try:
            if self.root.grab_current() is not None:
                return
            tasks = self.app.list_tasks()
            if self._task_signature(tasks) == self._task_signature(self.tasks):
                return
            filtered = self._filtered(tasks)
            prepared = None
            target = self.current_id
            artifact = self.current_artifact
            if filtered:
                task = next((item for item in filtered if item["id"] == target), filtered[0])
                target = task["id"]
                prepared = self._prepare_task(target, artifact)
            self.tasks = tasks
            self._render_task_list(target, artifact, refresh_aux=False, prepared=prepared)
        except Exception:
            pass
        finally:
            try:
                if self.root.winfo_exists():
                    self._schedule_auto_refresh()
            except tk.TclError:
                pass

    def _close(self) -> None:
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        self.root.destroy()

    def _update_stage_rail(self, phase: str) -> None:
        stages = STAGES
        current = stages.index(phase) if phase in stages else -1
        for index, label in enumerate(self.stage_labels):
            if index < current:
                label.configure(bg=ACCENT_SOFT, fg=ACCENT_DARK, highlightbackground="#a8d4cd")
            elif index == current:
                label.configure(bg=INK, fg="white", highlightbackground=INK)
            else:
                label.configure(bg=PANEL_ALT, fg=MUTED, highlightbackground=LINE)

    def _update_status_badge(self, status: str) -> None:
        if "BLOCKED" in status:
            colors = ("#fee4e2", DANGER)
        elif "等待" in status:
            colors = (WARM_SOFT, "#75401f")
        elif "完成" in status:
            colors = (ACCENT_SOFT, ACCENT_DARK)
        else:
            colors = ("#eceae3", INK)
        self.status_badge.configure(bg=colors[0], fg=colors[1])

    def show_artifact(self, name: str) -> None:
        if not self.current_id:
            return
        try:
            artifact = self.app.read_artifact(self.current_id, name)
            self.current_artifact = name
            self.artifact_title.set(artifact["label"])
            for tab_name, button in self.artifact_tabs.items():
                button.configure(style="TabActive.TButton" if tab_name == name else "Tab.TButton")
            self._set_text(self.artifact_text, artifact["content"])
        except Exception as error:
            self._show_error(error)

    def _render_actions(self, actions: List[Dict[str, Any]]) -> None:
        for child in self.actions.winfo_children():
            child.destroy()
        if not actions:
            ttk.Label(self.actions, text="当前无需人工动作", style="Muted.TLabel").pack(anchor="w")
            return
        for action in actions:
            label = action["label"]
            if action.get("project"):
                label += " · " + action["project"]
            ttk.Button(self.actions, text=label, style="Action.TButton", command=lambda value=action: self.open_gate(value)).pack(fill="x", pady=(0, 7))

    def refresh_side_panels(self) -> None:
        git = self.app.git_status()
        self._set_text(self.git_text, git.get("output", "") or "暂无 Git 输出")
        logs = self.app.logs()
        content = "\n".join("{}  {}  {}".format(item["time"], item["task_id"], item["detail"]) for item in logs)
        self._set_text(self.log_text, content or "暂无写操作")

    def copy_prompt(self) -> None:
        value = self.prompt.get()
        if value:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)

    def open_settings(self) -> None:
        try:
            snapshot = self.app.settings()
            SettingsDialog(self.root, self.app, snapshot, self.refresh_side_panels)
        except Exception as error:
            self._show_error(error)

    def open_gate(self, action: Dict[str, Any]) -> None:
        if not self.current_id:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title(action["label"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("520x330")
        dialog.configure(bg=PAPER)
        dialog.columnconfigure(0, weight=1)

        ttk.Label(dialog, text=action["label"], style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))
        result = tk.StringVar()
        row = 1
        if action["gate"] == "C":
            values = action.get("results", [])
            result.set(values[0] if values else "已验收(无MR)")
            ttk.Combobox(dialog, textvariable=result, values=values, state="readonly").grid(row=1, column=0, sticky="ew", padx=14)
            row = 2
        ttk.Label(dialog, text="人工原话").grid(row=row, column=0, sticky="w", padx=14, pady=(10, 4))
        quote = scrolledtext.ScrolledText(dialog, height=7, wrap="word")
        self._style_input(quote)
        quote.grid(row=row + 1, column=0, sticky="nsew", padx=14)
        dialog.rowconfigure(row + 1, weight=1)

        def submit() -> None:
            payload = {"gate": action["gate"], "quote": quote.get("1.0", "end-1c")}
            if action["gate"] == "C":
                payload.update({"project": action.get("project", ""), "result": result.get()})
            try:
                self.app.approve_gate(self.current_id, payload)
                dialog.destroy()
                self.refresh_tasks(self.current_id)
            except Exception as error:
                self._show_error(error)

        buttons = ttk.Frame(dialog)
        buttons.grid(row=row + 2, column=0, sticky="e", padx=14, pady=14)
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="确认写入", command=submit, style="Accent.TButton").pack(side="left")

    def open_new_prd(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("新建需求")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("650x650")
        dialog.configure(bg=PAPER)
        dialog.columnconfigure(1, weight=1)

        task_id = tk.StringVar()
        title = tk.StringVar()
        ttk.Label(dialog, text="需求 id").grid(row=0, column=0, sticky="nw", padx=(14, 8), pady=(14, 6))
        ttk.Entry(dialog, textvariable=task_id).grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=(14, 6))
        ttk.Label(dialog, text="标题").grid(row=1, column=0, sticky="nw", padx=(14, 8), pady=6)
        ttk.Entry(dialog, textvariable=title).grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=6)

        fields = {}  # type: Dict[str, tk.Text]
        for row, (key, label, height) in enumerate(
            (("background", "背景", 4), ("description", "功能描述", 7), ("acceptance", "验收标准", 7), ("out_of_scope", "范围外", 4)),
            start=2,
        ):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="nw", padx=(14, 8), pady=6)
            widget = tk.Text(dialog, height=height, wrap="word")
            self._style_input(widget)
            widget.grid(row=row, column=1, sticky="nsew", padx=(0, 14), pady=6)
            fields[key] = widget
            dialog.rowconfigure(row, weight=1)

        def submit() -> None:
            payload = {"id": task_id.get(), "title": title.get()}
            payload.update({key: widget.get("1.0", "end-1c") for key, widget in fields.items()})
            try:
                self.app.create_prd(payload)
                dialog.destroy()
                self.refresh_tasks(task_id.get())
            except Exception as error:
                self._show_error(error)

        buttons = ttk.Frame(dialog)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", padx=14, pady=14)
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="创建 PRD", command=submit, style="Accent.TButton").pack(side="left")


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, app: WorkflowWorkspace, snapshot: Dict[str, Any], on_saved) -> None:
        super().__init__(parent)
        self.app = app
        self.snapshot = snapshot
        self.on_saved = on_saved
        self.skill_rows = [
            {
                "source_id": row.get("source_id", ""),
                "file": row["file"],
                "mounts": list(row["mounts"]),
                "trigger": row["trigger"],
                "state": row["state"],
            }
            for row in snapshot["skills"]["rows"]
        ]
        self.skill_catalog = list(snapshot["skills"].get("catalog", []))
        self.project_rows = [
            {
                "name": row["name"],
                "path": row["path"],
                "specifications": row["specifications"],
                "commands": list(row["commands"]),
                "branch_model": row["branch_model"],
                "extension": row["extension"],
                "integration": row["integration"],
            }
            for row in snapshot["projects"]["rows"]
        ]
        self.skill_index = None  # type: Optional[int]
        self.project_index = None  # type: Optional[int]
        self._loading_skill = False

        self.title("Workflow Desk V2 设置")
        self.transient(parent)
        self.grab_set()
        self.geometry("1000x680")
        self.minsize(900, 600)
        self.configure(bg=PAPER)

        heading = ttk.Frame(self, style="Header.TFrame", padding=(20, 16))
        heading.pack(fill="x")
        ttk.Label(heading, text="设置中心", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(heading, text="编辑现有配置；阶段顺序、闸口和验证语义保持锁定。", style="HeaderSub.TLabel").pack(anchor="w", pady=(3, 0))

        footer = ttk.Frame(self, style="Header.TFrame", padding=(20, 12))
        footer.pack(side="bottom", fill="x")
        ttk.Label(footer, text="保存会原子写回 config/；检测到外部修改时会拒绝覆盖。", style="HeaderSub.TLabel").pack(side="left")
        ttk.Button(footer, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="保存设置", command=self._save, style="Accent.TButton").pack(side="right", padx=(0, 8))

        self.settings_notebook = ttk.Notebook(self)
        self.settings_notebook.pack(fill="both", expand=True, padx=20, pady=(16, 10))
        self._build_skills_tab()
        self._build_projects_tab()
        self._build_capabilities_tab()

    @staticmethod
    def _panel(parent) -> ttk.Frame:
        return ttk.Frame(parent, style="Header.TFrame", padding=16)

    def _build_skills_tab(self) -> None:
        tab = ttk.Frame(self.settings_notebook, style="Header.TFrame", padding=14)
        self.settings_notebook.add(tab, text="技能挂载")
        panes = ttk.Panedwindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = self._panel(panes)
        right = self._panel(panes)
        panes.add(left, weight=2)
        panes.add(right, weight=3)

        toolbar = ttk.Frame(left, style="Header.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="已编排技能", style="Section.TLabel").pack(side="left")
        self.catalog_button = ttk.Button(
            toolbar,
            command=self._open_skill_catalog,
            style="Accent.TButton",
        )
        self.catalog_button.pack(side="right")
        ttk.Button(toolbar, text="下移", command=lambda: self._move_skill(1)).pack(side="right", padx=(0, 8))
        ttk.Button(toolbar, text="上移", command=lambda: self._move_skill(-1)).pack(side="right", padx=(0, 8))
        self.skill_summary = tk.StringVar()
        ttk.Label(left, textvariable=self.skill_summary, style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        self.skill_tree = ttk.Treeview(left, columns=("file", "mounts", "state"), show="headings", selectmode="browse")
        self.skill_tree.heading("file", text="技能")
        self.skill_tree.heading("mounts", text="环节")
        self.skill_tree.heading("state", text="状态")
        self.skill_tree.column("file", width=190, minwidth=130)
        self.skill_tree.column("mounts", width=120, minwidth=90)
        self.skill_tree.column("state", width=60, minwidth=55, stretch=False)
        self.skill_tree.pack(fill="both", expand=True)
        self.skill_tree.bind("<<TreeviewSelect>>", self._select_skill)
        self._update_skill_summary()

        ttk.Label(right, text="技能设置", style="Section.TLabel").pack(anchor="w")
        self.skill_file = tk.StringVar()
        ttk.Label(right, textvariable=self.skill_file, style="Mono.TLabel").pack(anchor="w", pady=(3, 16))
        ttk.Label(right, text="挂载环节", style="Muted.TLabel").pack(anchor="w")
        stages = ttk.Frame(right, style="Header.TFrame")
        stages.pack(fill="x", pady=(7, 16))
        self.stage_vars = {}  # type: Dict[str, tk.BooleanVar]
        for stage in self.snapshot["skills"]["stages"]:
            value = tk.BooleanVar()
            self.stage_vars[stage] = value
            ttk.Checkbutton(stages, text=stage, variable=value, command=self._skill_form_changed, style="Panel.TCheckbutton").pack(side="left", padx=(0, 14))
        ttk.Label(right, text="触发条件", style="Muted.TLabel").pack(anchor="w")
        self.skill_trigger = tk.StringVar()
        self.skill_trigger.trace_add("write", lambda *_: self._skill_form_changed())
        ttk.Entry(right, textvariable=self.skill_trigger).pack(fill="x", pady=(7, 16))
        ttk.Label(right, text="状态", style="Muted.TLabel").pack(anchor="w")
        self.skill_state = tk.StringVar()
        self.skill_state.trace_add("write", lambda *_: self._skill_form_changed())
        ttk.Combobox(right, textvariable=self.skill_state, values=("启用", "停用"), state="readonly", width=12).pack(anchor="w", pady=(7, 16))
        ttk.Separator(right).pack(fill="x", pady=(2, 14))
        ttk.Label(right, text="技能只能增加检查和约束，不能改变状态机、闸口或验收标准。", wraplength=430, justify="left", style="Muted.TLabel").pack(anchor="w")

        self._refresh_skill_tree(0)

    def _refresh_skill_tree(self, selected: int) -> None:
        self.skill_tree.delete(*self.skill_tree.get_children())
        for index, row in enumerate(self.skill_rows):
            self.skill_tree.insert("", "end", iid=str(index), values=(self._skill_label(row), ", ".join(row["mounts"]), row["state"]))
        if self.skill_rows:
            selected = max(0, min(selected, len(self.skill_rows) - 1))
            self.skill_tree.selection_set(str(selected))
            self.skill_tree.focus(str(selected))
            self.skill_tree.see(str(selected))

    def _select_skill(self, _event=None) -> None:
        selection = self.skill_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        row = self.skill_rows[index]
        self._loading_skill = True
        self.skill_index = index
        self.skill_file.set(row["file"] or row.get("_label", ""))
        for stage, value in self.stage_vars.items():
            value.set(stage in row["mounts"])
        self.skill_trigger.set(row["trigger"])
        self.skill_state.set(row["state"])
        self._loading_skill = False

    def _skill_form_changed(self) -> None:
        if self._loading_skill or self.skill_index is None:
            return
        row = self.skill_rows[self.skill_index]
        row["mounts"] = [stage for stage, value in self.stage_vars.items() if value.get()]
        row["trigger"] = self.skill_trigger.get()
        row["state"] = self.skill_state.get()
        self.skill_tree.item(str(self.skill_index), values=(self._skill_label(row), ", ".join(row["mounts"]), row["state"]))

    def _move_skill(self, offset: int) -> None:
        if self.skill_index is None:
            return
        target = self.skill_index + offset
        if target < 0 or target >= len(self.skill_rows):
            return
        self.skill_rows[self.skill_index], self.skill_rows[target] = self.skill_rows[target], self.skill_rows[self.skill_index]
        self.skill_index = target
        self._refresh_skill_tree(target)

    @staticmethod
    def _skill_label(row: Dict[str, Any]) -> str:
        return row["file"].split("/")[-1] if row.get("file") else row.get("_label", row.get("source_id", ""))

    def _open_skill_catalog(self) -> None:
        dialog = SkillCatalogDialog(
            self,
            self.app,
            self.skill_catalog,
            lambda: self.skill_rows,
            self._add_catalog_skill,
            self._catalog_refreshed,
        )
        self.wait_window(dialog)
        if self.winfo_exists():
            self.grab_set()

    def _catalog_refreshed(self, catalog: List[Dict[str, Any]]) -> None:
        self.skill_catalog = catalog
        self._update_skill_summary()

    def _update_skill_summary(self) -> None:
        self.skill_summary.set(
            "已编排 {} 个；本机已检测 {} 个".format(len(self.skill_rows), len(self.skill_catalog))
        )
        self.catalog_button.configure(text="查看本机技能（{}）".format(len(self.skill_catalog)))

    def _add_catalog_skill(self, item: Dict[str, Any]) -> bool:
        source_id = item.get("source_id", "")
        if not source_id or any(row.get("source_id") == source_id for row in self.skill_rows):
            return False
        self.skill_rows.append(
            {
                "source_id": source_id,
                "file": item.get("file", ""),
                "mounts": [],
                "trigger": "",
                "state": "停用",
                "_label": item.get("name", source_id),
            }
        )
        self._refresh_skill_tree(len(self.skill_rows) - 1)
        self._update_skill_summary()
        return True

    def _build_projects_tab(self) -> None:
        tab = ttk.Frame(self.settings_notebook, style="Header.TFrame", padding=14)
        self.settings_notebook.add(tab, text="项目设置")
        panes = ttk.Panedwindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = self._panel(panes)
        right = self._panel(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        toolbar = ttk.Frame(left, style="Header.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text="已注册项目", style="Section.TLabel").pack(side="left")
        ttk.Button(toolbar, text="导入项目", command=self._import_project, style="Accent.TButton").pack(side="right")
        self.project_list = tk.Listbox(left, activestyle="none", exportselection=False, bg=PANEL, fg=INK, selectbackground=ACCENT_SOFT, selectforeground=INK, relief="flat", highlightthickness=1, highlightbackground=LINE, borderwidth=0)
        self.project_list.pack(fill="both", expand=True)
        self.project_list.bind("<<ListboxSelect>>", self._select_project)
        for project in self.project_rows:
            self.project_list.insert("end", project["name"])

        self.project_canvas = tk.Canvas(right, bg=PANEL, highlightthickness=0, borderwidth=0)
        project_scrollbar = ttk.Scrollbar(right, orient="vertical", command=self.project_canvas.yview)
        self.project_canvas.configure(yscrollcommand=project_scrollbar.set)
        project_scrollbar.pack(side="right", fill="y", padx=(8, 0))
        self.project_canvas.pack(side="left", fill="both", expand=True)
        project_form = ttk.Frame(self.project_canvas, style="Header.TFrame")
        project_window = self.project_canvas.create_window((0, 0), window=project_form, anchor="nw")
        project_form.bind(
            "<Configure>",
            lambda _event: self.project_canvas.configure(scrollregion=self.project_canvas.bbox("all")),
        )
        self.project_canvas.bind(
            "<Configure>",
            lambda event: self.project_canvas.itemconfigure(project_window, width=event.width),
        )

        self.project_name = tk.StringVar()
        ttk.Label(project_form, textvariable=self.project_name, style="Section.TLabel").pack(anchor="w")
        self.project_extension = tk.StringVar()
        ttk.Label(project_form, textvariable=self.project_extension, style="Muted.TLabel").pack(anchor="w", pady=(3, 12))
        ttk.Label(project_form, text="项目路径（工作区内相对路径）", style="Muted.TLabel").pack(anchor="w")
        self.project_path = tk.StringVar()
        ttk.Entry(project_form, textvariable=self.project_path).pack(fill="x", pady=(6, 12))
        ttk.Label(project_form, text="规范文件", style="Muted.TLabel").pack(anchor="w")
        self.project_specs = tk.Text(project_form, height=1, wrap="word")
        WorkflowDesk._style_input(self.project_specs)
        self.project_specs.pack(fill="x", pady=(6, 12))
        ttk.Label(project_form, text="验证命令（每行一条，只保存、不执行）", style="Muted.TLabel").pack(anchor="w")
        self.project_commands = scrolledtext.ScrolledText(project_form, height=3, wrap="word")
        WorkflowDesk._style_input(self.project_commands)
        self.project_commands.pack(fill="x", pady=(6, 12))
        ttk.Label(project_form, text="分支模型（需写明精确基线和交付目标）", style="Muted.TLabel").pack(anchor="w")
        self.project_branch = tk.Text(project_form, height=2, wrap="word")
        WorkflowDesk._style_input(self.project_branch)
        self.project_branch.pack(fill="x", pady=(6, 0))

        def scroll_project(event) -> str:
            self.project_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        self.project_canvas.bind("<MouseWheel>", scroll_project)
        project_form.bind("<MouseWheel>", scroll_project)
        for widget in project_form.winfo_children():
            if not isinstance(widget, tk.Text):
                widget.bind("<MouseWheel>", scroll_project)

        if self.project_rows:
            self.project_list.selection_set(0)
            self._load_project(0)

    def _import_project(self) -> None:
        selected = filedialog.askdirectory(
            parent=self,
            initialdir=str(self.app.root),
            mustexist=True,
            title="导入工作区内的 Git 项目",
        )
        if not selected:
            return
        try:
            project = self.app.inspect_project(selected)
        except Exception as error:
            message = error.message if isinstance(error, ApiError) else str(error)
            messagebox.showerror("导入项目", message, parent=self)
            return
        if any(row["path"].rstrip("/\\") == project["path"].rstrip("/\\") for row in self.project_rows):
            messagebox.showerror("导入项目", "该项目路径已经注册。", parent=self)
            return
        existing_names = {row["name"] for row in self.project_rows}
        base_name = project["name"]
        suffix = 2
        while project["name"] in existing_names:
            project["name"] = "{}-{}".format(base_name, suffix)
            suffix += 1
        self._store_project_form()
        project["_new"] = True
        self.project_rows.append(project)
        index = len(self.project_rows) - 1
        self.project_list.insert("end", project["name"])
        self.project_list.selection_clear(0, "end")
        self.project_list.selection_set(index)
        self.project_list.see(index)
        self._load_project(index)

    @staticmethod
    def _replace_text(widget: tk.Text, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _store_project_form(self) -> None:
        if self.project_index is None:
            return
        row = self.project_rows[self.project_index]
        row["path"] = self.project_path.get()
        row["specifications"] = " ".join(self.project_specs.get("1.0", "end-1c").splitlines()).strip()
        row["commands"] = [line.strip() for line in self.project_commands.get("1.0", "end-1c").splitlines() if line.strip()]
        row["branch_model"] = " ".join(self.project_branch.get("1.0", "end-1c").splitlines()).strip()

    def _load_project(self, index: int) -> None:
        row = self.project_rows[index]
        self.project_index = index
        self.project_name.set(row["name"])
        self.project_extension.set(
            "流程扩展：" + row["extension"] + (" · 新导入，请填写分支模型并检查验证命令" if row.get("_new") else "")
        )
        self.project_path.set(row["path"])
        self._replace_text(self.project_specs, row["specifications"])
        self._replace_text(self.project_commands, "\n".join(row["commands"]))
        self._replace_text(self.project_branch, row["branch_model"])

    def _select_project(self, _event=None) -> None:
        selection = self.project_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index == self.project_index:
            return
        self._store_project_form()
        self._load_project(index)

    def _build_capabilities_tab(self) -> None:
        tab = ttk.Frame(self.settings_notebook, style="Header.TFrame", padding=24)
        self.settings_notebook.add(tab, text="能力档位")
        ttk.Label(tab, text="运行档位偏好", style="Section.TLabel").pack(anchor="w")
        ttk.Label(tab, text="这是主动降级上限，不会给代理增加它原本没有的权限。", style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
        self.capability_mode = tk.StringVar(
            value=CAPABILITY_LABELS.get(
                self.snapshot["capabilities"]["mode"],
                self.snapshot["capabilities"]["mode"],
            )
        )
        chooser = ttk.Combobox(
            tab,
            textvariable=self.capability_mode,
            values=[CAPABILITY_LABELS.get(mode, mode) for mode in self.snapshot["capabilities"]["modes"]],
            state="readonly",
            width=42,
        )
        chooser.pack(anchor="w")
        chooser.bind("<<ComboboxSelected>>", lambda _event: self._update_capability_description())
        self.capability_description = tk.StringVar()
        ttk.Label(tab, textvariable=self.capability_description, wraplength=700, justify="left", style="Muted.TLabel").pack(anchor="w", pady=(16, 22))
        ttk.Separator(tab).pack(fill="x", pady=(0, 20))
        ttk.Label(tab, text="始终锁定", style="Section.TLabel").pack(anchor="w")
        ttk.Label(tab, text="S1～S6 顺序与合法转移 · 闸口 B/C · PASS/FAIL/NOT_RUN/BLOCKED 语义 · 必需过程产物", wraplength=760, justify="left", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self._update_capability_description()

    def _update_capability_description(self) -> None:
        selected = next(
            (mode for mode, label in CAPABILITY_LABELS.items() if label == self.capability_mode.get()),
            self.capability_mode.get(),
        )
        descriptions = {
            "自动检测": "由当前代理按文件、Shell、并行和远端能力自检，选择实际可运行档位。",
            "档位1": "允许代理使用实际拥有的全部能力；仍只在闸口停下。",
            "档位2": "强制不执行 Shell 命令；代理输出命令清单，由人执行并贴回结果。",
            "档位3": "强制纯对话中继；所有文件和命令操作均由人完成。",
        }
        self.capability_description.set(descriptions.get(selected, ""))

    def _save(self) -> None:
        self._store_project_form()
        skill_rows = []
        for row in self.skill_rows:
            item = {key: row[key] for key in ("file", "mounts", "trigger", "state")}
            if row.get("source_id"):
                item["source_id"] = row["source_id"]
            skill_rows.append(item)
        payload = {
            "skills": {"revision": self.snapshot["skills"]["revision"], "rows": skill_rows},
            "projects": {"revision": self.snapshot["projects"]["revision"], "rows": self.project_rows},
            "capabilities": {
                "revision": self.snapshot["capabilities"]["revision"],
                "mode": next(
                    (mode for mode, label in CAPABILITY_LABELS.items() if label == self.capability_mode.get()),
                    self.capability_mode.get(),
                ),
            },
        }
        try:
            self.app.save_settings(payload)
            self.on_saved()
        except Exception as error:
            message = error.message if isinstance(error, ApiError) else str(error)
            messagebox.showerror("Workflow Desk 设置", message, parent=self)
            return
        messagebox.showinfo("Workflow Desk 设置", "设置已保存。", parent=self)
        self.destroy()


class SkillCatalogDialog(tk.Toplevel):
    def __init__(self, parent, app, catalog, rows, on_add, on_refreshed) -> None:
        super().__init__(parent)
        self.app = app
        self.catalog = list(catalog)
        self.rows = rows
        self.on_add = on_add
        self.on_refreshed = on_refreshed
        self.filtered = []  # type: List[Dict[str, Any]]
        self.query = tk.StringVar()
        self.count = tk.StringVar()
        self.path = tk.StringVar()
        self.meta = tk.StringVar()
        self.description = tk.StringVar()

        self.title("本机技能目录")
        self.transient(parent)
        self.grab_set()
        self.geometry("940x600")
        self.minsize(760, 480)
        self.configure(bg=PAPER)

        heading = ttk.Frame(self, style="Header.TFrame", padding=(18, 14))
        heading.pack(fill="x")
        ttk.Label(heading, text="本机技能目录", style="HeaderTitle.TLabel").pack(side="left")
        ttk.Button(heading, text="重新检测", command=self._refresh).pack(side="right")

        search = ttk.Frame(self, style="Header.TFrame", padding=(18, 10))
        search.pack(fill="x")
        ttk.Label(search, text="搜索名称、产品、范围、状态或路径", style="Muted.TLabel").pack(side="left")
        ttk.Label(search, textvariable=self.count, style="Muted.TLabel").pack(side="right")
        ttk.Entry(self, textvariable=self.query).pack(fill="x", padx=18, pady=(0, 12))

        table = ttk.Frame(self, style="Header.TFrame")
        table.pack(fill="both", expand=True, padx=18)
        self.tree = ttk.Treeview(
            table,
            columns=("name", "products", "scope", "status", "orchestrated"),
            show="headings",
            selectmode="extended",
        )
        for key, label, width in (
            ("name", "技能", 220),
            ("products", "产品", 140),
            ("scope", "范围", 150),
            ("status", "来源状态", 100),
            ("orchestrated", "已编排", 65),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70, stretch=True)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._select)

        detail = ttk.Frame(self, style="Header.TFrame", padding=(18, 12))
        detail.pack(fill="x")
        ttk.Label(detail, textvariable=self.path, style="Mono.TLabel", wraplength=870, justify="left").pack(anchor="w")
        ttk.Label(detail, textvariable=self.meta, style="Muted.TLabel", wraplength=870, justify="left").pack(anchor="w", pady=(5, 0))
        ttk.Label(detail, textvariable=self.description, style="Muted.TLabel", wraplength=870, justify="left").pack(anchor="w", pady=(5, 0))

        footer = ttk.Frame(self, style="Header.TFrame", padding=(18, 12))
        footer.pack(fill="x")
        ttk.Button(footer, text="关闭", command=self.destroy).pack(side="right")
        self.add_button = ttk.Button(
            footer,
            text="加入编排（可多选）",
            command=self._add,
            style="Accent.TButton",
            state="disabled",
        )
        self.add_button.pack(side="right", padx=(0, 8))

        self.query.trace_add("write", lambda *_: self._render())
        self._render()

    @staticmethod
    def _text(item: Dict[str, Any], plural: str, singular: str = "") -> str:
        value = item.get(plural, item.get(singular, "") if singular else "")
        if isinstance(value, list):
            return ", ".join(str(part) for part in value)
        return str(value or "")

    def _orchestrated(self, item: Dict[str, Any]) -> bool:
        source_id = item.get("source_id", "")
        return bool(item.get("orchestrated")) or any(
            source_id and row.get("source_id") == source_id for row in self.rows()
        )

    def _status(self, item: Dict[str, Any]) -> str:
        return self._text(item, "status")

    def _orchestration(self, item: Dict[str, Any]) -> str:
        return "是" if self._orchestrated(item) else "否"

    def _addable(self, item: Dict[str, Any]) -> bool:
        return not self._orchestrated(item) and self._text(item, "status") not in ("失效", "无效")

    def _render(self) -> None:
        query = self.query.get().strip().lower()
        self.filtered = []
        for item in self.catalog:
            searchable = " ".join(
                (
                    self._text(item, "name"),
                    self._text(item, "products", "product"),
                    self._text(item, "scopes", "scope"),
                    self._status(item),
                    self._orchestration(item),
                    self._text(item, "source_type"),
                    self._text(item, "evidence", "reason"),
                    self._text(item, "path"),
                )
            ).lower()
            if not query or query in searchable:
                self.filtered.append(item)
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.filtered):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    self._text(item, "name"),
                    self._text(item, "products", "product"),
                    self._text(item, "scopes", "scope"),
                    self._status(item),
                    self._orchestration(item),
                ),
            )
        self.count.set("{} 个技能".format(len(self.filtered)))
        self.path.set("")
        self.meta.set("")
        self.description.set("")
        self.add_button.configure(state="disabled")
        if self.filtered:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._select()

    def _select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item = self.filtered[int(selection[0])]
        self.path.set("路径：" + self._text(item, "path"))
        source_type = self._text(item, "source_type") or "未知"
        evidence = self._text(item, "evidence", "reason") or "无"
        self.meta.set("来源类型：{} · 启用证据：{}".format(source_type, evidence))
        description = self._text(item, "description")
        self.description.set(description)
        self.add_button.configure(
            state="normal"
            if any(self._addable(self.filtered[int(index)]) for index in selection)
            else "disabled"
        )

    def _refresh(self) -> None:
        try:
            self.catalog = list(self.app.settings()["skills"].get("catalog", []))
        except Exception as error:
            message = error.message if isinstance(error, ApiError) else str(error)
            messagebox.showerror("本机技能目录", message, parent=self)
            return
        self.on_refreshed(self.catalog)
        self._render()

    def _add(self) -> None:
        selection = self.tree.selection()
        added = False
        for index in selection:
            item = self.filtered[int(index)]
            if self._addable(item):
                added = self.on_add(item) or added
        if added:
            self._render()


def show_fatal(error: Exception) -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Workflow Desk", str(error), parent=root)
    root.destroy()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Workflow Desk 桌面程序")
    parser.add_argument("--workspace", default=str(default_workspace()), help="工作流根目录")
    args = parser.parse_args(argv)
    try:
        app = WorkflowWorkspace(Path(args.workspace))
        root = tk.Tk()
        WorkflowDesk(root, app)
        root.mainloop()
        return 0
    except Exception as error:
        show_fatal(error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
