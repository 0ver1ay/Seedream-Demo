from __future__ import annotations

import os
from typing import Any, Callable

import requests

GenerateFn = Callable[[dict[str, Any]], dict[str, Any]]
EnhanceFn = Callable[[dict[str, Any]], dict[str, str]]


def seedream_server_url() -> str | None:
    raw = (os.environ.get("SEEDREAM_SERVER") or "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def _http_post_json(url: str, body: dict[str, Any], *, timeout: float = 7200.0) -> dict[str, Any]:
    response = requests.post(url, json=body, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected response from server")
    return data


def http_generate(server: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _http_post_json(f"{server}/seedream/generate", payload)


def http_enhance(server: str, payload: dict[str, Any]) -> dict[str, str]:
    data = _http_post_json(f"{server}/seedream/enhance", payload, timeout=300.0)
    text = data.get("text")
    if not isinstance(text, str):
        raise RuntimeError("Enhance response missing text")
    return {"text": text}


def resolve_generate_fn() -> GenerateFn:
    server = seedream_server_url()
    if server:
        return lambda payload: http_generate(server, payload)
    from server.core import generate_images

    return lambda payload: generate_images(payload)


def resolve_enhance_fn() -> EnhanceFn:
    server = seedream_server_url()
    if server:
        return lambda payload: http_enhance(server, payload)
    from server.core import enhance_text

    return lambda payload: enhance_text(payload)
