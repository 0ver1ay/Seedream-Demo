from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Callable

import tkinter as tk
from tkinter import ttk

from seedream_desktop.theme import PALETTE, apply_theme

if TYPE_CHECKING:
    from seedream_desktop.application import SeedreamApp


def restore_session_async(
    app: SeedreamApp,
    *,
    session_path: str,
    load_payload: Callable[[], dict | None],
    on_loaded: Callable[[dict], None],
    on_empty: Callable[[], None],
) -> None:
    if not os.path.isfile(session_path):
        on_empty()
        return

    splash = tk.Toplevel(app)
    splash.title("Seedream")
    splash.transient(app)
    splash.resizable(False, False)
    apply_theme(splash)
    splash.configure(bg=PALETTE["bg"])
    frame = ttk.Frame(splash, style="Elevated.TFrame", padding=28)
    frame.pack()
    ttk.Label(frame, text="Seedream", style="Brand.TLabel").pack()
    ttk.Label(frame, text="Восстановление сессии…", style="Header.TLabel").pack(pady=(10, 0))
    ttk.Label(frame, text="Загружаем последний проект", style="ElevatedMuted.TLabel").pack(pady=(6, 0))
    pb = ttk.Progressbar(frame, mode="indeterminate", length=260)
    pb.pack(pady=(14, 0))
    pb.start(10)
    splash.update_idletasks()
    w, h = splash.winfo_width(), splash.winfo_height()
    x = app.winfo_x() + max(0, (app.winfo_width() - w) // 2)
    y = app.winfo_y() + max(0, (app.winfo_height() - h) // 2)
    splash.geometry(f"+{x}+{y}")

    def _worker() -> None:
        payload = load_payload()

        def _finish() -> None:
            try:
                if not app.winfo_exists():
                    return
                pb.stop()
                splash.destroy()
            except tk.TclError:
                return
            if payload:
                on_loaded(payload)
            else:
                on_empty()

        try:
            if app.winfo_exists():
                app.after(0, _finish)
        except (tk.TclError, RuntimeError):
            pass

    threading.Thread(target=_worker, daemon=True).start()
