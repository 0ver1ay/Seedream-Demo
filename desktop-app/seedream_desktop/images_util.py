from __future__ import annotations

import base64
import io

from PIL import Image


def image_from_base64(image_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")


def sanitize_payload(payload: dict) -> dict:
    redacted = {}
    for k, v in payload.items():
        if k == "token" and v:
            redacted[k] = "***"
        elif k == "init_images_base64" and isinstance(v, list):
            redacted[k] = {"count": len(v)}
        elif k in ("prompt", "text") and isinstance(v, str):
            redacted[k] = v[:200] + ("..." if len(v) > 200 else "")
        else:
            redacted[k] = v
    return redacted
