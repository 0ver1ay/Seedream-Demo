import base64
import os
import sys
import tempfile
import unittest

DESKTOP_APP_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "desktop-app"))
if DESKTOP_APP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_APP_DIR)

from seedream_desktop.models import PROJECT_SCHEMA_VERSION, RefItem
from seedream_desktop.project_store import (
    default_pipelines_bundle,
    load_pipelines_from_payload,
    materialize_ref,
    migrate_branch_refs_to_files,
)


class DesktopStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="seedream_storage_")

    def test_materialize_ref_writes_file(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n" + b"x" * 64
        b64 = base64.b64encode(raw).decode("ascii")
        ref = RefItem(name="test.png", mime="image/png", base64=b64)
        stored = materialize_ref(ref, self._tmpdir)
        self.assertIsNotNone(stored.rel_path)
        self.assertIsNone(stored.base64)
        path = os.path.join(self._tmpdir, stored.rel_path.replace("/", os.sep))
        self.assertTrue(os.path.isfile(path))
        roundtrip = stored.load_base64(self._tmpdir)
        self.assertEqual(roundtrip, b64)

    def test_migrate_v2_refs_to_files(self) -> None:
        raw = b"jpeg-bytes-test"
        b64 = base64.b64encode(raw).decode("ascii")
        pipelines, ap, ast, ab = default_pipelines_bundle()
        branch = pipelines[0]["stages"][0]["branches"][0]
        branch["refs_snapshot"] = [{"name": "a.jpg", "base64": b64, "mime": "image/jpeg"}]
        payload = {
            "seedream_project_version": 2,
            "pipelines": pipelines,
            "active_pipeline_id": ap,
            "active_stage_id": ast,
            "active_branch_id": ab,
        }
        migrate_branch_refs_to_files(pipelines, self._tmpdir)
        snap = branch["refs_snapshot"][0]
        self.assertIn("rel_path", snap)
        self.assertNotIn("base64", snap)
        loaded, _, _, _ = load_pipelines_from_payload(payload, self._tmpdir)
        ref = RefItem.from_dict(loaded[0]["stages"][0]["branches"][0]["refs_snapshot"][0])
        self.assertIsNotNone(ref)
        self.assertEqual(ref.load_base64(self._tmpdir), b64)

    def test_project_schema_version_constant(self) -> None:
        self.assertEqual(PROJECT_SCHEMA_VERSION, 3)


if __name__ == "__main__":
    unittest.main()
