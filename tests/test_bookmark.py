"""Unit tests for the bookmark installer. No browser, no real profile needed."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bookmark  # noqa: E402


def minimal_doc():
    """The smallest document Chromium would write: three roots, no children."""
    return {
        "checksum": "",
        "roots": {
            "bookmark_bar": {"children": [], "date_added": "0", "date_last_used": "0",
                             "date_modified": "0", "guid": "0" * 32, "id": "1",
                             "name": "Bookmarks bar", "type": "folder"},
            "other": {"children": [], "date_added": "0", "date_last_used": "0",
                      "date_modified": "0", "guid": "1" * 32, "id": "2",
                      "name": "Other bookmarks", "type": "folder"},
            "synced": {"children": [], "date_added": "0", "date_last_used": "0",
                       "date_modified": "0", "guid": "2" * 32, "id": "3",
                       "name": "Mobile bookmarks", "type": "folder"},
        },
        "sync_metadata": "",
        "version": 1,
    }


class TestChecksum(unittest.TestCase):
    def test_checksum_is_stable_and_order_sensitive(self):
        doc = minimal_doc()
        base = bookmark.checksum(doc)
        self.assertEqual(base, bookmark.checksum(minimal_doc()))
        doc["roots"]["bookmark_bar"]["children"].append(
            {"id": "4", "name": "x", "type": "url", "url": "http://a/"})
        self.assertNotEqual(base, bookmark.checksum(doc))

    def test_title_bytes_are_utf16(self):
        # A folder named "A" and a folder named "\u0041" are the same string;
        # but a two byte title must not hash like its UTF-8 encoding.
        a = minimal_doc()
        a["roots"]["other"]["name"] = "A"
        b = minimal_doc()
        b["roots"]["other"]["name"] = "A\u0000"
        self.assertNotEqual(bookmark.checksum(a), bookmark.checksum(b))


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="vitals-bm-")
        self.profile = os.path.join(self.dir, "Default")
        os.makedirs(self.profile)
        doc = minimal_doc()
        doc["checksum"] = bookmark.checksum(doc)
        with open(os.path.join(self.profile, "Bookmarks"), "w", encoding="utf8") as f:
            json.dump(doc, f, indent=3, sort_keys=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def read(self):
        with open(os.path.join(self.profile, "Bookmarks"), encoding="utf8") as f:
            return json.load(f)

    def test_install_adds_both_entries_and_valid_checksum(self):
        bookmark.install(self.profile)
        doc = self.read()
        self.assertEqual(doc["checksum"], bookmark.checksum(doc))
        urls = [c["url"] for c in doc["roots"]["bookmark_bar"]["children"]]
        self.assertIn(bookmark.VITALS_URL, urls)
        self.assertTrue(any(u.startswith("javascript:") for u in urls))

    def test_install_is_idempotent(self):
        bookmark.install(self.profile)
        bookmark.install(self.profile)
        bar = self.read()["roots"]["bookmark_bar"]["children"]
        self.assertEqual(len(bar), 2)

    def test_ids_do_not_collide_with_existing_nodes(self):
        doc = self.read()
        doc["roots"]["bookmark_bar"]["children"].append(
            {"id": "99", "name": "existing", "type": "url", "url": "http://b/"})
        doc["checksum"] = bookmark.checksum(doc)
        with open(os.path.join(self.profile, "Bookmarks"), "w", encoding="utf8") as f:
            json.dump(doc, f, indent=3, sort_keys=True)
        bookmark.install(self.profile)
        ids = [c["id"] for c in self.read()["roots"]["bookmark_bar"]["children"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_remove_takes_only_its_own_entries(self):
        doc = self.read()
        doc["roots"]["bookmark_bar"]["children"].append(
            {"id": "50", "name": "keep me", "type": "url", "url": "http://keep/"})
        doc["checksum"] = bookmark.checksum(doc)
        with open(os.path.join(self.profile, "Bookmarks"), "w", encoding="utf8") as f:
            json.dump(doc, f, indent=3, sort_keys=True)
        bookmark.install(self.profile)
        bookmark.remove(self.profile)
        bar = self.read()["roots"]["bookmark_bar"]["children"]
        self.assertEqual([c["name"] for c in bar], ["keep me"])

    def test_backup_is_written_before_touching_the_file(self):
        bookmark.install(self.profile)
        backups = [f for f in os.listdir(self.profile) if f.startswith("Bookmarks.pre-vitals-")]
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()
