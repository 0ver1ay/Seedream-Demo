from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import tkinter as tk
from PIL import Image, ImageTk
from tkinter import ttk

from seedream_desktop.images_util import image_from_base64
from seedream_desktop.theme import style_canvas, style_thumb_button

if TYPE_CHECKING:
    from seedream_desktop.models import RefItem


class RefsPanel:
    """Горизонтальная лента миниатюр референсов с drag-reorder."""

    def __init__(
        self,
        *,
        get_refs: Callable[[], list[RefItem]],
        get_workspace: Callable[[], str],
        on_select: Callable[[int], None],
        on_reorder: Callable[[int, int], None],
        on_persist: Callable[[], None],
    ) -> None:
        self._get_refs = get_refs
        self._get_workspace = get_workspace
        self._on_select = on_select
        self._on_reorder = on_reorder
        self._on_persist = on_persist
        self._thumb_imgs: list[ImageTk.PhotoImage] = []
        self._ref_frames: list[ttk.Frame] = []
        self._drag_source: int | None = None
        self._drag_target: int | None = None
        self._selected_index = -1
        self.label: ttk.Label | None = None
        self.canvas: tk.Canvas | None = None
        self.inner: ttk.Frame | None = None

    def build(self, refs_frame: ttk.LabelFrame, *, on_add: Callable[[], None]) -> None:
        refs_top = ttk.Frame(refs_frame, style="Surface.TFrame")
        refs_top.pack(fill=tk.X)
        self.label = ttk.Label(refs_top, text="", style="SurfaceMuted.TLabel")
        self.label.pack(side=tk.LEFT)
        ttk.Button(refs_top, text="Добавить", style="Secondary.TButton", command=on_add).pack(side=tk.RIGHT)
        self.canvas = tk.Canvas(refs_frame, height=84)
        style_canvas(self.canvas, variant="input")
        self.inner = ttk.Frame(self.canvas, style="Surface.TFrame")
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(fill=tk.X, pady=(10, 0))
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

    def set_label(self, text: str) -> None:
        if self.label:
            self.label.config(text=text)

    def set_selected_index(self, idx: int) -> None:
        self._selected_index = idx

    def refresh(self) -> None:
        if not self.inner or not self.canvas:
            return
        for w in list(self.inner.children.values()):
            w.destroy()
        self._thumb_imgs = []
        self._ref_frames = []
        refs = self._get_refs()
        ws = self._get_workspace()
        for idx, ref in enumerate(refs):
            frame = ttk.Frame(self.inner, style="Surface.TFrame", padding=2)
            frame.grid(row=0, column=idx, padx=4)
            self._ref_frames.append(frame)
            highlight = idx == self._selected_index or idx == self._drag_target
            try:
                b64 = ref.load_base64(ws)
                if b64:
                    img = image_from_base64(b64)
                    img.thumbnail((72, 72), Image.LANCZOS)
                    tkimg = ImageTk.PhotoImage(img)
                    self._thumb_imgs.append(tkimg)
                    btn = tk.Button(
                        frame,
                        image=tkimg,
                        text=ref.name[:12],
                        compound=tk.TOP,
                    )
                    style_thumb_button(btn, selected=highlight)
                    btn.pack()
                    btn.bind("<ButtonPress-1>", lambda e, i=idx: self._on_press(i, e))
                    btn.bind("<B1-Motion>", self._on_motion)
                    btn.bind("<ButtonRelease-1>", self._on_release)
                else:
                    ttk.Label(frame, text=ref.name[:12], style="SurfaceMuted.TLabel").pack()
            except Exception:
                ttk.Label(frame, text=ref.name[:12], style="SurfaceMuted.TLabel").pack()
        self._on_inner_configure()

    def _on_inner_configure(self, _event=None) -> None:
        if self.canvas:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _index_at_x(self, root_x: int) -> int | None:
        for idx, frame in enumerate(self._ref_frames):
            x1 = frame.winfo_rootx()
            x2 = x1 + frame.winfo_width()
            if x1 <= root_x <= x2:
                return idx
        return None

    def _on_press(self, idx: int, event) -> None:
        self._drag_source = idx
        self._drag_target = idx
        self._selected_index = idx
        self._on_select(idx)

    def _on_motion(self, event) -> None:
        if self._drag_source is None:
            return
        target = self._index_at_x(event.x_root)
        if target is None:
            return
        if target != self._drag_target:
            self._drag_target = target
            self.refresh()

    def _on_release(self, event) -> None:
        self._finish_drag(event.x_root)

    def _on_canvas_release(self, event) -> None:
        if self._drag_source is not None:
            self._finish_drag(event.x_root)

    def _finish_drag(self, root_x: int) -> None:
        if self._drag_source is None:
            return
        target = self._index_at_x(root_x)
        source = self._drag_source
        self._drag_source = None
        self._drag_target = None
        if target is not None and target != source:
            self._on_reorder(source, target)
            self._selected_index = target
            self._on_persist()
        self.refresh()
