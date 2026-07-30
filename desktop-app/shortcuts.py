from __future__ import annotations

import tkinter as tk


class ShortcutManager:
    """Clipboard / select-all / undo / redo for Text and Entry.

    On Windows Tk, layout-dependent keysyms (c vs Cyrillic_es) and
    bind_all('<Control-KeyPress>') both cause sticky Ctrl and broken typing.
    We bind once per widget class and dispatch by physical keycode, ignoring AltGr.
    """

    # Windows VK codes — одинаковы для EN/RU на одной физической клавише
    _VK = {
        65: "select_all",  # A / Ф
        67: "copy",        # C / С
        86: "paste",       # V / М
        88: "cut",         # X / Ч
        89: "redo",        # Y / Н
        90: "undo",        # Z / Я
    }

    @staticmethod
    def apply_to(root: tk.Tk | tk.Widget) -> None:
        def _is_ctrl_only(event: tk.Event) -> bool:
            state = int(getattr(event, "state", 0) or 0)
            # Control without Alt/AltGr (AltGr == Control+Alt on Windows)
            return bool(state & 0x4) and not bool(state & 0x20000)

        def _focused_text() -> tk.Entry | tk.Text | None:
            widget = root.focus_get()
            if isinstance(widget, (tk.Entry, tk.Text)):
                return widget
            return None

        def _select_all(widget: tk.Entry | tk.Text) -> None:
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "1.0")
                widget.see("insert")
            else:
                widget.selection_range(0, "end")
                widget.icursor("end")

        def _copy(widget: tk.Entry | tk.Text) -> None:
            try:
                if isinstance(widget, tk.Text):
                    if not widget.tag_ranges("sel"):
                        return
                    text = widget.get("sel.first", "sel.last")
                else:
                    if not widget.selection_present():
                        return
                    text = widget.selection_get()
                widget.clipboard_clear()
                widget.clipboard_append(text)
            except tk.TclError:
                pass

        def _cut(widget: tk.Entry | tk.Text) -> None:
            try:
                if isinstance(widget, tk.Text):
                    if not widget.tag_ranges("sel"):
                        return
                    text = widget.get("sel.first", "sel.last")
                    widget.clipboard_clear()
                    widget.clipboard_append(text)
                    widget.delete("sel.first", "sel.last")
                else:
                    if not widget.selection_present():
                        return
                    text = widget.selection_get()
                    widget.clipboard_clear()
                    widget.clipboard_append(text)
                    widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass

        def _paste(widget: tk.Entry | tk.Text) -> None:
            try:
                text = widget.clipboard_get()
            except tk.TclError:
                return
            if text is None:
                return
            text = str(text)
            try:
                if isinstance(widget, tk.Text):
                    try:
                        widget.delete("sel.first", "sel.last")
                    except tk.TclError:
                        pass
                    widget.insert("insert", text)
                else:
                    try:
                        if widget.selection_present():
                            widget.delete("sel.first", "sel.last")
                    except tk.TclError:
                        pass
                    widget.insert("insert", text)
            except tk.TclError:
                pass

        def _undo(widget: tk.Entry | tk.Text) -> None:
            try:
                widget.edit_undo()
            except (tk.TclError, AttributeError):
                pass

        def _redo(widget: tk.Entry | tk.Text) -> None:
            try:
                widget.edit_redo()
            except (tk.TclError, AttributeError):
                pass

        actions = {
            "copy": _copy,
            "cut": _cut,
            "paste": _paste,
            "select_all": _select_all,
            "undo": _undo,
            "redo": _redo,
        }

        def _on_key(event: tk.Event):
            if not _is_ctrl_only(event):
                return None
            action = ShortcutManager._VK.get(int(getattr(event, "keycode", 0) or 0))
            if not action:
                return None
            widget = event.widget
            if not isinstance(widget, (tk.Entry, tk.Text)):
                widget = _focused_text()
            if widget is None:
                return None
            handler = actions[action]
            handler(widget)
            return "break"

        # Class bindings replace the fragile keysym/Cyrillic matrix.
        # add=False so we own Ctrl letter combos and default Tk paste doesn't double-fire.
        for widget_class in ("Text", "Entry"):
            root.bind_class(widget_class, "<Control-KeyPress>", _on_key, add=False)

        def _dispatch_if_text(action: str):
            def _h(_event: tk.Event):
                widget = _focused_text()
                if widget is None:
                    return None
                actions[action](widget)
                return "break"

            return _h

        root.bind_all("<Control-Insert>", _dispatch_if_text("copy"))
        root.bind_all("<Shift-Delete>", _dispatch_if_text("cut"))
        root.bind_all("<Shift-Insert>", _dispatch_if_text("paste"))
