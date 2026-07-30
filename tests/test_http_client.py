import os
import sys
import unittest
from unittest import mock

DESKTOP_APP_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "desktop-app"))
if DESKTOP_APP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_APP_DIR)

from seedream_desktop.services import http_client


class HttpClientTests(unittest.TestCase):
    def test_seedream_server_url_empty(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(http_client.seedream_server_url())

    def test_seedream_server_url_strips_slash(self) -> None:
        with mock.patch.dict(os.environ, {"SEEDREAM_SERVER": "http://127.0.0.1:8000/"}, clear=False):
            self.assertEqual(http_client.seedream_server_url(), "http://127.0.0.1:8000")

    def test_http_generate_posts_to_server(self) -> None:
        fake = mock.Mock()
        fake.json.return_value = {"image_base64": "abc", "images_base64": ["abc"]}
        fake.raise_for_status = mock.Mock()
        with mock.patch("seedream_desktop.services.http_client.requests.post", return_value=fake) as post:
            out = http_client.http_generate("http://localhost:8000", {"prompt": "x", "token": "t"})
        post.assert_called_once()
        self.assertEqual(out["image_base64"], "abc")


if __name__ == "__main__":
    unittest.main()
