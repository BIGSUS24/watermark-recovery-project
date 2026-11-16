"""Focused regression checks for the local web application's added controls."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
os.environ["WATERMARK_DB"] = _db_file.name

from webapp import db, server  # noqa: E402


class FeatureTests(unittest.TestCase):
    def test_library_delete_can_be_undone(self):
        con = db.connect()
        try:
            rid = db.insert(
                con, name="feature-test.png", height=16, width=16, block=8,
                variant="A", key="test-key", image_id=b"feature-test",
                png=b"not-a-real-png",
            )
        finally:
            con.close()

        client = server.app.test_client()
        deleted = client.delete(f"/api/library/{rid}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.get("/api/library").json["records"], [])

        restored = client.post(f"/api/library/{rid}/restore")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(client.get("/api/library").json["records"][0]["id"], rid)

    def test_new_frontend_controls_are_present(self):
        html = (ROOT / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
        for element_id in (
            "protect-preview", "verify-preview", "protect-progress",
            "verify-progress", "library-search", "library-sort", "library-undo",
            "key-generate",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("/api/library/${id}/restore", js)
        self.assertIn("is-zoomed", js)


def tearDownModule():
    try:
        os.unlink(_db_file.name)
    except FileNotFoundError:
        pass
    os.environ.pop("WATERMARK_DB", None)


if __name__ == "__main__":
    unittest.main()
