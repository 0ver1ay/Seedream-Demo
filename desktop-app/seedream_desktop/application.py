from __future__ import annotations

import base64
import copy
import os
import sys
import threading
import traceback
from datetime import datetime
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from shortcuts import ShortcutManager

from seedream_desktop.credentials import (
    apply_seedream_env_from_secrets,
    load_secrets,
    provider_token,
    replicate_token,
)
from seedream_desktop.generation_controller import GenerationController
from seedream_desktop.io_utils import append_log, load_json_file, save_json_file
from seedream_desktop.models import (
    ENHANCE_MODEL_LABEL_TO_SLUG,
    ENHANCE_MODEL_SLUG_TO_LABEL,
    ENHANCE_MODELS,
    ASPECT_QUICK_PRESETS,
    IMAGE_FILE_TYPES,
    IMAGE_MODEL_CONFIGS,
    IMAGE_MODEL_LABEL_TO_SLUG,
    IMAGE_MODEL_SLUG_TO_LABEL,
    PROJECT_FILE_TYPES,
    PROJECT_SCHEMA_VERSION,
    GenSettings,
    RefItem,
    aspect_label,
    aspect_value_from_label,
    guess_mime_type,
    preferred_aspect,
    preferred_size,
)
from seedream_desktop.project_store import (
    _entity_id,
    _slugify,
    _unique_slug,
    branch_rel_prefix,
    default_pipelines_bundle,
    default_workspace_root,
    load_pipelines_from_payload,
    materialize_ref,
    refs_to_snapshot,
    repair_pipeline_invariants,
    write_branch_sidecar,
)
from seedream_desktop.app_config import (
    APP_DIR,
    LOG_FILE,
    SECRETS_FILE,
    SESSION_FILE,
    STAGE_LABELS,
)
from seedream_desktop.images_util import image_from_base64, sanitize_payload
from seedream_desktop.services.http_client import resolve_enhance_fn, resolve_generate_fn, seedream_server_url
from seedream_desktop.services.session_restore import restore_session_async
from seedream_desktop.views.pipeline_tree import PipelineTreePanel, tree_node_kind
from seedream_desktop.views.preview_panel import PreviewPanel
from seedream_desktop.views.refs_panel import RefsPanel
from seedream_desktop.views.settings_dialog import open_settings_dialog
from seedream_desktop.theme import (
    PALETTE,
    apply_theme,
    style_listbox,
    style_spinbox,
    style_text_widget,
)
from seedream_desktop.task_prompts import (
    append_task_iteration,
    create_task_prompt,
    find_task,
    normalize_task_prompts,
)
from server.core import DEFAULT_IMAGE_MODEL, trace_event


def _log(message: str, data: dict | None = None) -> None:
    append_log(LOG_FILE, message, data)


class SeedreamApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        _log("app_start", {"app_dir": APP_DIR, "log_file": LOG_FILE})
        try:
            trace_event("app_tk_init", log_file=LOG_FILE, frozen=getattr(sys, "frozen", False))
        except Exception:
            pass

        self.title("Seedream Студия")
        self.geometry("1400x900")
        self.minsize(1200, 780)
        apply_theme(self)

        try:
            icon_path = os.path.join(APP_DIR, "icon-placeholder.png")
            if os.path.isfile(icon_path):
                self.iconphoto(True, tk.PhotoImage(file=icon_path))
        except Exception:
            pass

        self.secrets = load_secrets(SECRETS_FILE)
        apply_seedream_env_from_secrets(self.secrets)
        self._gen_controller = GenerationController()
        self._gen_thread: threading.Thread | None = None

        self.refs: list[RefItem] = []
        self._last_images_b64: list[str] = []
        self._last_image_b64: str | None = None
        self._last_refs_b64: list[str] = []
        self._selected_image_index = 0
        self._selected_ref_index = -1
        self._settings_window: tk.Toplevel | None = None
        self._generation_prompt_used = ""
        self._preview_panel: PreviewPanel | None = None
        self._pipeline_panel: PipelineTreePanel | None = None
        self._refs_panel: RefsPanel | None = None

        pl, ap, ast, ab = default_pipelines_bundle()
        self._pipelines: list[dict] = pl
        self._active_pipeline_id: str | None = ap
        self._active_stage_id: str | None = ast
        self._active_branch_id: str | None = ab
        self._last_saved_project_path: str | None = None
        self._autosave_root_path = default_workspace_root(APP_DIR)
        self._autosave_seq = 0
        self._current_generation_run_id: str | None = None
        self._task_prompts: list[dict] = []
        self._active_task_id: str | None = None

        self._build_ui()
        self._restore_session_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<Control-Return>", lambda _e: self.on_generate())
        self.bind_all("<Escape>", lambda _e: self.on_cancel_generation())

    def _build_ui(self) -> None:
        ShortcutManager.apply_to(self)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, style="Elevated.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        header = ttk.Frame(top, style="Elevated.TFrame", padding=(18, 12))
        header.pack(fill=tk.X)
        header.columnconfigure(1, weight=1)
        brand = ttk.Frame(header, style="Elevated.TFrame")
        brand.grid(row=0, column=0, sticky="w")
        ttk.Label(brand, text="Seedream", style="Brand.TLabel").pack(side=tk.LEFT)
        ttk.Label(brand, text="  Студия", style="BrandSub.TLabel").pack(side=tk.LEFT, padx=(2, 0))
        self._project_label = ttk.Label(header, text="Новый проект", style="ElevatedMuted.TLabel")
        self._project_label.grid(row=0, column=1, sticky="w", padx=(20, 0))
        mode = "HTTP" if seedream_server_url() else "локально"
        self._mode_label = ttk.Label(header, text=mode, style="Badge.TLabel")
        self._mode_label.grid(row=0, column=2, sticky="e", padx=(12, 0))
        ttk.Button(header, text="Открыть", style="Toolbar.TButton", command=self.on_open_project).grid(row=0, column=3, padx=(12, 0))
        ttk.Button(header, text="Сохранить", style="Toolbar.TButton", command=self.on_save_project).grid(row=0, column=4, padx=(6, 0))
        ttk.Button(header, text="Настройки", style="Toolbar.TButton", command=self.open_settings).grid(row=0, column=5, padx=(6, 0))
        tk.Frame(top, bg=PALETTE["border_subtle"], height=1).pack(fill=tk.X)

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(10, 4))

        left = ttk.Frame(body, width=250)
        center = ttk.Frame(body)
        right = ttk.Frame(body, width=292)
        body.add(left, weight=0)
        body.add(center, weight=1)
        body.add(right, weight=0)

        self._pipeline_panel = PipelineTreePanel(
            left,
            on_select_branch=self._switch_to_branch,
            on_add_pipeline=self._on_add_pipeline,
            on_add_stage=self._on_add_stage,
            on_new_branch=self._on_new_branch,
            on_new_child=self._on_new_child_branch,
            on_rename=self._on_rename_branch,
            on_delete=self._on_delete_node,
            on_choose_autosave=self._on_choose_autosave_folder,
            get_autosave_label=lambda: f"Папка: {self._project_workspace_root()}",
        )

        # --- Center: fixed top (prompt/refs) + expanding preview (no sash) ---
        top_stack = ttk.Frame(center)
        top_stack.pack(fill=tk.X, side=tk.TOP)
        preview_host = ttk.Frame(center)
        preview_host.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=(8, 0))

        prompt_frame = ttk.LabelFrame(top_stack, text=" Промпт ", style="Card.TLabelframe", padding=12)
        prompt_frame.pack(fill=tk.X, pady=(0, 8))
        self.prompt = tk.Text(prompt_frame, height=3, undo=True, wrap="word")
        style_text_widget(self.prompt)
        self.prompt.pack(fill=tk.X)
        self._attach_context_menu(self.prompt)

        task_row = ttk.Frame(prompt_frame, style="Surface.TFrame")
        task_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(task_row, text="Задача", style="SurfaceMuted.TLabel").pack(side=tk.LEFT)
        self._task_var = tk.StringVar(value="")
        self._task_combo = ttk.Combobox(task_row, textvariable=self._task_var, state="readonly", width=28)
        self._task_combo.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
        self._task_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_task_selected())
        ttk.Button(task_row, text="Сохранить", style="Ghost.TButton", command=self._save_current_as_task).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(task_row, text="Итерация", style="Ghost.TButton", command=self._record_prompt_iteration).pack(side=tk.LEFT, padx=(6, 0))

        enh_row = ttk.Frame(prompt_frame, style="Surface.TFrame")
        enh_row.pack(fill=tk.X, pady=(10, 0))
        self.use_enh = tk.IntVar(value=0)
        ttk.Checkbutton(enh_row, text="Использовать улучшенный", style="Surface.TCheckbutton", variable=self.use_enh).pack(side=tk.LEFT)
        self.enhance_with_refs = tk.IntVar(value=1)
        self._enhance_refs_cb = ttk.Checkbutton(
            enh_row,
            text="С референсами",
            style="Surface.TCheckbutton",
            variable=self.enhance_with_refs,
        )
        self._enhance_refs_cb.pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(enh_row, text="Улучшить", style="Secondary.TButton", command=self.on_enhance).pack(side=tk.RIGHT)

        self._enhance_details = ttk.Frame(prompt_frame, style="Surface.TFrame")
        self._enhance_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            prompt_frame,
            text="Показать улучшение и доп. настройки",
            style="Surface.TCheckbutton",
            variable=self._enhance_visible,
            command=self._toggle_enhance_details,
        ).pack(anchor="w", pady=(8, 0))
        self.prompt_enh = tk.Text(self._enhance_details, height=3, undo=True, wrap="word")
        style_text_widget(self.prompt_enh)
        self.prompt_enh.pack(fill=tk.X, pady=(8, 0))
        self._attach_context_menu(self.prompt_enh)
        enh_grid = ttk.Frame(self._enhance_details, style="Surface.TFrame")
        enh_grid.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(enh_grid, text="Модель улучшения", style="SurfaceMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.enh_model = tk.StringVar(value=ENHANCE_MODEL_SLUG_TO_LABEL[ENHANCE_MODELS[0]])
        ttk.Combobox(
            enh_grid, textvariable=self.enh_model, state="readonly",
            values=[ENHANCE_MODEL_SLUG_TO_LABEL[s] for s in ENHANCE_MODELS],
        ).grid(row=1, column=0, sticky="we", pady=(4, 0))
        ttk.Label(enh_grid, text="Рассуждение", style="SurfaceMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.reasoning = tk.StringVar(value="medium")
        ttk.Combobox(enh_grid, textvariable=self.reasoning, state="readonly", values=["low", "medium", "high"]).grid(
            row=1, column=1, sticky="we", padx=(10, 0), pady=(4, 0)
        )
        enh_grid.columnconfigure(0, weight=1)

        refs_frame = ttk.LabelFrame(top_stack, text=" Референсы ", style="Card.TLabelframe", padding=12)
        refs_frame.pack(fill=tk.X)
        self._refs_panel = RefsPanel(
            get_refs=lambda: self.refs,
            get_workspace=self._project_workspace_root,
            on_select=self._select_ref,
            on_reorder=self._reorder_ref,
            on_persist=self._persist_session_state,
        )
        self._refs_panel.build(refs_frame, on_add=self.on_add_files)
        refs_btns = ttk.Frame(refs_frame, style="Surface.TFrame")
        refs_btns.pack(fill=tk.X, pady=(8, 0))
        for label, cmd in [("Вверх", lambda: self.move_ref(-1)), ("Вниз", lambda: self.move_ref(1)), ("Удалить", self.remove_ref), ("Очистить", self.clear_refs)]:
            ttk.Button(refs_btns, text=label, style="Ghost.TButton", command=cmd).pack(side=tk.LEFT, padx=(0, 6))

        self._preview_panel = PreviewPanel(preview_host)
        self._preview_panel.bind_controls(
            on_actual_size=self.actual_preview_size,
            on_reset=self.reset_preview_position,
            on_thumb=self._show_image,
        )
        hist_tools = ttk.Frame(self._preview_panel.history_tab, style="Surface.TFrame")
        hist_tools.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(hist_tools, text="Загрузить настройки", style="Ghost.TButton", command=self._load_selected_run).pack(side=tk.LEFT)
        self._history_list = tk.Listbox(self._preview_panel.history_tab, height=4)
        style_listbox(self._history_list)
        self._history_list.pack(fill=tk.BOTH, expand=True)
        self.preview = self._preview_panel.canvas
        self.preview_meta = self._preview_panel.meta
        self.ribbon_inner = self._preview_panel.ribbon_inner
        self.ribbon_canvas = self._preview_panel.ribbon_canvas
        self.ribbon_scroll = self._preview_panel.ribbon_scroll

        # --- Right: generation ---
        gen_frame = ttk.LabelFrame(right, text=" Генерация ", style="Card.TLabelframe", padding=14)
        gen_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(gen_frame, text="Модель", style="Section.TLabel").pack(anchor="w")
        self.image_model = tk.StringVar(value=IMAGE_MODEL_SLUG_TO_LABEL[DEFAULT_IMAGE_MODEL])
        self._image_model_combo = ttk.Combobox(
            gen_frame, textvariable=self.image_model, state="readonly",
            values=[IMAGE_MODEL_SLUG_TO_LABEL[s] for s in IMAGE_MODEL_CONFIGS],
        )
        self._image_model_combo.pack(fill=tk.X, pady=(6, 14))
        self._image_model_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_model_changed())

        format_box = ttk.Frame(gen_frame, style="Surface.TFrame")
        format_box.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(format_box, text="Формат", style="Section.TLabel").pack(anchor="w")
        grid = ttk.Frame(format_box, style="Surface.TFrame")
        grid.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(grid, text="Размер", style="SurfaceMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text="Соотношение", style="SurfaceMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.size = tk.StringVar()
        self.aspect = tk.StringVar()
        self._aspect_display = tk.StringVar()
        self._size_combo = ttk.Combobox(grid, textvariable=self.size, state="readonly", width=8)
        self._aspect_combo = ttk.Combobox(grid, textvariable=self._aspect_display, state="readonly", width=18)
        self._size_combo.grid(row=1, column=0, sticky="we", pady=(4, 0))
        self._aspect_combo.grid(row=1, column=1, sticky="we", padx=(8, 0), pady=(4, 0))
        self._aspect_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_aspect_combo_changed())
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=2)

        ttk.Label(format_box, text="Быстрый выбор", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(12, 6))
        self._aspect_presets = ttk.Frame(format_box, style="Surface.TFrame")
        self._aspect_presets.pack(fill=tk.X)
        self._aspect_preset_buttons: dict[str, ttk.Button] = {}

        ttk.Label(gen_frame, text="Изображений за запуск", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(4, 0))
        self.max_images = tk.Spinbox(gen_frame, from_=1, to=15, width=6)
        style_spinbox(self.max_images)
        self.max_images.delete(0, tk.END)
        self.max_images.insert(0, "1")
        self.max_images.pack(anchor="w", pady=(4, 0))

        self._advanced_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(gen_frame, text="Дополнительно", style="Surface.TCheckbutton", variable=self._advanced_visible, command=self._toggle_advanced).pack(anchor="w", pady=(12, 0))
        self._advanced_frame = ttk.Frame(gen_frame, style="Surface.TFrame")
        ttk.Label(self._advanced_frame, text="Количество запусков", style="SurfaceMuted.TLabel").pack(anchor="w")
        self.num_calls = tk.Spinbox(self._advanced_frame, from_=1, to=15, width=6)
        style_spinbox(self.num_calls)
        self.num_calls.delete(0, tk.END)
        self.num_calls.insert(0, "1")
        self.num_calls.pack(anchor="w", pady=(4, 4))
        ttk.Label(self._advanced_frame, text="Последовательность", style="SurfaceMuted.TLabel").pack(anchor="w", pady=(8, 0))
        self.sequential = tk.StringVar(value="disabled")
        self._sequential_combo = ttk.Combobox(self._advanced_frame, textvariable=self.sequential, state="readonly", values=["disabled", "auto"])
        self._sequential_combo.pack(fill=tk.X, pady=(4, 0))

        actions = ttk.Frame(gen_frame, style="Surface.TFrame")
        actions.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(actions, text="Сохранить", style="Secondary.TButton", command=self.on_save).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(actions, text="Сохранить все", style="Ghost.TButton", command=self.on_save_all).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(actions, text="Очистить превью", style="Ghost.TButton", command=self.on_clear_generated_previews).pack(fill=tk.X)

        self.show_original = tk.IntVar(value=0)
        ttk.Checkbutton(gen_frame, text="Показать референс", style="Surface.TCheckbutton", variable=self.show_original, command=self.on_toggle_original).pack(anchor="w", pady=(12, 0))

        footer_wrap = ttk.Frame(self, style="Elevated.TFrame")
        footer_wrap.grid(row=2, column=0, sticky="ew")
        tk.Frame(footer_wrap, bg=PALETTE["border_subtle"], height=1).pack(fill=tk.X)
        footer = ttk.Frame(footer_wrap, style="Elevated.TFrame", padding=(16, 12))
        footer.pack(fill=tk.X)
        footer.columnconfigure(0, weight=1)
        self._progress = ttk.Progressbar(footer, mode="indeterminate")
        self._progress.grid(row=0, column=0, sticky="ew", padx=(0, 16))
        self.status = ttk.Label(footer, text="Готово", style="Status.TLabel")
        self.status.grid(row=1, column=0, sticky="w", pady=(8, 0))
        action_bar = ttk.Frame(footer, style="Elevated.TFrame")
        action_bar.grid(row=0, column=1, rowspan=2, sticky="e")
        self._cancel_btn = ttk.Button(action_bar, text="Отмена", style="Ghost.TButton", command=self.on_cancel_generation, state="disabled")
        self._cancel_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._generate_btn = ttk.Button(action_bar, text="Сгенерировать", style="Accent.TButton", command=self.on_generate)
        self._generate_btn.pack(side=tk.LEFT)

        self.bind_all("<Control-0>", lambda _e: self.reset_preview_position())
        self.bind_all("<Control-Key-1>", lambda _e: self.actual_preview_size())

        self._toggle_enhance_details()
        self._toggle_advanced()
        self.on_model_changed()
        self._sync_enhance_refs_toggle()
        self._refresh_tree()

    @property
    def refs_label(self):
        return self._refs_panel.label if self._refs_panel else None

    def _toggle_enhance_details(self) -> None:
        if self._enhance_visible.get():
            self._enhance_details.pack(fill=tk.X, pady=(4, 0))
        else:
            self._enhance_details.pack_forget()

    def _toggle_advanced(self) -> None:
        if self._advanced_visible.get():
            self._advanced_frame.pack(fill=tk.X, pady=(4, 0))
        else:
            self._advanced_frame.pack_forget()

    def ui(self, func, *args, **kwargs) -> None:
        self.after(0, lambda: func(*args, **kwargs))

    def set_status(self, text: str) -> None:
        self.status.config(text=text)
        self.update_idletasks()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._generate_btn.config(state=state)
        self._cancel_btn.config(state="normal" if busy else "disabled")
        if busy:
            self._progress.start(12)
        else:
            self._progress.stop()

    def _selected_image_model_slug(self) -> str:
        return IMAGE_MODEL_LABEL_TO_SLUG.get(self.image_model.get(), DEFAULT_IMAGE_MODEL)

    def _selected_enhance_model_slug(self) -> str:
        return ENHANCE_MODEL_LABEL_TO_SLUG.get(self.enh_model.get(), ENHANCE_MODELS[0])

    def _project_workspace_root(self) -> str:
        if self._autosave_root_path:
            return os.path.normpath(self._autosave_root_path)
        return default_workspace_root(APP_DIR)

    def _refresh_autosave_path_label(self) -> None:
        if self._pipeline_panel:
            self._pipeline_panel.update_autosave_label(f"Папка: {self._project_workspace_root()}")

    def _refresh_project_label(self) -> None:
        if self._last_saved_project_path:
            self._project_label.config(text=os.path.basename(self._last_saved_project_path))
        else:
            self._project_label.config(text="Новый проект")

    def _on_choose_autosave_folder(self) -> None:
        current = self._project_workspace_root()
        initialdir = current if os.path.isdir(current) else APP_DIR
        path = filedialog.askdirectory(initialdir=initialdir, title="Папка автосохранения")
        if not path:
            return
        self._autosave_root_path = os.path.normpath(path)
        self._refresh_autosave_path_label()
        self._persist_session_state()
        self.set_status(f"Папка автосохранения: {self._autosave_root_path}")

    def _get_active_pipeline(self) -> dict | None:
        for p in self._pipelines:
            if p.get("id") == self._active_pipeline_id:
                return p
        return self._pipelines[0] if self._pipelines else None

    def _get_active_stage(self) -> dict | None:
        p = self._get_active_pipeline()
        if not p:
            return None
        for s in p.get("stages") or []:
            if s.get("id") == self._active_stage_id:
                return s
        stages = p.get("stages") or []
        return stages[0] if stages else None

    def _get_active_branch(self) -> dict | None:
        st = self._get_active_stage()
        if not st:
            return None
        for b in st.get("branches") or []:
            if b.get("id") == self._active_branch_id:
                return b
        brs = st.get("branches") or []
        return brs[0] if brs else None

    def _tree_node_kind(self, iid: str) -> tuple[str, str]:
        return tree_node_kind(iid)

    def _refresh_tree(self) -> None:
        if self._pipeline_panel:
            self._pipeline_panel.refresh(self._pipelines, self._active_branch_id)

    def _switch_to_branch(self, bid: str) -> None:
        if self._gen_controller.is_busy or bid == self._active_branch_id:
            return
        self._sync_active_branch_from_ui()
        for p in self._pipelines:
            for s in p.get("stages") or []:
                for b in s.get("branches") or []:
                    if str(b.get("id")) == bid:
                        self._active_pipeline_id = str(p.get("id"))
                        self._active_stage_id = str(s.get("id"))
                        self._active_branch_id = bid
                        p["active_stage_id"] = self._active_stage_id
                        s["active_branch_id"] = bid
                        self._apply_active_branch_to_ui()
                        self._persist_session_state()
                        return

    def on_model_changed(self) -> None:
        config = IMAGE_MODEL_CONFIGS.get(self._selected_image_model_slug(), IMAGE_MODEL_CONFIGS[DEFAULT_IMAGE_MODEL])
        sizes = list(config["sizes"])
        aspects = list(config["aspect_ratios"])
        self._size_combo["values"] = sizes
        self._aspect_combo["values"] = [aspect_label(a) for a in aspects]
        if self.size.get() not in sizes:
            self.size.set(preferred_size(sizes))
        current_aspect = self.aspect.get()
        if current_aspect not in aspects:
            current_aspect = preferred_aspect(aspects)
            self.aspect.set(current_aspect)
        self._aspect_display.set(aspect_label(self.aspect.get()))
        self._rebuild_aspect_presets(aspects)
        max_refs = config["max_reference_images"]
        if self._refs_panel:
            self._refs_panel.set_label(f"Референсы (макс. {max_refs})")
        supports_batch = bool(config.get("supports_batch"))
        if supports_batch:
            self._sequential_combo.config(state="readonly")
            self.max_images.config(state="normal")
        else:
            self.sequential.set("disabled")
            self._sequential_combo.config(state="disabled")
            self.max_images.delete(0, tk.END)
            self.max_images.insert(0, "1")
            self.max_images.config(state="disabled")
        if len(self.refs) > max_refs:
            self.refs = self.refs[:max_refs]
            self.refresh_refs_list()
            self.set_status(f"Оставлено {max_refs} референсов для текущей модели")

    def _rebuild_aspect_presets(self, aspects: list[str]) -> None:
        for child in self._aspect_presets.winfo_children():
            child.destroy()
        self._aspect_preset_buttons.clear()
        col = 0
        row = 0
        for value in ASPECT_QUICK_PRESETS:
            if value not in aspects:
                continue
            short = {
                "match_input_image": "Реф",
                "1:1": "1:1",
                "16:9": "16:9",
                "9:16": "9:16",
                "4:3": "4:3",
                "21:9": "21:9",
            }.get(value, value)
            btn = ttk.Button(
                self._aspect_presets,
                text=short,
                style="Chip.TButton",
                command=lambda v=value: self._set_aspect_ratio(v),
                width=5,
            )
            btn.grid(row=row, column=col, padx=(0, 4), pady=(0, 4), sticky="we")
            self._aspect_preset_buttons[value] = btn
            col += 1
            if col >= 3:
                col = 0
                row += 1
        for i in range(3):
            self._aspect_presets.columnconfigure(i, weight=1)
        self._refresh_aspect_preset_styles()

    def _set_aspect_ratio(self, value: str) -> None:
        self.aspect.set(value)
        self._aspect_display.set(aspect_label(value))
        self._refresh_aspect_preset_styles()

    def _on_aspect_combo_changed(self) -> None:
        value = aspect_value_from_label(self._aspect_display.get())
        self.aspect.set(value)
        self._refresh_aspect_preset_styles()

    def _refresh_aspect_preset_styles(self) -> None:
        current = self.aspect.get()
        for value, btn in self._aspect_preset_buttons.items():
            btn.configure(style="ChipSelected.TButton" if value == current else "Chip.TButton")

    def _branch_gen_snapshot_from_ui(self) -> dict:
        try:
            max_img = max(1, min(15, int(self.max_images.get() or 1)))
        except ValueError:
            max_img = 1
        return {
            "image_model": self._selected_image_model_slug(),
            "size": self.size.get() or "4K",
            "aspect_ratio": self.aspect.get() or "match_input_image",
            "sequential_image_generation": self.sequential.get(),
            "num_calls": self.num_calls.get().strip(),
            "max_images": str(max_img),
            "enhance_model": self._selected_enhance_model_slug(),
            "reasoning": self.reasoning.get(),
            "max_tokens": "4096",
        }

    def _apply_gen_snapshot_to_ui(self, gs: dict | None) -> None:
        settings = GenSettings.from_snapshot(gs)
        if settings.image_model in IMAGE_MODEL_SLUG_TO_LABEL:
            self.image_model.set(IMAGE_MODEL_SLUG_TO_LABEL[settings.image_model])
        self.on_model_changed()
        model_config = IMAGE_MODEL_CONFIGS.get(self._selected_image_model_slug(), IMAGE_MODEL_CONFIGS[DEFAULT_IMAGE_MODEL])
        if settings.size in model_config["sizes"]:
            self.size.set(settings.size)
        elif model_config["sizes"]:
            self.size.set(preferred_size(list(model_config["sizes"])))
        if settings.aspect_ratio in model_config["aspect_ratios"]:
            self._set_aspect_ratio(settings.aspect_ratio)
        elif model_config["aspect_ratios"]:
            self._set_aspect_ratio(preferred_aspect(list(model_config["aspect_ratios"])))
        if settings.sequential_image_generation in ("disabled", "auto"):
            self.sequential.set(settings.sequential_image_generation)
        self.num_calls.delete(0, tk.END)
        self.num_calls.insert(0, str(settings.num_calls))
        self.max_images.delete(0, tk.END)
        self.max_images.insert(0, str(settings.max_images))
        lbl = ENHANCE_MODEL_SLUG_TO_LABEL.get(settings.enhance_model)
        if lbl:
            self.enh_model.set(lbl)
        self.reasoning.set(settings.reasoning)

    def _sync_active_branch_from_ui(self) -> None:
        branch = self._get_active_branch()
        if not branch:
            return
        ws = self._project_workspace_root()
        branch["prompt_snapshot"] = self.prompt.get("1.0", tk.END).rstrip("\n")
        branch["prompt_enhanced_snapshot"] = self.prompt_enh.get("1.0", tk.END).rstrip("\n")
        branch["use_enhanced"] = int(self.use_enh.get())
        branch["refs_snapshot"] = refs_to_snapshot(self.refs, ws)
        branch["gen_snapshot"] = self._branch_gen_snapshot_from_ui()

    def _apply_active_branch_to_ui(self) -> None:
        branch = self._get_active_branch()
        if not branch:
            self._refresh_tree()
            return
        self.prompt.delete("1.0", tk.END)
        self.prompt.insert("1.0", str(branch.get("prompt_snapshot") or ""))
        self.prompt_enh.delete("1.0", tk.END)
        self.prompt_enh.insert("1.0", str(branch.get("prompt_enhanced_snapshot") or ""))
        self.use_enh.set(int(branch.get("use_enhanced", 0) or 0))
        ws = self._project_workspace_root()
        refs: list[RefItem] = []
        for item in branch.get("refs_snapshot") or []:
            ref = RefItem.from_dict(item) if isinstance(item, dict) else None
            if ref is not None:
                refs.append(ref)
        model_slug = (branch.get("gen_snapshot") or {}).get("image_model") or self._selected_image_model_slug()
        model_config = IMAGE_MODEL_CONFIGS.get(model_slug, IMAGE_MODEL_CONFIGS[DEFAULT_IMAGE_MODEL])
        self.refs = refs[: model_config["max_reference_images"]]
        self.refresh_refs_list()
        self._apply_gen_snapshot_to_ui(branch.get("gen_snapshot") or {})
        self._load_branch_images_into_viewer(branch)
        self._refresh_history_list()
        self._refresh_tree()

    def _refresh_history_list(self) -> None:
        self._history_list.delete(0, tk.END)
        branch = self._get_active_branch()
        if not branch:
            return
        for run in reversed(branch.get("runs") or []):
            if not isinstance(run, dict):
                continue
            started = str(run.get("started_at") or "")
            model = str(run.get("image_model") or run.get("model") or "")
            status = str(run.get("status") or "done")
            prompt = str(run.get("effective_prompt") or "")[:48]
            self._history_list.insert(tk.END, f"{started} | {status} | {model} | {prompt}")

    def _load_selected_run(self) -> None:
        sel = self._history_list.curselection()
        if not sel:
            return
        branch = self._get_active_branch()
        if not branch:
            return
        runs = list(reversed(branch.get("runs") or []))
        idx = sel[0]
        if idx < 0 or idx >= len(runs):
            return
        run = runs[idx]
        if not isinstance(run, dict):
            return
        self.prompt.delete("1.0", tk.END)
        self.prompt.insert("1.0", str(run.get("effective_prompt") or ""))
        self._apply_gen_snapshot_to_ui(run)
        self.set_status("Настройки из истории применены")

    def _load_branch_images_into_viewer(self, branch: dict) -> None:
        self._clear_generated_previews_state()
        ws = self._project_workspace_root()
        images_meta = list(branch.get("images") or [])
        images_meta.sort(key=lambda x: str(x.get("saved_at") or ""))
        loaded: list[str] = []
        ws_norm = os.path.normpath(ws)
        for meta in images_meta:
            if not isinstance(meta, dict):
                continue
            rel = meta.get("rel_path")
            if not isinstance(rel, str) or not rel.strip():
                abs_meta = meta.get("abs_path")
                if not isinstance(abs_meta, str) or not abs_meta.strip():
                    continue
                path = os.path.normpath(abs_meta)
            else:
                path = os.path.normpath(os.path.join(ws_norm, rel.replace("/", os.sep)))
                if not path.startswith(ws_norm + os.sep) and path != ws_norm:
                    continue
            if not os.path.isfile(path):
                abs_meta = meta.get("abs_path")
                if isinstance(abs_meta, str) and abs_meta.strip() and os.path.isfile(os.path.normpath(abs_meta)):
                    path = os.path.normpath(abs_meta)
                else:
                    continue
            try:
                with open(path, "rb") as f:
                    loaded.append(base64.b64encode(f.read()).decode("utf-8"))
            except Exception:
                continue
        self._last_images_b64 = loaded
        if loaded:
            self._show_image(0)

    def _autosave_single_generated_image(self, image_b64: str) -> None:
        branch = self._get_active_branch()
        pipe = self._get_active_pipeline()
        stage = self._get_active_stage()
        if not (branch and pipe and stage):
            return
        try:
            ws_root = self._project_workspace_root()
            os.makedirs(ws_root, exist_ok=True)
            rel_prefix = branch_rel_prefix(pipe, stage, branch)
            branch["autosave_dir"] = rel_prefix
            rel_dir = f"{rel_prefix}/images"
            abs_dir = os.path.normpath(os.path.join(ws_root, rel_dir.replace("/", os.sep)))
            os.makedirs(abs_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._autosave_seq += 1
            fname = f"img_{ts}_{self._autosave_seq:04d}.png"
            abs_path = os.path.join(abs_dir, fname)
            with open(abs_path, "wb") as f:
                f.write(base64.b64decode(image_b64))
            rel_path = f"{rel_dir}/{fname}".replace("\\", "/")
            entry = {
                "rel_path": rel_path,
                "abs_path": os.path.normpath(abs_path),
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "run_id": self._current_generation_run_id,
                "prompt": self._generation_prompt_used or "",
                "model": self._selected_image_model_slug(),
                "size": self.size.get() or "4K",
                "aspect_ratio": self.aspect.get() or "match_input_image",
            }
            branch.setdefault("images", []).append(entry)
            write_branch_sidecar(ws_root, pipe, stage, branch)
        except Exception as exc:
            _log("autosave_error", {"error": str(exc), "traceback": traceback.format_exc()})

    def _record_generation_run_start(self, calls: int, effective_prompt: str) -> str:
        self._generation_prompt_used = effective_prompt
        self._sync_active_branch_from_ui()
        branch = self._get_active_branch()
        rid = _entity_id("run")
        self._current_generation_run_id = rid
        if not branch:
            return rid
        run = {
            "id": rid,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "status": "running",
            "calls": calls,
            **self._branch_gen_snapshot_from_ui(),
            "effective_prompt": effective_prompt,
            "refs_snapshot": refs_to_snapshot(self.refs, self._project_workspace_root()),
        }
        branch.setdefault("runs", []).append(run)
        return rid

    def _finalize_run(self, run_id: str, *, status: str, images: int, failures: int, elapsed_s: float, error: str = "") -> None:
        branch = self._get_active_branch()
        if not branch:
            return
        for run in branch.get("runs") or []:
            if isinstance(run, dict) and run.get("id") == run_id:
                run["status"] = status
                run["completed_at"] = datetime.now().isoformat(timespec="seconds")
                run["images_count"] = images
                run["failures"] = failures
                run["elapsed_s"] = round(elapsed_s, 3)
                if error:
                    run["error"] = error
                break
        self._refresh_history_list()

    def _collect_project_payload(self) -> dict:
        self._sync_active_branch_from_ui()
        ws = self._project_workspace_root()
        return {
            "seedream_project_version": PROJECT_SCHEMA_VERSION,
            "prompt": self.prompt.get("1.0", tk.END).strip(),
            "prompt_enhanced": self.prompt_enh.get("1.0", tk.END).strip(),
            "use_enhanced": int(self.use_enh.get()),
            "enhance_model": self._selected_enhance_model_slug(),
            "reasoning": self.reasoning.get(),
            "image_model": self._selected_image_model_slug(),
            "size": self.size.get() or "4K",
            "aspect_ratio": self.aspect.get() or "match_input_image",
            "sequential_image_generation": self.sequential.get(),
            "num_calls": self.num_calls.get().strip(),
            "max_images": self.max_images.get().strip(),
            "refs": refs_to_snapshot(self.refs, ws),
            "pipelines": copy.deepcopy(self._pipelines),
            "active_pipeline_id": self._active_pipeline_id,
            "active_stage_id": self._active_stage_id,
            "active_branch_id": self._active_branch_id,
            "autosave_root_path": ws,
            "task_prompts": copy.deepcopy(self._task_prompts),
            "active_task_id": self._active_task_id,
        }

    def _apply_project_payload(self, payload: dict, *, silent: bool = False) -> None:
        if not isinstance(payload, dict):
            return
        ws = self._project_workspace_root()
        autosave_root = payload.get("autosave_root_path")
        if isinstance(autosave_root, str) and autosave_root.strip():
            self._autosave_root_path = os.path.normpath(autosave_root)
            self._refresh_autosave_path_label()
            ws = self._autosave_root_path
        self.prompt.delete("1.0", tk.END)
        self.prompt.insert("1.0", payload.get("prompt", ""))
        self.prompt_enh.delete("1.0", tk.END)
        self.prompt_enh.insert("1.0", payload.get("prompt_enhanced", ""))
        self.use_enh.set(int(payload.get("use_enhanced", 0) or 0))
        enhance_slug = payload.get("enhance_model") or ENHANCE_MODELS[0]
        enhance_label = ENHANCE_MODEL_SLUG_TO_LABEL.get(enhance_slug)
        if enhance_label:
            self.enh_model.set(enhance_label)
        self.reasoning.set(str(payload.get("reasoning") or "medium"))
        image_slug = payload.get("image_model") or DEFAULT_IMAGE_MODEL
        image_label = IMAGE_MODEL_SLUG_TO_LABEL.get(image_slug)
        if image_label:
            self.image_model.set(image_label)
        self.on_model_changed()
        model_config = IMAGE_MODEL_CONFIGS.get(self._selected_image_model_slug(), IMAGE_MODEL_CONFIGS[DEFAULT_IMAGE_MODEL])
        if payload.get("size") in model_config["sizes"]:
            self.size.set(payload["size"])
        if payload.get("aspect_ratio") in model_config["aspect_ratios"]:
            self.aspect.set(payload["aspect_ratio"])
        if str(payload.get("sequential_image_generation") or "disabled") in ("disabled", "auto"):
            self.sequential.set(str(payload.get("sequential_image_generation") or "disabled"))
        self.num_calls.delete(0, tk.END)
        self.num_calls.insert(0, str(payload.get("num_calls") or "1"))
        self.max_images.delete(0, tk.END)
        self.max_images.insert(0, str(payload.get("max_images") or "1"))
        refs: list[RefItem] = []
        for item in payload.get("refs", []):
            ref = RefItem.from_dict(item)
            if ref is not None:
                refs.append(ref)
        self.refs = refs[: model_config["max_reference_images"]]
        self.refresh_refs_list()
        pipelines, ap, ast, ab = load_pipelines_from_payload(payload, ws)
        self._pipelines = pipelines
        self._active_pipeline_id, self._active_stage_id, self._active_branch_id = ap, ast, ab
        self._task_prompts = normalize_task_prompts(payload.get("task_prompts"))
        self._active_task_id = payload.get("active_task_id") if isinstance(payload.get("active_task_id"), str) else None
        if self._active_task_id and find_task(self._task_prompts, self._active_task_id) is None:
            self._active_task_id = None
        self._refresh_task_combo()
        self._apply_active_branch_to_ui()
        if not silent:
            self.set_status("Проект загружен")

    def _persist_session_state(self) -> None:
        try:
            save_json_file(SESSION_FILE, self._collect_project_payload())
        except Exception as exc:
            _log("session_save_error", {"error": str(exc)})

    def _restore_session_state(self) -> None:
        def _load() -> dict | None:
            payload = load_json_file(SESSION_FILE)
            return payload if payload else None

        def _apply(payload: dict) -> None:
            self._apply_project_payload(payload, silent=True)
            self.set_status("Сессия восстановлена")

        restore_session_async(
            self,
            session_path=SESSION_FILE,
            load_payload=_load,
            on_loaded=_apply,
            on_empty=lambda: None,
        )

    def on_open_project(self) -> None:
        path = filedialog.askopenfilename(filetypes=PROJECT_FILE_TYPES)
        if not path:
            return
        path = os.path.normpath(path)
        try:
            self._last_saved_project_path = path
            self._apply_project_payload(load_json_file(path))
            self._persist_session_state()
            self._refresh_project_label()
        except Exception as exc:
            self._last_saved_project_path = None
            messagebox.showerror("Ошибка открытия", str(exc))

    def on_save_project(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".seedream.json", filetypes=PROJECT_FILE_TYPES)
        if not path:
            return
        path = os.path.normpath(path)
        try:
            save_json_file(path, self._collect_project_payload())
            self._last_saved_project_path = path
            self._persist_session_state()
            self._refresh_project_label()
            self.set_status("Проект сохранён")
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))

    def open_settings(self) -> None:
        def _on_saved(secrets: dict) -> None:
            self.secrets = secrets
            mode = "HTTP" if seedream_server_url() else "локально"
            self._mode_label.config(text=mode)

        open_settings_dialog(self, on_saved=_on_saved)

    def on_add_files(self) -> None:
        config = IMAGE_MODEL_CONFIGS.get(self._selected_image_model_slug(), IMAGE_MODEL_CONFIGS[DEFAULT_IMAGE_MODEL])
        max_refs = config["max_reference_images"]
        remaining = max_refs - len(self.refs)
        if remaining <= 0:
            messagebox.showwarning("Лимит", f"Максимум {max_refs} референсов для этой модели")
            return
        paths = filedialog.askopenfilenames(filetypes=IMAGE_FILE_TYPES)
        if not paths:
            return
        ws = self._project_workspace_root()
        os.makedirs(ws, exist_ok=True)
        added = 0
        for path in paths[:remaining]:
            with open(path, "rb") as f:
                raw = f.read()
            name = os.path.basename(path)
            ref = materialize_ref(RefItem(name, guess_mime_type(name), base64=base64.b64encode(raw).decode("utf-8")), ws)
            self.refs.append(ref)
            added += 1
        self.refresh_refs_list()
        if added:
            self.set_status(f"Добавлено референсов: {added}")
        self._persist_session_state()

    def refresh_refs_list(self) -> None:
        if self._refs_panel:
            self._refs_panel.set_selected_index(self._selected_ref_index)
            self._refs_panel.refresh()
        self._sync_enhance_refs_toggle()

    def _sync_enhance_refs_toggle(self) -> None:
        cb = getattr(self, "_enhance_refs_cb", None)
        if cb is None:
            return
        state = "normal" if self.refs else "disabled"
        try:
            cb.configure(state=state)
        except tk.TclError:
            pass
        if not self.refs:
            # Keep preference, but UI shows disabled until refs appear
            pass

    def _reorder_ref(self, source: int, target: int) -> None:
        item = self.refs.pop(source)
        self.refs.insert(target, item)
        self._selected_ref_index = target

    def _select_ref(self, idx: int) -> None:
        self._selected_ref_index = idx
        if self._refs_panel:
            self._refs_panel.set_selected_index(idx)
            self._refs_panel.refresh()
        if self.show_original.get():
            self.preview_selected_ref()

    def preview_selected_ref(self, reset_view: bool = True) -> None:
        if self._selected_ref_index < 0 or self._selected_ref_index >= len(self.refs):
            return
        ws = self._project_workspace_root()
        b64 = self.refs[self._selected_ref_index].load_base64(ws)
        if not b64:
            return
        try:
            img = image_from_base64(b64)
            if self._preview_panel:
                self._preview_panel.set_image(img, source=f"Референс {self._selected_ref_index + 1}/{len(self.refs)}")
        except Exception as exc:
            self.set_status(f"Не удалось открыть референс: {exc}")

    def move_ref(self, delta: int) -> None:
        if self._selected_ref_index < 0:
            return
        idx = self._selected_ref_index
        new_idx = max(0, min(len(self.refs) - 1, idx + delta))
        if new_idx == idx:
            return
        self.refs[idx], self.refs[new_idx] = self.refs[new_idx], self.refs[idx]
        self._selected_ref_index = new_idx
        self.refresh_refs_list()
        self._persist_session_state()

    def remove_ref(self) -> None:
        if self._selected_ref_index < 0:
            return
        self.refs.pop(self._selected_ref_index)
        self._selected_ref_index = min(self._selected_ref_index, len(self.refs) - 1) if self.refs else -1
        self.refresh_refs_list()
        self._persist_session_state()

    def clear_refs(self) -> None:
        self.refs.clear()
        self._selected_ref_index = -1
        self.refresh_refs_list()
        self._persist_session_state()

    def _clear_generated_previews_state(self) -> None:
        self._last_images_b64 = []
        self._last_image_b64 = None
        self._selected_image_index = 0
        self.show_original.set(0)
        if self._preview_panel:
            self._preview_panel.clear()

    def on_clear_generated_previews(self) -> None:
        self._clear_generated_previews_state()
        self.set_status("Сгенерированные превью очищены")

    def on_toggle_original(self) -> None:
        if self.show_original.get():
            self.preview_selected_ref()
        elif self._last_images_b64:
            self._show_image(self._selected_image_index)

    def _task_combo_values(self) -> list[str]:
        return [f"{t.get('name')}  ·  {str(t.get('id'))[-6:]}" for t in self._task_prompts]

    def _refresh_task_combo(self) -> None:
        if not hasattr(self, "_task_combo"):
            return
        values = self._task_combo_values()
        self._task_combo["values"] = values
        active = find_task(self._task_prompts, self._active_task_id)
        if active is None:
            self._task_var.set("")
            return
        label = f"{active.get('name')}  ·  {str(active.get('id'))[-6:]}"
        self._task_var.set(label)

    def _on_task_selected(self) -> None:
        selected = self._task_var.get()
        for task in self._task_prompts:
            label = f"{task.get('name')}  ·  {str(task.get('id'))[-6:]}"
            if label == selected:
                self._active_task_id = str(task.get("id"))
                self.prompt.delete("1.0", tk.END)
                self.prompt.insert("1.0", str(task.get("prompt") or ""))
                self.prompt_enh.delete("1.0", tk.END)
                self.prompt_enh.insert("1.0", str(task.get("prompt_enhanced") or ""))
                if task.get("prompt_enhanced") and not self._enhance_visible.get():
                    self._enhance_visible.set(True)
                    self._toggle_enhance_details()
                self.set_status(f"Задача: {task.get('name')} ({len(task.get('iterations') or [])} итер.)")
                self._persist_session_state()
                return

    def _save_current_as_task(self) -> None:
        prompt = self.prompt.get("1.0", tk.END).rstrip("\n")
        enhanced = self.prompt_enh.get("1.0", tk.END).rstrip("\n")
        if not prompt.strip():
            messagebox.showinfo("Задача", "Сначала введите промпт.")
            return
        name = simpledialog.askstring("Задача", "Название задачи:", parent=self)
        if not name or not name.strip():
            return
        task = create_task_prompt(name=name.strip(), prompt=prompt, prompt_enhanced=enhanced)
        self._task_prompts.append(task)
        self._active_task_id = str(task["id"])
        self._refresh_task_combo()
        self._persist_session_state()
        self.set_status(f"Задача сохранена: {task['name']}")

    def _record_prompt_iteration(self, *, kind: str = "edit") -> None:
        task = find_task(self._task_prompts, self._active_task_id)
        if task is None:
            self._save_current_as_task()
            return
        prompt = self.prompt.get("1.0", tk.END).rstrip("\n")
        enhanced = self.prompt_enh.get("1.0", tk.END).rstrip("\n")
        append_task_iteration(task, prompt=prompt, prompt_enhanced=enhanced, kind=kind)
        self._refresh_task_combo()
        self._persist_session_state()
        self.set_status(f"Итерация #{len(task.get('iterations') or [])}: {task.get('name')}")

    def _maybe_append_active_task(self, *, kind: str) -> None:
        if not self._active_task_id:
            return
        task = find_task(self._task_prompts, self._active_task_id)
        if task is None:
            return
        prompt = self.prompt.get("1.0", tk.END).rstrip("\n")
        enhanced = self.prompt_enh.get("1.0", tk.END).rstrip("\n")
        append_task_iteration(task, prompt=prompt, prompt_enhanced=enhanced, kind=kind)
        self._refresh_task_combo()

    def on_enhance(self) -> None:
        text = self.prompt.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Промпт", "Введите промпт для улучшения.")
            return
        provider, model = self._selected_enhance_model_slug().split(":", 1)
        token = provider_token(self.secrets, provider)
        if not token:
            messagebox.showerror("Токен", f"Укажите токен для {provider} в настройках или переменных окружения.")
            return
        refs_b64: list[str] = []
        if self.enhance_with_refs.get() and self.refs:
            if "llama" in model.lower():
                self.set_status("Llama без vision — референсы не отправятся")
            else:
                ws = self._project_workspace_root()
                for ref in self.refs[:4]:
                    b64 = ref.load_base64(ws)
                    if b64:
                        refs_b64.append(b64)
        status = "Улучшаю промпт с референсами..." if refs_b64 else "Улучшаю промпт..."
        self.set_status(status)

        def _run() -> None:
            try:
                body: dict[str, Any] = {
                    "text": text,
                    "provider": provider,
                    "model": model,
                    "token": token,
                    "reasoning_effort": self.reasoning.get() or None,
                }
                if refs_b64:
                    body["init_images_base64"] = refs_b64
                result = resolve_enhance_fn()(body)
                enhanced = result.get("text", text)
                self.ui(self._set_enhanced_text, enhanced)
                self.ui(self._maybe_append_active_task, kind="enhance")
                self.ui(self.set_status, "Промпт улучшен" + (f" (реф.: {len(refs_b64)})" if refs_b64 else ""))
                self.ui(self._persist_session_state)
            except Exception as exc:
                self.ui(lambda: messagebox.showerror("Ошибка улучшения", str(exc)))
                self.ui(self.set_status, f"Ошибка улучшения: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def _set_enhanced_text(self, text: str) -> None:
        self.prompt_enh.delete("1.0", tk.END)
        self.prompt_enh.insert("1.0", text)
        if not self._enhance_visible.get():
            self._enhance_visible.set(True)
            self._toggle_enhance_details()
        self.use_enh.set(1)

    def on_generate(self) -> None:
        if self._gen_controller.is_busy:
            return
        prompt = self.prompt.get("1.0", tk.END).strip()
        if self.use_enh.get():
            enhanced = self.prompt_enh.get("1.0", tk.END).strip()
            if enhanced:
                prompt = enhanced
        if not prompt:
            messagebox.showinfo("Промпт", "Введите промпт перед генерацией.")
            return
        token = replicate_token(self.secrets)
        if not token:
            messagebox.showerror("Токен", "Укажите REPLICATE_API_TOKEN в настройках или переменных окружения.")
            return
        try:
            calls = max(1, int(self.num_calls.get() or 1))
            max_images = max(1, min(15, int(self.max_images.get() or 1)))
        except ValueError:
            calls, max_images = 1, 1
        ws = self._project_workspace_root()
        refs_b64 = []
        for ref in self.refs:
            b64 = ref.load_base64(ws)
            if b64:
                refs_b64.append(b64)
        payload = {
            "prompt": prompt,
            "model": self._selected_image_model_slug(),
            "size": self.size.get() or "4K",
            "aspect_ratio": self.aspect.get() or "match_input_image",
            "sequential_image_generation": self.sequential.get(),
            "max_images": max_images,
            "init_images_base64": refs_b64,
            "token": token,
        }
        self._last_refs_b64 = list(refs_b64)
        self.show_original.set(0)
        self._clear_generated_previews_state()
        run_id = self._record_generation_run_start(calls, prompt)
        self._maybe_append_active_task(kind="generate")
        self._autosave_seq = 0
        self._set_busy(True)
        self.set_status("Генерация...")
        _log("generate", {"calls": calls, "max_images": max_images, **sanitize_payload(payload)})
        generate_fn = resolve_generate_fn()

        def _progress(stage: str, fields: dict) -> None:
            label = STAGE_LABELS.get(stage, stage)
            extra = ""
            if "call_index" in fields and "calls" in fields:
                extra = f" ({fields['call_index']}/{fields['calls']})"
            self.ui(self.set_status, f"{label}{extra}")

        def _partial(images: list[str], done: int, total: int, failures: int) -> None:
            self.ui(self._append_generated_images_ui, images, done=done, calls=total, failures=failures)

        def _run() -> None:
            try:
                result = self._gen_controller.run(
                    payload, calls=calls, on_progress=_progress, on_partial=_partial, generate_fn=generate_fn,
                )
                if result.cancelled:
                    self.ui(self.set_status, "Генерация отменена")
                    self.ui(
                        self._finalize_run,
                        run_id,
                        status="canceled",
                        images=len(result.images),
                        failures=result.failures,
                        elapsed_s=result.elapsed_s,
                    )
                    if result.images:
                        self.ui(
                            self._finish_generation_ui,
                            list(result.images),
                            failures=result.failures,
                            calls=calls,
                            elapsed_s=result.elapsed_s,
                        )
                    return
                self.ui(self._finish_generation_ui, list(result.images), failures=result.failures, calls=calls, elapsed_s=result.elapsed_s)
                self.ui(self._finalize_run, run_id, status="done" if not result.failures else "partial", images=len(result.images), failures=result.failures, elapsed_s=result.elapsed_s)
            except Exception as exc:
                if "canceled" in str(exc).lower():
                    self.ui(self.set_status, "Генерация отменена")
                    self.ui(self._finalize_run, run_id, status="canceled", images=0, failures=0, elapsed_s=0.0)
                else:
                    _log("generate_error", {"error": str(exc), "traceback": traceback.format_exc()})
                    self.ui(lambda e=exc: messagebox.showerror("Ошибка генерации", str(e)))
                    self.ui(self.set_status, f"Ошибка генерации: {exc}")
                    self.ui(self._finalize_run, run_id, status="error", images=0, failures=calls, elapsed_s=0.0, error=str(exc))
            finally:
                self.ui(self._set_busy, False)
                self.ui(self._persist_session_state)

        self._gen_thread = threading.Thread(target=_run, daemon=True)
        self._gen_thread.start()

    def on_cancel_generation(self) -> None:
        if self._gen_controller.is_busy:
            self._gen_controller.cancel()
            self.set_status("Отмена...")

    def _append_generated_images_ui(self, images_b64: list[str], *, done: int, calls: int, failures: int) -> None:
        new_images = [img for img in images_b64 if img]
        if not new_images:
            return
        had_images = bool(self._last_images_b64)
        current_idx = self._selected_image_index
        self._last_images_b64.extend(new_images)
        if not had_images:
            self._selected_image_index = 0
            self._show_image(0)
        elif not self.show_original.get():
            self._show_image(min(current_idx, len(self._last_images_b64) - 1))
        else:
            self._render_ribbon(self._last_images_b64)
        for img_b64 in new_images:
            self._autosave_single_generated_image(img_b64)

    def _finish_generation_ui(self, combined: list[str], *, failures: int, calls: int, elapsed_s: float) -> None:
        if combined:
            self._last_images_b64 = list(combined)
            self._show_image(max(0, min(self._selected_image_index, len(combined) - 1)))
            if failures:
                self.set_status(f"Готово частично: {len(combined)} изображений, ошибок: {failures}/{calls}")
            else:
                self.set_status(f"Готово: {len(combined)} изображений за {elapsed_s:.1f} с")
            return
        self._clear_generated_previews_state()

    def on_save(self) -> None:
        if not self._last_image_b64:
            messagebox.showinfo("Сохранение", "Нет изображения для сохранения.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if not path:
            return
        with open(path, "wb") as f:
            f.write(base64.b64decode(self._last_image_b64))
        messagebox.showinfo("Сохранено", path)

    def on_save_all(self) -> None:
        if not self._last_images_b64:
            messagebox.showinfo("Сохранение", "Нет изображений для сохранения.")
            return
        folder = filedialog.askdirectory()
        if not folder:
            return
        saved = 0
        for idx, b64 in enumerate(self._last_images_b64, start=1):
            try:
                with open(os.path.join(folder, f"image_{idx:02d}.png"), "wb") as f:
                    f.write(base64.b64decode(b64))
                saved += 1
            except Exception:
                continue
        messagebox.showinfo("Сохранено", f"Сохранено изображений: {saved}")

    def _render_ribbon(self, images_b64: list[str]) -> None:
        if self._preview_panel:
            self._preview_panel.render_ribbon(images_b64, self._selected_image_index)

    def _show_image(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._last_images_b64):
            return
        self._selected_image_index = idx
        self._last_image_b64 = self._last_images_b64[idx]
        self.show_original.set(0)
        if self._preview_panel:
            img = image_from_base64(self._last_image_b64)
            self._preview_panel.set_image(
                img,
                source=f"Результат {idx + 1}/{len(self._last_images_b64)}",
                selected_index=idx,
            )
            self._preview_panel.render_ribbon(self._last_images_b64, idx)

    def actual_preview_size(self) -> None:
        if self._preview_panel:
            self._preview_panel.fit_actual_size()

    def reset_preview_position(self) -> None:
        if self._preview_panel:
            self._preview_panel.reset_position()

    def _attach_context_menu(self, widget) -> None:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Вставить", command=lambda: widget.event_generate("<<Paste>>"))

        def _popup(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        widget.bind("<Button-3>", _popup)

    def _on_add_pipeline(self) -> None:
        name = simpledialog.askstring("Пайплайн", "Имя пайплайна:", parent=self)
        if not name or not name.strip():
            return
        self._sync_active_branch_from_ui()
        pid = _entity_id("pip")
        existing_slugs = {str(p.get("slug") or "") for p in self._pipelines}
        slug = _unique_slug(_slugify(name.strip(), "pipeline"), existing_slugs)
        bid, sid = _entity_id("br"), _entity_id("stg")
        from seedream_desktop.project_store import _empty_branch_dict, _empty_stage_dict, _empty_pipeline_dict

        br = _empty_branch_dict(branch_id=bid, name="main", slug="main", parent_branch_id=None)
        st = _empty_stage_dict(sid, "Концепт", "concept", br)
        pipe = _empty_pipeline_dict(pid, name.strip(), slug, st)
        self._pipelines.append(pipe)
        self._active_pipeline_id, self._active_stage_id, self._active_branch_id = pid, sid, bid
        self._apply_active_branch_to_ui()
        self._persist_session_state()

    def _on_add_stage(self) -> None:
        p = self._get_active_pipeline()
        if not p:
            return
        name = simpledialog.askstring("Этап", "Имя этапа:", parent=self)
        if not name or not name.strip():
            return
        self._sync_active_branch_from_ui()
        from seedream_desktop.project_store import _empty_branch_dict, _empty_stage_dict

        sid, bid = _entity_id("stg"), _entity_id("br")
        used = {str(s.get("slug") or "") for s in (p.get("stages") or [])}
        st_slug = _unique_slug(_slugify(name.strip(), "stage"), used)
        br = _empty_branch_dict(branch_id=bid, name="main", slug="main", parent_branch_id=None)
        st = _empty_stage_dict(sid, name.strip(), st_slug, br)
        p.setdefault("stages", []).append(st)
        self._active_stage_id, self._active_branch_id = sid, bid
        p["active_stage_id"] = sid
        self._apply_active_branch_to_ui()
        self._persist_session_state()

    def _on_new_branch(self) -> None:
        st = self._get_active_stage()
        if not st:
            return
        self._sync_active_branch_from_ui()
        name = simpledialog.askstring("Ветка", "Имя новой ветки:", parent=self)
        if not name or not name.strip():
            return
        from seedream_desktop.project_store import _empty_branch_dict

        bid = _entity_id("br")
        used = {str(b.get("slug") or "") for b in (st.get("branches") or [])}
        slug = _unique_slug(_slugify(name.strip(), "branch"), used)
        br = _empty_branch_dict(bid, name.strip(), slug, None)
        st.setdefault("branches", []).append(br)
        self._active_branch_id = bid
        st["active_branch_id"] = bid
        self._apply_active_branch_to_ui()
        self._persist_session_state()

    def _on_new_child_branch(self) -> None:
        st = self._get_active_stage()
        parent = self._get_active_branch()
        if not st or not parent:
            return
        self._sync_active_branch_from_ui()
        name = simpledialog.askstring("Дочерняя ветка", "Имя ветки:", parent=self)
        if not name or not name.strip():
            return
        from seedream_desktop.project_store import _empty_branch_dict

        bid = _entity_id("br")
        used = {str(b.get("slug") or "") for b in (st.get("branches") or [])}
        slug = _unique_slug(_slugify(name.strip(), "branch"), used)
        br = _empty_branch_dict(bid, name.strip(), slug, str(parent.get("id")))
        br["prompt_snapshot"] = str(parent.get("prompt_snapshot") or "")
        br["prompt_enhanced_snapshot"] = str(parent.get("prompt_enhanced_snapshot") or "")
        br["use_enhanced"] = int(parent.get("use_enhanced", 0) or 0)
        br["refs_snapshot"] = copy.deepcopy(parent.get("refs_snapshot") or [])
        br["gen_snapshot"] = copy.deepcopy(parent.get("gen_snapshot") or {})
        st.setdefault("branches", []).append(br)
        self._active_branch_id = bid
        st["active_branch_id"] = bid
        self._apply_active_branch_to_ui()
        self._persist_session_state()

    def _on_rename_branch(self) -> None:
        iid = self._pipeline_panel.selected_iid() if self._pipeline_panel else None
        if not iid:
            return
        kind, eid = self._tree_node_kind(iid)
        if kind != "branch":
            messagebox.showinfo("Переименование", "Выберите ветку в дереве.")
            return
        for p in self._pipelines:
            for s in p.get("stages") or []:
                br = next((b for b in s.get("branches") or [] if str(b.get("id")) == eid), None)
                if br:
                    name = simpledialog.askstring("Переименовать", "Новое имя:", parent=self, initialvalue=str(br.get("name") or ""))
                    if not name or not name.strip():
                        return
                    br["name"] = name.strip()
                    self._refresh_tree()
                    self._persist_session_state()
                    return

    def _on_delete_node(self) -> None:
        iid = self._pipeline_panel.selected_iid() if self._pipeline_panel else None
        if not iid:
            return
        kind, eid = self._tree_node_kind(iid)
        if kind == "pipeline" and len(self._pipelines) <= 1:
            messagebox.showinfo("Удаление", "Нельзя удалить последний пайплайн.")
            return
        if kind == "stage":
            p = self._get_active_pipeline()
            if p and len(p.get("stages") or []) <= 1:
                messagebox.showinfo("Удаление", "Нельзя удалить последний этап.")
                return
        if kind == "branch":
            st = self._get_active_stage()
            if st and len(st.get("branches") or []) <= 1:
                messagebox.showinfo("Удаление", "Нельзя удалить последнюю ветку.")
                return
        if not messagebox.askyesno("Удаление", "Удалить выбранный элемент из проекта?"):
            return
        self._sync_active_branch_from_ui()
        if kind == "pipeline":
            self._pipelines = [p for p in self._pipelines if str(p.get("id")) != eid]
        elif kind == "stage":
            p = self._get_active_pipeline()
            if p:
                p["stages"] = [s for s in p.get("stages") or [] if str(s.get("id")) != eid]
        elif kind == "branch":
            st = self._get_active_stage()
            if st:
                st["branches"] = [b for b in st.get("branches") or [] if str(b.get("id")) != eid]
        self._pipelines, self._active_pipeline_id, self._active_stage_id, self._active_branch_id = repair_pipeline_invariants(
            self._pipelines, self._active_pipeline_id, self._active_stage_id, self._active_branch_id
        )
        self._apply_active_branch_to_ui()
        self._persist_session_state()

    def _on_close(self) -> None:
        self._persist_session_state()
        self.destroy()
