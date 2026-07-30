from __future__ import annotations

import os
from typing import Any

from seedream_desktop.io_utils import load_json_file, save_json_file


def load_secrets(secrets_path: str) -> dict[str, Any]:
    return load_json_file(secrets_path)


def save_secrets(secrets_path: str, secrets: dict[str, Any]) -> None:
    save_json_file(secrets_path, secrets)


def apply_seedream_env_from_secrets(secrets: dict[str, Any]) -> list[str]:
    if not isinstance(secrets, dict):
        return []
    applied: list[str] = []
    for key, val in secrets.items():
        if not isinstance(key, str) or not key.startswith("SEEDREAM_"):
            continue
        if isinstance(val, bool) or val is None:
            continue
        sval = str(val).strip()
        if not sval:
            continue
        if key not in os.environ:
            os.environ[key] = sval
            applied.append(key)
    if secrets.get("replicate_ref_upload_insecure_tls") is True:
        if "SEEDREAM_REF_UPLOAD_VERIFY_SSL" not in os.environ:
            os.environ["SEEDREAM_REF_UPLOAD_VERIFY_SSL"] = "0"
            applied.append("SEEDREAM_REF_UPLOAD_VERIFY_SSL")
    return applied


def replicate_token(secrets: dict[str, Any]) -> str | None:
    env = (os.environ.get("REPLICATE_API_TOKEN") or "").strip()
    if env:
        return env
    val = secrets.get("replicate")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def provider_token(secrets: dict[str, Any], provider: str) -> str | None:
    if provider == "replicate":
        return replicate_token(secrets)
    val = secrets.get(provider)
    if isinstance(val, str) and val.strip():
        return val.strip()
    env_key = {"openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY"}.get(provider)
    if env_key:
        env = (os.environ.get(env_key) or "").strip()
        if env:
            return env
    return None
