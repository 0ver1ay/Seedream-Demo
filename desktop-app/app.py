"""Seedream Desktop — точка входа."""
from __future__ import annotations

import os
import sys

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
for path in (APP_DIR, PROJECT_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from seedream_desktop.application import SeedreamApp  # noqa: E402
from server.core import trace_event  # noqa: E402


if __name__ == "__main__":
    try:
        trace_event("app_main_entry", frozen=getattr(sys, "frozen", False), executable=sys.executable)
    except Exception:
        pass
    SeedreamApp().mainloop()
