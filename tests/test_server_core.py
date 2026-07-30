import base64
import io
import os
import sys
import unittest
from unittest import mock

DESKTOP_APP_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "desktop-app"))
if DESKTOP_APP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_APP_DIR)

import httpx
from PIL import Image

from server import core


class _FakeFileOutput:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeUploaded:
    urls = {"get": "https://replicate-files.example/ref.png"}


class _FakeFilesApi:
    def __init__(self):
        self.created = False

    def create(self, file, **kwargs):  # noqa: A002
        self.created = True
        return _FakeUploaded()


class _FakeFilesApiAlwaysFail:
    def create(self, file, **kwargs):  # noqa: A002
        raise RuntimeError("upload failed")


class _FakeClientUploadFail:
    def __init__(self):
        self.files = _FakeFilesApiAlwaysFail()


class _FakeClientForUpload:
    def __init__(self):
        self.files = _FakeFilesApi()


class GenerateImagesTests(unittest.TestCase):
    def test_prepare_ref_image_compresses_large_image(self):
        raw_bytes = os.urandom(1200 * 900 * 3)
        img = Image.frombytes("RGB", (1200, 900), raw_bytes)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=96)
        raw = buf.getvalue()
        self.assertGreater(len(raw), 600 * 1024, "fixture should exceed soft limit")
        out, fname, ctype = core._prepare_ref_image_for_upload(raw)
        self.assertEqual(fname, "seedream_ref.jpg")
        self.assertEqual(ctype, "image/jpeg")
        self.assertLess(len(out), len(raw))
        self.assertLess(len(out), 1_500_000)

    def test_upload_reference_images_uses_files_create(self):
        ref_b64 = base64.b64encode(b"fake-png-bytes").decode("ascii")
        client = _FakeClientForUpload()
        with mock.patch.object(core, "trace_event", lambda *a, **k: None):
            urls = core._upload_reference_images(client, "token", [ref_b64], 10)  # type: ignore[arg-type]
        self.assertTrue(client.files.created)
        self.assertEqual(urls, ["https://replicate-files.example/ref.png"])

    def test_prepared_ref_data_url_uses_jpeg_mime_from_ctype(self):
        blob = b"\xff\xd8\xff\xe0" + b"\x00" * 80 + b"\xff\xd9"
        u = core._prepared_ref_data_url(blob, "image/jpeg")
        self.assertTrue(u.startswith("data:image/jpeg;base64,"))
        self.assertLess(len(u), 500)

    def test_ref_upload_uses_requests_after_sdk_transient_fail(self):
        class FailingFiles:
            def create(self, file, **kwargs):  # noqa: A002
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

        class FailingClient:
            files = FailingFiles()

        ref_b64 = base64.b64encode(b"x" * 300).decode("ascii")
        fake_resp = mock.Mock()
        fake_resp.status_code = 201
        fake_resp.json.return_value = {"urls": {"get": "https://replicate-files.example/up.jpg"}}

        with mock.patch.object(core, "trace_event", lambda *a, **k: None), mock.patch.dict(
            os.environ,
            {"SEEDREAM_REF_UPLOAD_SDK_ATTEMPTS": "1", "SEEDREAM_REF_UPLOAD_REQUESTS_ATTEMPTS": "1"},
            clear=False,
        ), mock.patch("server.core.requests.post", return_value=fake_resp):
            urls = core._upload_reference_images(FailingClient(), "secret-token", [ref_b64], 10)

        self.assertEqual(urls, ["https://replicate-files.example/up.jpg"])
        fake_resp.json.assert_called()

    def test_upload_fallback_embeds_prepared_bytes_not_original_base64(self):
        huge_original = base64.b64encode(os.urandom(120_000)).decode("ascii")
        small_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 400 + b"\xff\xd9"
        client = _FakeClientUploadFail()
        with mock.patch.object(core, "trace_event", lambda *a, **k: None), mock.patch.object(
            core,
            "_prepare_ref_image_for_upload",
            return_value=(small_jpeg, "seedream_ref.jpg", "image/jpeg"),
        ):
            urls = core._upload_reference_images(client, "token", [huge_original], 10)  # type: ignore[arg-type]
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].startswith("data:image/jpeg;base64,"))
        self.assertLess(len(urls[0]), 10_000)
        self.assertNotIn(huge_original[:200], urls[0])

    def test_generate_images_uses_image_input_only_for_multiple_refs(self):
        captured = {}
        ref_payload = base64.b64encode(b"ref-image").decode("utf-8")

        def fake_run(client, model, inputs, **kwargs):
            captured["model"] = model
            captured["input"] = inputs
            return [_FakeFileOutput(b"generated-image")]

        with mock.patch.object(core, "_upload_reference_images", return_value=["https://upload/1.png", "https://upload/2.png"]), \
            mock.patch.object(core, "_run_replicate_model", side_effect=fake_run):
            result = core.generate_images(
                {
                    "prompt": "test prompt",
                    "model": "bytedance/seedream-4.5",
                    "init_images_base64": [ref_payload, ref_payload],
                    "token": "token",
                }
            )

        self.assertEqual(base64.b64decode(result["image_base64"]), b"generated-image")
        self.assertEqual(
            captured["input"]["image_input"],
            ["https://upload/1.png", "https://upload/2.png"],
        )
        self.assertNotIn("image", captured["input"])
        self.assertNotIn("images", captured["input"])

    def test_generate_images_downloads_url_outputs(self):
        with mock.patch.object(core, "_upload_reference_images", return_value=[]), \
            mock.patch.object(core, "_run_replicate_model", return_value="https://example.com/result.png"), \
            mock.patch.object(core.requests, "get", return_value=_FakeResponse(b"url-image")):
            result = core.generate_images(
                {
                    "prompt": "test prompt",
                    "model": "bytedance/seedream-4.5",
                    "token": "token",
                }
            )

        self.assertEqual(base64.b64decode(result["image_base64"]), b"url-image")

    def test_generate_images_forces_single_output_for_non_batch_models(self):
        captured = {}

        def fake_run(client, model, inputs, **kwargs):
            captured["input"] = inputs
            return [_FakeFileOutput(b"single-image")]

        with mock.patch.object(core, "_upload_reference_images", return_value=[]), \
            mock.patch.object(core, "_run_replicate_model", side_effect=fake_run):
            core.generate_images(
                {
                    "prompt": "test prompt",
                    "model": "google/nano-banana-2",
                    "max_images": 5,
                    "token": "token",
                }
            )

        self.assertNotIn("max_images", captured["input"])
        self.assertIn("prompt", captured["input"])

    def test_generate_images_does_not_send_output_format(self):
        captured = {}

        def fake_run(client, model, inputs, **kwargs):
            captured["input"] = inputs
            return [_FakeFileOutput(b"single-image")]

        with mock.patch.object(core, "_upload_reference_images", return_value=[]), \
            mock.patch.object(core, "_run_replicate_model", side_effect=fake_run):
            core.generate_images(
                {
                    "prompt": "test prompt",
                    "model": "bytedance/seedream-4.5",
                    "token": "token",
                }
            )

        self.assertNotIn("output_format", captured["input"])

    def test_build_replicate_inputs_seedream_uses_size_and_image_input(self):
        cfg = core.get_image_model_config("bytedance/seedream-5-lite")
        inputs = core.build_replicate_image_inputs(
            cfg,
            prompt="p",
            size="2K",
            aspect_ratio="16:9",
            image_urls=["https://a.png"],
            max_images=2,
            sequential_image_generation="auto",
        )
        self.assertEqual(inputs["size"], "2K")
        self.assertNotIn("resolution", inputs)
        self.assertEqual(inputs["image_input"], ["https://a.png"])
        self.assertNotIn("input_images", inputs)

    def test_build_replicate_inputs_nano_banana_uses_resolution(self):
        for slug in ("google/nano-banana-pro", "google/nano-banana-2", "google/nano-banana"):
            cfg = core.get_image_model_config(slug)
            inputs = core.build_replicate_image_inputs(
                cfg,
                prompt="p",
                size="4K",
                aspect_ratio="1:1",
                image_urls=["https://a.png", "https://b.png"],
                max_images=5,
                sequential_image_generation=None,
            )
            self.assertEqual(inputs.get("resolution"), "4K", slug)
            self.assertNotIn("size", inputs)
            self.assertEqual(inputs.get("image_input"), ["https://a.png", "https://b.png"], slug)
            self.assertNotIn("input_images", inputs)
            self.assertNotIn("max_images", inputs)

    def test_build_replicate_inputs_flux2_uses_input_images(self):
        cfg = core.get_image_model_config("black-forest-labs/flux-2-pro")
        inputs = core.build_replicate_image_inputs(
            cfg,
            prompt="p",
            size="4 MP",
            aspect_ratio="16:9",
            image_urls=["https://a.png"],
            max_images=3,
            sequential_image_generation=None,
        )
        self.assertEqual(inputs["resolution"], "4 MP")
        self.assertNotIn("size", inputs)
        self.assertEqual(inputs["input_images"], ["https://a.png"])
        self.assertNotIn("image_input", inputs)

    def test_generate_images_flux2_maps_refs_field(self):
        captured = {}
        ref_payload = base64.b64encode(b"ref-image").decode("utf-8")

        def fake_run(client, model, inputs, **kwargs):
            captured["input"] = inputs
            return [_FakeFileOutput(b"generated-image")]

        with mock.patch.object(core, "_upload_reference_images", return_value=["https://upload/1.png"]), \
            mock.patch.object(core, "_run_replicate_model", side_effect=fake_run):
            core.generate_images(
                {
                    "prompt": "test prompt",
                    "model": "black-forest-labs/flux-2-pro",
                    "size": "2 MP",
                    "init_images_base64": [ref_payload],
                    "token": "token",
                }
            )

        self.assertEqual(captured["input"]["resolution"], "2 MP")
        self.assertEqual(captured["input"]["input_images"], ["https://upload/1.png"])
        self.assertNotIn("image_input", captured["input"])
        self.assertNotIn("size", captured["input"])


class EnhanceTextTests(unittest.TestCase):
    def test_enhance_image_field_mapping(self):
        self.assertEqual(core._enhance_image_field("openai/gpt-5"), "image_input")
        self.assertEqual(core._enhance_image_field("openai/gpt-5.4"), "image_input")
        self.assertEqual(core._enhance_image_field("google/gemini-2.5-pro"), "images")
        self.assertEqual(core._enhance_image_field("google/gemini-3-pro"), "images")
        self.assertIsNone(core._enhance_image_field("meta/llama-3.1-8b-instruct"))

    def test_enhance_replicate_attaches_image_input(self):
        captured = {}
        tiny = base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode("ascii")

        class FakeClient:
            def run(self, model, input=None, **kwargs):
                captured["model"] = model
                captured["input"] = input or {}
                return "improved prompt text"

        with mock.patch.object(core, "_make_replicate_client", return_value=FakeClient()), \
            mock.patch.object(core, "_upload_reference_images", return_value=["https://example.com/ref.jpg"]):
            result = core.enhance_text(
                {
                    "text": "make it sharper",
                    "provider": "replicate",
                    "model": "openai/gpt-5",
                    "token": "token",
                    "init_images_base64": [tiny],
                }
            )

        self.assertEqual(result["text"], "improved prompt text")
        self.assertEqual(captured["input"]["image_input"], ["https://example.com/ref.jpg"])
        self.assertIn("reference image", captured["input"]["prompt"].lower())

    def test_enhance_text_only_skips_upload_for_llama(self):
        captured = {}

        class FakeClient:
            def run(self, model, input=None, **kwargs):
                captured["input"] = input or {}
                return "ok"

        with mock.patch.object(core, "_make_replicate_client", return_value=FakeClient()), \
            mock.patch.object(core, "_upload_reference_images") as upload_mock:
            core.enhance_text(
                {
                    "text": "hello",
                    "provider": "replicate",
                    "model": "meta/llama-3.1-8b-instruct",
                    "token": "token",
                    "init_images_base64": ["aaaa"],
                }
            )

        upload_mock.assert_not_called()
        self.assertNotIn("image_input", captured["input"])
        self.assertNotIn("images", captured["input"])


if __name__ == "__main__":
    unittest.main()
