from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any


def load_json_file(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_json_file(path: str, data: dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".seedream_", suffix=".json", dir=directory or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def append_log(log_file: str, message: str, data: dict[str, Any] | None = None) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    if data is not None:
        try:
            line += json.dumps(data, ensure_ascii=False) + "\n"
        except Exception:
            line += str(data) + "\n"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
    except Exception as exc:
        try:
            alt = os.path.join(tempfile.gettempdir(), "seedream_app_log_fail.txt")
            with open(alt, "a", encoding="utf-8") as f:
                f.write(line)
                f.write(f"primary_log_error={type(exc).__name__}: {exc}; primary_path={log_file!r}\n")
        except Exception:
            pass
