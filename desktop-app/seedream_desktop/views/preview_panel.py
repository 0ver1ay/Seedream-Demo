from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import tkinter as tk
from PIL import Image, ImageTk
from tkinter import ttk

from seedream_desktop.images_util import image_from_base64
from seedream_desktop.theme import FONTS, PALETTE, style_canvas, style_thumb_button

if TYPE_CHECKING:
    from PIL import Image as PILImage


class PreviewPanel:
    """Профессиональный просмотр: fit / 100% / zoom к курсору / pan без лагов."""

    _MIN_SCALE = 0.05
    _MAX_SCALE = 12.0
    _PAD = 16

    def __init__(self, parent: ttk.Frame) -> None:
        self._current_full_image: PILImage.Image | None = None
        self._scale = 1.0
        self._fit_mode = True
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._drag_origin: tuple[int, int] | None = None
        self._drag_offset_origin: tuple[float, float] | None = None
        self._preview_source = "Нет изображения"
        self._preview_image: ImageTk.PhotoImage | None = None
        self._image_item: int | None = None
        self._thumb_imgs: list[ImageTk.PhotoImage] = []
        self._selected_index = 0
        self._on_thumb_select: Callable[[int], None] | None = None
        self._render_job: str | None = None
        self._last_canvas_size = (0, 0)
        self._checker_ids: list[int] = []

        card = ttk.LabelFrame(parent, text=" Предпросмотр ", style="Card.TLabelframe", padding=12)
        card.pack(fill=tk.BOTH, expand=True)
        self._card = card

        # Сначала резервируем низ (Результаты/История), иначе canvas съедает высоту.
        bottom_nb = ttk.Notebook(card)
        bottom_nb.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        results_tab = ttk.Frame(bottom_nb, style="Surface.TFrame")
        self.history_tab = ttk.Frame(bottom_nb, style="Surface.TFrame")
        bottom_nb.add(results_tab, text="Результаты")
        bottom_nb.add(self.history_tab, text="История")
        self._bottom_nb = bottom_nb

        ribbon = ttk.Frame(results_tab, style="Surface.TFrame")
        ribbon.pack(fill=tk.BOTH, expand=True, padx=4, pady=6)
        self.ribbon_scroll = ttk.Scrollbar(ribbon, orient=tk.HORIZONTAL)
        self.ribbon_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.ribbon_canvas = tk.Canvas(ribbon, height=100, xscrollcommand=self.ribbon_scroll.set)
        style_canvas(self.ribbon_canvas, variant="surface")
        self.ribbon_canvas.pack(side=tk.TOP, fill=tk.X)
        self.ribbon_scroll.config(command=self.ribbon_canvas.xview)
        self.ribbon_inner = ttk.Frame(self.ribbon_canvas, style="Surface.TFrame")
        self.ribbon_canvas.create_window((0, 0), window=self.ribbon_inner, anchor="nw")
        self.ribbon_inner.bind(
            "<Configure>",
            lambda _e: self.ribbon_canvas.configure(scrollregion=self.ribbon_canvas.bbox("all")),
        )

        tools = ttk.Frame(card, style="Surface.TFrame")
        tools.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(tools, text="Просмотр", style="Section.TLabel").pack(side=tk.LEFT)
        self._btn_fit = ttk.Button(tools, text="Вписать", style="Chip.TButton", width=8)
        self._btn_fit.pack(side=tk.LEFT, padx=(12, 0))
        self._btn_actual = ttk.Button(tools, text="100%", style="Chip.TButton", width=5)
        self._btn_actual.pack(side=tk.LEFT, padx=(6, 0))
        self._btn_zoom_out = ttk.Button(tools, text="−", style="Chip.TButton", width=3)
        self._btn_zoom_out.pack(side=tk.LEFT, padx=(6, 0))
        self._btn_zoom_in = ttk.Button(tools, text="+", style="Chip.TButton", width=3)
        self._btn_zoom_in.pack(side=tk.LEFT, padx=(4, 0))
        self.meta = ttk.Label(tools, text="Нет изображения", style="SurfaceMuted.TLabel")
        self.meta.pack(side=tk.RIGHT)

        stage = ttk.Frame(card, style="Surface.TFrame")
        stage.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(10, 0))
        stage.rowconfigure(0, weight=1)
        stage.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(stage, highlightthickness=0)
        style_canvas(self.canvas, variant="preview")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<MouseWheel>", self._on_zoom_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.12))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.12))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.fit_to_window())
        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Motion>", self._on_motion)
        self._draw_empty_state()

    def bind_controls(
        self,
        *,
        on_actual_size: Callable[[], None],
        on_reset: Callable[[], None],
        on_thumb: Callable[[int], None],
    ) -> None:
        self._btn_actual.config(command=on_actual_size)
        self._btn_fit.config(command=on_reset)
        self._btn_zoom_in.config(command=lambda: self._zoom_center(1.15))
        self._btn_zoom_out.config(command=lambda: self._zoom_center(1 / 1.15))
        self._on_thumb_select = on_thumb

    def set_image(self, image: PILImage.Image | None, *, source: str, selected_index: int = 0) -> None:
        self._current_full_image = image
        self._preview_source = source
        self._selected_index = selected_index
        self._fit_mode = True
        self._offset_x = 0.0
        self._offset_y = 0.0
        self.fit_to_window()

    def clear(self) -> None:
        self._current_full_image = None
        self._preview_source = "Нет изображения"
        self._preview_image = None
        self._image_item = None
        self._thumb_imgs = []
        self._fit_mode = True
        self._offset_x = 0.0
        self._offset_y = 0.0
        for w in list(self.ribbon_inner.children.values()):
            w.destroy()
        self._draw_empty_state()
        self.meta.config(text="Нет изображения")

    def render_ribbon(self, images_b64: list[str], selected_index: int) -> None:
        self._selected_index = selected_index
        for w in list(self.ribbon_inner.children.values()):
            w.destroy()
        self._thumb_imgs = []
        for idx, b64 in enumerate(images_b64):
            try:
                img = image_from_base64(b64)
                thumb = img.copy()
                thumb.thumbnail((120, 84), Image.LANCZOS)
                tkimg = ImageTk.PhotoImage(thumb)
                self._thumb_imgs.append(tkimg)
                btn = tk.Button(
                    self.ribbon_inner,
                    image=tkimg,
                    text=f"#{idx + 1}",
                    compound=tk.TOP,
                    command=lambda i=idx: self._on_thumb_select(i) if self._on_thumb_select else None,
                )
                style_thumb_button(btn, selected=idx == selected_index)
                btn.pack(side=tk.LEFT, padx=5, pady=6)
            except Exception:
                continue
        self.ribbon_canvas.update_idletasks()
        bbox = self.ribbon_canvas.bbox("all")
        if bbox:
            self.ribbon_canvas.configure(scrollregion=bbox)

    def fit_to_window(self) -> None:
        self._fit_mode = True
        self._offset_x = 0.0
        self._offset_y = 0.0
        if self._current_full_image is None:
            self._draw_empty_state()
            return
        cw, ch = self._canvas_size()
        if cw < 80 or ch < 80:
            retries = getattr(self, "_fit_retries", 0)
            if retries < 20:
                self._fit_retries = retries + 1
                self.canvas.after(50, self.fit_to_window)
            return
        self._fit_retries = 0
        self._scale = self._fit_scale()
        self._render_image(high_quality=True)
        self._update_meta()

    def fit_actual_size(self) -> None:
        """100% — один пиксель изображения = один пиксель экрана."""
        if self._current_full_image is None:
            return
        self._fit_mode = False
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._render_image(high_quality=True)
        self._update_meta()

    def reset_position(self) -> None:
        self.fit_to_window()

    # Back-compat alias used by older callers
    def render(self) -> None:
        if self._fit_mode:
            self.fit_to_window()
        else:
            self._render_image(high_quality=True)
            self._update_meta()

    def _canvas_size(self) -> tuple[int, int]:
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        return w, h

    def _fit_scale(self) -> float:
        if self._current_full_image is None:
            return 1.0
        cw, ch = self._canvas_size()
        iw, ih = self._current_full_image.size
        if iw <= 0 or ih <= 0:
            return 1.0
        avail_w = max(40, cw - self._PAD * 2)
        avail_h = max(40, ch - self._PAD * 2)
        return max(self._MIN_SCALE, min(avail_w / iw, avail_h / ih))

    def _draw_empty_state(self) -> None:
        self.canvas.delete("all")
        self._image_item = None
        self._checker_ids.clear()
        cw, ch = self._canvas_size()
        self._draw_checkerboard(cw, ch)
        cx, cy = cw // 2, ch // 2
        self.canvas.create_text(
            cx,
            cy - 14,
            text="Предпросмотр",
            fill=PALETTE["text_secondary"],
            font=FONTS["heading"],
            anchor="center",
        )
        self.canvas.create_text(
            cx,
            cy + 14,
            text="Сгенерируйте изображение или выберите референс",
            fill=PALETTE["text_muted"],
            font=FONTS["ui"],
            anchor="center",
        )

    def _draw_checkerboard(self, cw: int, ch: int) -> None:
        size = 14
        c1, c2 = PALETTE["checker_a"], PALETTE["checker_b"]
        for y in range(0, ch + size, size):
            for x in range(0, cw + size, size):
                color = c1 if ((x // size) + (y // size)) % 2 == 0 else c2
                item = self.canvas.create_rectangle(x, y, x + size, y + size, fill=color, outline="")
                self._checker_ids.append(item)

    def _schedule_render(self, *, high_quality: bool = False, delay_ms: int = 16) -> None:
        if self._render_job is not None:
            try:
                self.canvas.after_cancel(self._render_job)
            except Exception:
                pass
        self._render_job = self.canvas.after(
            delay_ms,
            lambda: self._render_image(high_quality=high_quality),
        )

    def _render_image(self, *, high_quality: bool = True) -> None:
        self._render_job = None
        if self._current_full_image is None:
            self._draw_empty_state()
            return
        cw, ch = self._canvas_size()
        iw, ih = self._current_full_image.size
        scale = max(self._MIN_SCALE, min(self._MAX_SCALE, self._scale))
        self._scale = scale
        tw = max(1, int(round(iw * scale)))
        th = max(1, int(round(ih * scale)))

        # Не раздувать bitmap без нужды при огромном зуме — ограничим рабочий рендер
        max_side = 6000
        if max(tw, th) > max_side:
            factor = max_side / max(tw, th)
            tw = max(1, int(tw * factor))
            th = max(1, int(th * factor))

        resample = Image.LANCZOS if high_quality else Image.BILINEAR
        rendered = self._current_full_image.resize((tw, th), resample)
        self._preview_image = ImageTk.PhotoImage(rendered)

        self.canvas.delete("all")
        self._checker_ids.clear()
        self._draw_checkerboard(cw, ch)
        x = cw / 2 + self._offset_x
        y = ch / 2 + self._offset_y
        self._image_item = self.canvas.create_image(x, y, image=self._preview_image, anchor="center")
        self._update_meta()

    def _update_meta(self) -> None:
        if self._current_full_image is None:
            self.meta.config(text="Нет изображения")
            return
        iw, ih = self._current_full_image.size
        pct = int(round(self._scale * 100))
        mode = "вписан" if self._fit_mode else "свободно"
        self.meta.config(text=f"{self._preview_source}  |  {iw}x{ih}  |  {pct}%  |  {mode}")

    def _place_image_item(self) -> None:
        if self._image_item is None:
            return
        cw, ch = self._canvas_size()
        self.canvas.coords(self._image_item, cw / 2 + self._offset_x, ch / 2 + self._offset_y)

    def _zoom_at(self, cx: float, cy: float, factor: float) -> None:
        if self._current_full_image is None:
            return
        self._fit_mode = False
        cw, ch = self._canvas_size()
        old = self._scale
        new = max(self._MIN_SCALE, min(self._MAX_SCALE, old * factor))
        if abs(new - old) < 1e-9:
            return
        # Точка под курсором (в системе offset) должна остаться на месте
        # before: screen = center + offset + (img_local * old)
        # after:  screen = center + offset' + (img_local * new)
        rel_x = cx - (cw / 2 + self._offset_x)
        rel_y = cy - (ch / 2 + self._offset_y)
        self._offset_x += rel_x - rel_x * (new / old)
        self._offset_y += rel_y - rel_y * (new / old)
        self._scale = new
        self._schedule_render(high_quality=False, delay_ms=20)
        self.canvas.after(140, lambda: self._schedule_render(high_quality=True, delay_ms=0))
        self._update_meta()

    def _zoom_center(self, factor: float) -> None:
        cw, ch = self._canvas_size()
        self._zoom_at(cw / 2, ch / 2, factor)

    def _on_configure(self, event) -> None:
        size = (event.width, event.height)
        if size == self._last_canvas_size or event.width < 2 or event.height < 2:
            return
        self._last_canvas_size = size
        if self._current_full_image is None:
            self._draw_empty_state()
            return
        if self._fit_mode:
            if self._render_job is not None:
                try:
                    self.canvas.after_cancel(self._render_job)
                except Exception:
                    pass
            self._render_job = self.canvas.after(40, self.fit_to_window)
        else:
            self._schedule_render(high_quality=True, delay_ms=40)

    def _on_press(self, event) -> None:
        if self._current_full_image is None:
            return
        self._drag_origin = (event.x, event.y)
        self._drag_offset_origin = (self._offset_x, self._offset_y)
        self.canvas.config(cursor="fleur")

    def _on_drag(self, event) -> None:
        if self._current_full_image is None or self._drag_origin is None or self._drag_offset_origin is None:
            return
        self._fit_mode = False
        dx = event.x - self._drag_origin[0]
        dy = event.y - self._drag_origin[1]
        self._offset_x = self._drag_offset_origin[0] + dx
        self._offset_y = self._drag_offset_origin[1] + dy
        # Сдвиг без перерисовки bitmap — плавно
        if self._image_item is not None:
            self._place_image_item()
        else:
            self._render_image(high_quality=False)

    def _on_release(self, _event) -> None:
        self._drag_origin = None
        self._drag_offset_origin = None
        self.canvas.config(cursor="")

    def _on_motion(self, _event) -> None:
        if self._current_full_image is not None and self._drag_origin is None:
            self.canvas.config(cursor="hand2")

    def _on_zoom_wheel(self, event) -> str:
        if self._current_full_image is None:
            return "break"
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self._zoom_at(event.x, event.y, factor)
        return "break"
