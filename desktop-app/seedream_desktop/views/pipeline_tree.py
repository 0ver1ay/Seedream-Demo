from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import tkinter as tk
from tkinter import ttk

if TYPE_CHECKING:
    from seedream_desktop.application import SeedreamApp


def tree_node_kind(iid: str) -> tuple[str, str]:
    if iid.startswith("pipe:"):
        return "pipeline", iid[5:]
    if iid.startswith("stage:"):
        return "stage", iid[6:]
    if iid.startswith("branch:"):
        return "branch", iid[7:]
    return "", ""


class PipelineTreePanel:
    def __init__(
        self,
        parent: ttk.Frame,
        *,
        on_select_branch: Callable[[str], None],
        on_add_pipeline: Callable[[], None],
        on_add_stage: Callable[[], None],
        on_new_branch: Callable[[], None],
        on_new_child: Callable[[], None],
        on_rename: Callable[[], None],
        on_delete: Callable[[], None],
        on_choose_autosave: Callable[[], None],
        get_autosave_label: Callable[[], str],
    ) -> None:
        nav_frame = ttk.LabelFrame(parent, text=" Проект ", style="Card.TLabelframe", padding=12)
        nav_frame.pack(fill=tk.BOTH, expand=True)
        tree_wrap = ttk.Frame(nav_frame, style="Surface.TFrame")
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_wrap, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._on_select_branch = on_select_branch
        self.tree.bind("<<TreeviewSelect>>", self._handle_select)

        nav_btns = ttk.Frame(nav_frame, style="Surface.TFrame")
        nav_btns.pack(fill=tk.X, pady=(10, 0))
        for col, (label, cmd) in enumerate(
            [("+ Пайплайн", on_add_pipeline), ("+ Этап", on_add_stage), ("+ Ветка", on_new_branch)]
        ):
            ttk.Button(nav_btns, text=label, style="Ghost.TButton", command=cmd).grid(
                row=0, column=col, sticky="we", padx=(0 if col == 0 else 4, 0)
            )
            nav_btns.columnconfigure(col, weight=1)
        nav_btns2 = ttk.Frame(nav_frame, style="Surface.TFrame")
        nav_btns2.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(nav_btns2, text="Дочерняя", style="Ghost.TButton", command=on_new_child).pack(side=tk.LEFT)
        ttk.Button(nav_btns2, text="Переименовать", style="Ghost.TButton", command=on_rename).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(nav_btns2, text="Удалить", style="Danger.TButton", command=on_delete).pack(side=tk.LEFT, padx=(4, 0))

        autosave_frame = ttk.LabelFrame(parent, text=" Автосохранение ", style="Card.TLabelframe", padding=12)
        autosave_frame.pack(fill=tk.X, pady=(10, 0))
        self._autosave_label = ttk.Label(
            autosave_frame, text=get_autosave_label(), wraplength=220, style="SurfaceMuted.TLabel"
        )
        self._autosave_label.pack(anchor="w")
        ttk.Button(autosave_frame, text="Выбрать папку", style="Secondary.TButton", command=on_choose_autosave).pack(
            anchor="w", pady=(8, 0)
        )

    def update_autosave_label(self, text: str) -> None:
        self._autosave_label.config(text=text)

    def refresh(self, pipelines: list[dict], active_branch_id: str | None) -> None:
        self.tree.delete(*self.tree.get_children())
        for pipe in pipelines:
            pid = str(pipe.get("id") or "")
            p_iid = f"pipe:{pid}"
            self.tree.insert("", tk.END, iid=p_iid, text=str(pipe.get("name") or pid), open=True)
            for stage in pipe.get("stages") or []:
                sid = str(stage.get("id") or "")
                s_iid = f"stage:{sid}"
                self.tree.insert(p_iid, tk.END, iid=s_iid, text=str(stage.get("name") or sid), open=True)
                for branch in stage.get("branches") or []:
                    bid = str(branch.get("id") or "")
                    b_iid = f"branch:{bid}"
                    label = str(branch.get("name") or bid)
                    if bid == active_branch_id:
                        label += " *"
                    self.tree.insert(s_iid, tk.END, iid=b_iid, text=label)
        if active_branch_id:
            iid = f"branch:{active_branch_id}"
            try:
                self.tree.selection_set(iid)
                self.tree.see(iid)
            except tk.TclError:
                pass

    def selected_iid(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _handle_select(self, _event=None) -> None:
        iid = self.selected_iid()
        if not iid:
            return
        kind, eid = tree_node_kind(iid)
        if kind == "branch":
            self._on_select_branch(eid)
