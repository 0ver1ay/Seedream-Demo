"""
Симуляция полного цикла generate_images без реального Replicate:
create → polling статусов → output URL → requests.get → base64.
"""
import base64
import io
import os
import tempfile
import unittest
from unittest import mock

from PIL import Image

from fastapi import HTTPException

from server import core


def _tiny_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakePollClient:
    poll_interval = 0.01


class _SimPrediction:
    """Имитация prediction: reload() двигает статус к succeeded."""

    def __init__(self):
        self.id = "sim-pred-001"
        self.status = "starting"
        self._step = 0
        self._client = _FakePollClient()
        self.output = "https://cdn.fake-replicate.test/out.png"

    def reload(self) -> None:
        self._step += 1
        if self._step == 1:
            self.status = "processing"
        else:
            self.status = "succeeded"


class _SimPredictions:
    def create(self, model: str, input: dict):  # noqa: A002
        return _SimPrediction()


class _SimUploaded:
    urls = {"get": "https://upload.fake-replicate.test/ref.bin"}


class _SimFiles:
    def create(self, file, **kwargs):  # noqa: A002
        return _SimUploaded()


class _SimReplicateClient:
    files = _SimFiles()
    predictions = _SimPredictions()


class GenerationSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._log_path: str | None = None

    def tearDown(self) -> None:
        if self._log_path and os.path.isfile(self._log_path):
            try:
                os.remove(self._log_path)
            except OSError:
                pass

    def test_full_pipeline_simulation_with_refs(self):
        fd, path = tempfile.mkstemp(suffix=".log", prefix="seedream_sim_")
        os.close(fd)
        self._log_path = path

        captured: dict = {}

        def fake_make_client(token: str):
            captured["token_len"] = len(token)
            return _SimReplicateClient()

        png = _tiny_png_bytes()
        ref_b64 = base64.b64encode(png).decode("ascii")

        with mock.patch.dict(os.environ, {"SEEDREAM_LOG_FILE": path}, clear=False), mock.patch.object(
            core, "_make_replicate_client", side_effect=fake_make_client
        ), mock.patch.object(core.time, "sleep", lambda *_a, **_k: None), mock.patch.object(
            core.requests,
            "get",
            return_value=_FakeResponse(png),
        ):
            out = core.generate_images(
                {
                    "prompt": "simulation prompt",
                    "model": "bytedance/seedream-4.5",
                    "size": "2K",
                    "aspect_ratio": "1:1",
                    "init_images_base64": [ref_b64],
                    "token": "test-token",
                }
            )

        self.assertEqual(base64.b64decode(out["image_base64"]), png)
        self.assertEqual(len(out["images_base64"]), 1)
        self.assertEqual(captured.get("token_len"), len("test-token"))

        with open(path, encoding="utf-8") as f:
            written = f.read()
        self.assertIn("generate_images_start", written)
        self.assertIn("replicate_create_start", written)
        self.assertIn("replicate_prediction_status", written)
        self.assertIn("replicate_wait_done", written)
        self.assertIn("generate_images_done", written)
        self.assertIn("processing", written)
        self.assertIn("succeeded", written)

    def test_prediction_wall_timeout_uses_monotonic_simulation(self):
        """Симуляция вечного processing: monotonic ускорен, срабатывает wall-timeout."""

        class _StuckPrediction:
            id = "sim-stuck"
            status = "processing"
            _client = _FakePollClient()

            def reload(self) -> None:
                return None

        def stuck_create(self, model, input):  # noqa: A002
            return _StuckPrediction()

        tick = {"n": 0}

        def fake_monotonic() -> float:
            tick["n"] += 1
            return 0.0 if tick["n"] <= 4 else 400.0

        with mock.patch.object(core, "_max_prediction_wall_seconds", return_value=301.0), mock.patch.object(
            core, "_make_replicate_client", lambda _t: _SimReplicateClient()
        ), mock.patch.object(_SimPredictions, "create", stuck_create), mock.patch.object(
            core.time, "sleep", lambda *_a, **_k: None
        ), mock.patch.object(core.time, "monotonic", fake_monotonic):
            with self.assertRaises(HTTPException) as ctx:
                core.generate_images(
                    {
                        "prompt": "x",
                        "model": "bytedance/seedream-4.5",
                        "token": "t",
                    }
                )

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("TimeoutError", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
