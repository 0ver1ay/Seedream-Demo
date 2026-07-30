from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable

import tkinter as tk
from tkinter import messagebox, ttk

from seedream_desktop.app_config import SECRETS_FILE
from seedream_desktop.credentials import apply_seedream_env_from_secrets, save_secrets
from seedream_desktop.theme import apply_theme

if TYPE_CHECKING:
    from seedream_desktop.application import SeedreamApp


def _current_server_url(secrets: dict) -> str:
    env = (os.environ.get("SEEDREAM_SERVER") or "").strip()
    if env:
        return env
    saved = secrets.get("SEEDREAM_SERVER")
    if isinstance(saved, str):
        return saved.strip()
    return ""


def open_settings_dialog(
    app: SeedreamApp,
    *,
    on_saved: Callable[[dict], None],
) -> None:
    if app._settings_window is not None and app._settings_window.winfo_exists():
        app._settings_window.lift()
        return

    window = tk.Toplevel(app)
    window.title("Настройки")
    window.geometry("520x480")
    window.transient(app)
    window.grab_set()
    apply_theme(window)
    app._settings_window = window

    body = ttk.Frame(window, padding=20)
    body.pack(fill=tk.BOTH, expand=True)

    tokens = ttk.LabelFrame(body, text=" API токены ", style="Card.TLabelframe", padding=14)
    tokens.pack(fill=tk.X)
    token_vars = {
        "replicate": tk.StringVar(value=app.secrets.get("replicate", "")),
        "openai": tk.StringVar(value=app.secrets.get("openai", "")),
        "google": tk.StringVar(value=app.secrets.get("google", "")),
    }
    row = 0
    for key, label in (("replicate", "Replicate"), ("openai", "OpenAI"), ("google", "Google")):
        ttk.Label(tokens, text=label, style="SurfaceMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(tokens, textvariable=token_vars[key], show="*", width=48).grid(row=row + 1, column=0, sticky="we", pady=(4, 0))
        row += 2
    ttk.Label(
        tokens,
        text="Приоритет: переменные окружения, затем secrets.json",
        style="SurfaceMuted.TLabel",
    ).grid(row=row, column=0, sticky="we", pady=(10, 0))
    tokens.columnconfigure(0, weight=1)

    server_frame = ttk.LabelFrame(body, text=" Сервер (опционально) ", style="Card.TLabelframe", padding=14)
    server_frame.pack(fill=tk.X, pady=(14, 0))
    server_var = tk.StringVar(value=_current_server_url(app.secrets))
    ttk.Label(server_frame, text="SEEDREAM_SERVER", style="SurfaceMuted.TLabel").pack(anchor="w")
    ttk.Entry(server_frame, textvariable=server_var, width=48).pack(fill=tk.X, pady=(6, 0))
    ttk.Label(
        server_frame,
        text="Если указан URL, desktop ходит в HTTP API вместо прямого core.",
        style="SurfaceMuted.TLabel",
        wraplength=460,
    ).pack(anchor="w", pady=(8, 0))

    def _save() -> None:
        secrets = {k: v.get().strip() for k, v in token_vars.items() if v.get().strip()}
        srv = server_var.get().strip().rstrip("/")
        if srv:
            secrets["SEEDREAM_SERVER"] = srv
            os.environ["SEEDREAM_SERVER"] = srv
        else:
            secrets.pop("SEEDREAM_SERVER", None)
            os.environ.pop("SEEDREAM_SERVER", None)
        save_secrets(SECRETS_FILE, secrets)
        apply_seedream_env_from_secrets(secrets)
        on_saved(secrets)
        app.set_status("Настройки сохранены")
        messagebox.showinfo("Сохранено", "Настройки сохранены. Перезапустите генерацию при смене сервера.")

    def _close() -> None:
        app._settings_window = None
        window.destroy()

    actions = ttk.Frame(body)
    actions.pack(fill=tk.X, pady=(20, 0))
    ttk.Button(actions, text="Сохранить", style="Accent.TButton", command=_save).pack(side=tk.LEFT)
    ttk.Button(actions, text="Закрыть", style="Ghost.TButton", command=_close).pack(side=tk.RIGHT)
    window.protocol("WM_DELETE_WINDOW", _close)
