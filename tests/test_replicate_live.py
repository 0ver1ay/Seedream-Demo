"""
Live integration: real Replicate API + full HTTP round-trip via FastAPI.

Does not run in normal CI: requires REPLICATE_API_TOKEN and SEEDREAM_RUN_LIVE_REPLICATE=1.

PowerShell example:
  $env:REPLICATE_API_TOKEN="r8_..."
  $env:SEEDREAM_RUN_LIVE_REPLICATE="1"
  .\\desktop-app\\.venv\\Scripts\\python.exe -m unittest tests.test_replicate_live -v

Optional:
  $env:SEEDREAM_LIVE_MODEL="bytedance/seedream-4.5"
  $env:SEEDREAM_LIVE_SIZE="2K"
"""
from __future__ import annotations

import base64
import io
import os
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from server.main import app


def _live_enabled() -> bool:
    token = (os.environ.get("REPLICATE_API_TOKEN") or "").strip()
    flag = (os.environ.get("SEEDREAM_RUN_LIVE_REPLICATE") or "").strip().lower()
    return bool(token) and flag in ("1", "true", "yes")


@unittest.skipUnless(_live_enabled(), "Set REPLICATE_API_TOKEN and SEEDREAM_RUN_LIVE_REPLICATE=1 for live Replicate test")
class ReplicateLiveHttpTests(unittest.TestCase):
    """POST /seedream/generate -> Replicate -> JSON with image_base64 (decoded PNG/JPEG)."""

    def test_live_http_generate_roundtrip(self) -> None:
        token = os.environ["REPLICATE_API_TOKEN"].strip()
        model = (os.environ.get("SEEDREAM_LIVE_MODEL") or "google/nano-banana").strip()
        size = (os.environ.get("SEEDREAM_LIVE_SIZE") or "1K").strip()

        body = {
            "prompt": (
                "Simple flat geometric icon: blue circle on white background, "
                "minimal vector style, centered, no text, no watermark"
            ),
            "model": model,
            "size": size,
            "aspect_ratio": "1:1",
            "max_images": 1,
            "token": token,
        }

        client = TestClient(app)
        response = client.post("/seedream/generate", json=body)
        self.assertEqual(
            response.status_code,
            200,
            msg=response.text[:2000] if response.text else str(response.content[:500]),
        )
        data = response.json()
        self.assertIn("image_base64", data)
        raw = base64.b64decode(data["image_base64"])
        self.assertGreater(len(raw), 500, "image payload unexpectedly small")

        img = Image.open(io.BytesIO(raw))
        self.assertIn(img.format, ("PNG", "JPEG", "WEBP"))
        w, h = img.size
        self.assertGreater(w, 16)
        self.assertGreater(h, 16)


if __name__ == "__main__":
    unittest.main()
