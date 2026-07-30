from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Literal

# Студийная палитра: тёплый уголь + янтарь (без фиолетового AI-клише)
PALETTE = {
    "bg": "#0a0b0d",
    "bg_elevated": "#101114",
    "surface": "#16181d",
    "surface_hover": "#1e2128",
    "surface_input": "#1a1c22",
    "border": "#2c303a",
    "border_subtle": "#22252c",
    "text": "#f3f1ec",
    "text_secondary": "#c4c0b6",
    "text_muted": "#7f7b72",
    "accent": "#e8a54b",
    "accent_hover": "#f0b862",
    "accent_soft": "#3a2e1c",
    "accent_secondary": "#6fbfa8",
    "on_accent": "#1a1208",
    "danger": "#e87a6a",
    "danger_hover": "#f08a7c",
    "success": "#7bc47f",
    "preview_bg": "#070809",
    "selection": "#3a2e1c",
    "thumb_bg": "#1c1f26",
    "thumb_border": "#343842",
    "thumb_selected": "#3a2e1c",
    "checker_a": "#0c0d10",
    "checker_b": "#12141a",
    "badge_bg": "#1e2128",
    "badge_fg": "#c4c0b6",
}

FONTS = {
    "ui": ("Segoe UI", 10),
    "ui_sm": ("Segoe UI", 9),
    "heading": ("Segoe UI", 15, "bold"),
    "title": ("Segoe UI", 11, "bold"),
    "subheading": ("Segoe UI", 9, "bold"),
    "brand": ("Segoe UI", 16, "bold"),
    "brand_sub": ("Segoe UI", 11),
    "mono": ("Consolas", 9),
}


def _option_colors(root: tk.Misc) -> None:
    root.option_add("*Background", PALETTE["bg"])
    root.option_add("*Foreground", PALETTE["text"])
    root.option_add("*selectBackground", PALETTE["selection"])
    root.option_add("*selectForeground", PALETTE["text"])
    root.option_add("*insertBackground", PALETTE["accent_secondary"])
    root.option_add("*Menu.background", PALETTE["surface"])
    root.option_add("*Menu.foreground", PALETTE["text"])
    root.option_add("*Menu.activeBackground", PALETTE["surface_hover"])
    root.option_add("*Menu.activeForeground", PALETTE["text"])
    root.option_add("*TCombobox*Listbox.background", PALETTE["surface_input"])
    root.option_add("*TCombobox*Listbox.foreground", PALETTE["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", PALETTE["accent_soft"])
    root.option_add("*TCombobox*Listbox.selectForeground", PALETTE["text"])


def apply_theme(root: tk.Tk | tk.Toplevel) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=PALETTE["bg"])
    _option_colors(root)

    p = PALETTE
    f = FONTS

    style.configure(".", background=p["bg"], foreground=p["text"], font=f["ui"])
    style.configure("TFrame", background=p["bg"])
    style.configure("Surface.TFrame", background=p["surface"])
    style.configure("Elevated.TFrame", background=p["bg_elevated"])
    style.configure("Stage.TFrame", background=p["preview_bg"])

    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Surface.TLabel", background=p["surface"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"], font=f["ui_sm"])
    style.configure("SurfaceMuted.TLabel", background=p["surface"], foreground=p["text_muted"], font=f["ui_sm"])
    style.configure("Header.TLabel", background=p["bg_elevated"], foreground=p["text"], font=f["heading"])
    style.configure("Title.TLabel", background=p["bg_elevated"], foreground=p["text_secondary"], font=f["title"])
    style.configure("ElevatedMuted.TLabel", background=p["bg_elevated"], foreground=p["text_muted"], font=f["ui_sm"])
    style.configure("Section.TLabel", background=p["surface"], foreground=p["text_secondary"], font=f["subheading"])
    style.configure("Brand.TLabel", background=p["bg_elevated"], foreground=p["accent"], font=f["brand"])
    style.configure("BrandSub.TLabel", background=p["bg_elevated"], foreground=p["text_secondary"], font=f["brand_sub"])
    style.configure("Badge.TLabel", background=p["badge_bg"], foreground=p["badge_fg"], font=f["ui_sm"], padding=(8, 3))
    style.configure("Status.TLabel", background=p["bg_elevated"], foreground=p["text_secondary"], font=f["ui"])

    style.configure(
        "Card.TLabelframe",
        background=p["surface"],
        bordercolor=p["border_subtle"],
        relief="flat",
        borderwidth=1,
        padding=4,
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=p["surface"],
        foreground=p["text_muted"],
        font=f["subheading"],
    )
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border_subtle"], relief="flat")
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["text_muted"], font=f["subheading"])

    style.configure(
        "TButton",
        padding=(12, 8),
        background=p["surface_hover"],
        foreground=p["text"],
        borderwidth=1,
        relief="flat",
        focusthickness=0,
    )
    style.map(
        "TButton",
        background=[("active", p["border"]), ("pressed", p["border_subtle"]), ("disabled", p["surface"])],
        foreground=[("disabled", p["text_muted"])],
        bordercolor=[("active", p["border"]), ("!active", p["border_subtle"])],
    )

    style.configure(
        "Toolbar.TButton",
        padding=(11, 6),
        background=p["bg_elevated"],
        foreground=p["text_secondary"],
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "Toolbar.TButton",
        background=[("active", p["surface_hover"]), ("pressed", p["border_subtle"])],
        foreground=[("active", p["text"])],
        bordercolor=[("active", p["border"]), ("!active", p["border_subtle"])],
    )

    style.configure(
        "Accent.TButton",
        padding=(18, 10),
        background=p["accent"],
        foreground=p["on_accent"],
        borderwidth=0,
        relief="flat",
        font=(f["ui"][0], f["ui"][1], "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("active", p["accent_hover"]), ("pressed", p["accent_soft"]), ("disabled", p["surface_hover"])],
        foreground=[("disabled", p["text_muted"]), ("pressed", p["text"]), ("!disabled", p["on_accent"])],
    )

    style.configure(
        "Secondary.TButton",
        padding=(12, 8),
        background=p["surface_input"],
        foreground=p["text"],
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "Secondary.TButton",
        background=[("active", p["surface_hover"]), ("pressed", p["border_subtle"])],
        foreground=[("active", p["text"])],
        bordercolor=[("active", p["accent"]), ("!active", p["border"])],
    )

    style.configure(
        "Ghost.TButton",
        padding=(11, 7),
        background=p["surface"],
        foreground=p["text_secondary"],
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "Ghost.TButton",
        background=[("active", p["surface_hover"]), ("pressed", p["border_subtle"])],
        foreground=[("active", p["text"])],
        bordercolor=[("active", p["border"]), ("!active", p["border_subtle"])],
    )

    style.configure(
        "Chip.TButton",
        padding=(10, 5),
        background=p["surface_input"],
        foreground=p["text_secondary"],
        borderwidth=1,
        relief="flat",
        font=f["ui_sm"],
    )
    style.map(
        "Chip.TButton",
        background=[("active", p["surface_hover"]), ("pressed", p["border_subtle"])],
        foreground=[("active", p["text"])],
        bordercolor=[("active", p["border"]), ("!active", p["border_subtle"])],
    )
    style.configure(
        "ChipSelected.TButton",
        padding=(10, 5),
        background=p["accent_soft"],
        foreground=p["accent"],
        borderwidth=1,
        relief="flat",
        font=f["ui_sm"],
    )
    style.map(
        "ChipSelected.TButton",
        background=[("active", p["accent"]), ("pressed", p["accent_soft"])],
        foreground=[("active", p["on_accent"]), ("!active", p["accent"])],
        bordercolor=[("active", p["accent"]), ("!active", p["accent"])],
    )

    style.configure(
        "Danger.TButton",
        padding=(11, 7),
        background=p["surface"],
        foreground=p["danger"],
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#2a1a18"), ("pressed", "#3a2220")],
        foreground=[("active", p["danger_hover"])],
        bordercolor=[("active", p["danger"]), ("!active", p["border_subtle"])],
    )

    for name in ("TCheckbutton", "Surface.TCheckbutton"):
        bg = p["surface"] if "Surface" in name else p["bg"]
        style.configure(name, background=bg, foreground=p["text"], focusthickness=0)
        style.map(name, background=[("active", bg)], foreground=[("disabled", p["text_muted"])])

    style.configure("TRadiobutton", background=p["bg"], foreground=p["text"], focusthickness=0)

    style.configure(
        "TCombobox",
        fieldbackground=p["surface_input"],
        background=p["surface_input"],
        foreground=p["text"],
        arrowcolor=p["text_muted"],
        bordercolor=p["border"],
        lightcolor=p["border_subtle"],
        darkcolor=p["border"],
        insertcolor=p["accent_secondary"],
        padding=7,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", p["surface_input"]), ("disabled", p["surface"])],
        foreground=[("disabled", p["text_muted"])],
        bordercolor=[("focus", p["accent"]), ("!focus", p["border"])],
    )

    style.configure(
        "TEntry",
        fieldbackground=p["surface_input"],
        foreground=p["text"],
        bordercolor=p["border"],
        lightcolor=p["border_subtle"],
        darkcolor=p["border"],
        insertcolor=p["accent_secondary"],
        padding=7,
    )
    style.map("TEntry", bordercolor=[("focus", p["accent"]), ("!focus", p["border"])])

    style.configure(
        "Treeview",
        background=p["surface_input"],
        fieldbackground=p["surface_input"],
        foreground=p["text"],
        borderwidth=0,
        rowheight=28,
        font=f["ui"],
    )
    style.configure(
        "Treeview.Heading",
        background=p["surface_hover"],
        foreground=p["text_muted"],
        borderwidth=0,
        relief="flat",
        font=f["subheading"],
    )
    style.map(
        "Treeview",
        background=[("selected", p["accent_soft"])],
        foreground=[("selected", p["accent"])],
    )

    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=p["surface_input"],
        background=p["accent"],
        bordercolor=p["border_subtle"],
        lightcolor=p["accent"],
        darkcolor=p["accent"],
        thickness=4,
    )

    style.configure("TNotebook", background=p["surface"], borderwidth=0, tabmargins=(4, 6, 4, 0))
    style.configure(
        "TNotebook.Tab",
        background=p["surface"],
        foreground=p["text_muted"],
        padding=(16, 8),
        borderwidth=0,
        font=f["ui_sm"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", p["surface_hover"]), ("active", p["surface_input"])],
        foreground=[("selected", p["text"]), ("active", p["text_secondary"])],
        expand=[("selected", (1, 1, 1, 0))],
    )

    style.configure("TPanedwindow", background=p["border_subtle"])
    style.configure("Sash", sashthickness=5, sashrelief=tk.FLAT, background=p["border"])

    style.configure(
        "Vertical.TScrollbar",
        background=p["surface_hover"],
        troughcolor=p["surface"],
        bordercolor=p["surface"],
        arrowcolor=p["text_muted"],
        relief="flat",
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=p["surface_hover"],
        troughcolor=p["surface"],
        bordercolor=p["surface"],
        arrowcolor=p["text_muted"],
        relief="flat",
    )

    return style


def style_text_widget(widget: tk.Text) -> None:
    widget.configure(
        bg=PALETTE["surface_input"],
        fg=PALETTE["text"],
        insertbackground=PALETTE["accent_secondary"],
        selectbackground=PALETTE["selection"],
        selectforeground=PALETTE["text"],
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=PALETTE["border_subtle"],
        highlightcolor=PALETTE["accent"],
        padx=12,
        pady=10,
        font=FONTS["ui"],
        borderwidth=0,
        spacing1=2,
        spacing3=2,
    )


def style_listbox(widget: tk.Listbox) -> None:
    widget.configure(
        bg=PALETTE["surface_input"],
        fg=PALETTE["text"],
        selectbackground=PALETTE["accent_soft"],
        selectforeground=PALETTE["accent"],
        activestyle="none",
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=PALETTE["border_subtle"],
        highlightcolor=PALETTE["accent"],
        font=FONTS["ui_sm"],
        borderwidth=0,
    )


def style_spinbox(widget: tk.Spinbox) -> None:
    widget.configure(
        bg=PALETTE["surface_input"],
        fg=PALETTE["text"],
        insertbackground=PALETTE["accent_secondary"],
        selectbackground=PALETTE["selection"],
        selectforeground=PALETTE["text"],
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=PALETTE["border_subtle"],
        highlightcolor=PALETTE["accent"],
        buttonbackground=PALETTE["surface_hover"],
        disabledbackground=PALETTE["surface"],
        disabledforeground=PALETTE["text_muted"],
        font=FONTS["ui"],
        borderwidth=0,
    )


def style_canvas(widget: tk.Canvas, *, variant: Literal["preview", "surface", "input"] = "surface") -> None:
    colors = {
        "preview": PALETTE["preview_bg"],
        "surface": PALETTE["surface"],
        "input": PALETTE["surface_input"],
    }
    widget.configure(
        bg=colors[variant],
        highlightthickness=0,
        borderwidth=0,
        relief=tk.FLAT,
    )


def style_thumb_button(
    widget: tk.Button,
    *,
    selected: bool = False,
) -> None:
    widget.configure(
        bg=PALETTE["thumb_selected"] if selected else PALETTE["thumb_bg"],
        fg=PALETTE["accent"] if selected else PALETTE["text_secondary"],
        activebackground=PALETTE["surface_hover"],
        activeforeground=PALETTE["text"],
        relief=tk.FLAT,
        bd=0,
        highlightthickness=2 if selected else 1,
        highlightbackground=PALETTE["accent"] if selected else PALETTE["thumb_border"],
        highlightcolor=PALETTE["accent"],
        font=FONTS["ui_sm"],
        cursor="hand2",
        padx=2,
        pady=2,
    )


def placeholder_text_color() -> str:
    return PALETTE["text_muted"]
