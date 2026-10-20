"""Tests for site grouping and the plain-English role judgements."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


class TestUrlKey(unittest.TestCase):
    def test_fragments_collapse(self):
        a = server.url_key("https://site.com/page#one")
        b = server.url_key("https://site.com/page#two")
        self.assertEqual(a, b)

    def test_query_is_part_of_identity(self):
        self.assertNotEqual(server.url_key("https://site.com/?tab=1"),
                            server.url_key("https://site.com/?tab=2"))

    def test_empty_path_becomes_slash(self):
        self.assertEqual(server.url_key("https://site.com"), "https://site.com/")

    def test_junk_does_not_raise(self):
        self.assertEqual(server.url_key(""), "")
        self.assertEqual(server.url_key(None), "")


class TestMergeTabs(unittest.TestCase):
    def test_same_url_is_summed_with_a_count(self):
        tabs = [
            {"url": "https://a.com/x", "title": "A", "task_pct": 4.0, "heap_mb": 100, "nodes": 10},
            {"url": "https://a.com/x#frag", "title": "A again", "task_pct": 6.0, "heap_mb": 50, "nodes": 5},
            {"url": "https://b.com/", "title": "B", "task_pct": 1.0, "heap_mb": 10, "nodes": 1},
        ]
        out = server.merge_tabs(tabs)
        self.assertEqual(len(out), 2)
        a = next(t for t in out if "a.com" in t["url"])
        self.assertEqual(a["tab_count"], 2)
        self.assertAlmostEqual(a["task_pct"], 10.0)
        self.assertEqual(a["heap_mb"], 150)
        self.assertEqual(a["nodes"], 15)

    def test_distinct_urls_stay_separate(self):
        out = server.merge_tabs([{"url": "https://a/1", "task_pct": 1},
                                 {"url": "https://a/2", "task_pct": 1}])
        self.assertEqual(len(out), 2)

    def test_busiest_title_wins(self):
        out = server.merge_tabs([{"url": "https://a/", "title": "quiet", "task_pct": 0.1},
                                 {"url": "https://a/", "title": "loud", "task_pct": 9.0}])
        self.assertEqual(out[0]["title"], "loud")


class TestLeakHint(unittest.TestCase):
    def idle(self, age_h, cpu=0.0):
        return {"cpu": cpu, "age_h": age_h}

    def test_old_idle_calls_are_called_out(self):
        hint = server.leak_hint("call (WebRTC)", [self.idle(20), self.idle(9), self.idle(0.2, 0.1)])
        self.assertIn("2 of 3", hint)
        self.assertIn("20.0h", hint)

    def test_a_busy_group_is_not_accused(self):
        self.assertEqual(server.leak_hint("call (WebRTC)",
                                          [self.idle(20, 0.5), self.idle(20, 0.4)]), "")

    def test_young_processes_are_not_accused(self):
        self.assertEqual(server.leak_hint("call (WebRTC)", [self.idle(0.1), self.idle(0.2)]), "")

    def test_hint_never_says_safe_to_delete(self):
        hint = server.leak_hint("call (WebRTC)", [self.idle(30)])
        self.assertNotIn("safe", hint.lower())


if __name__ == "__main__":
    unittest.main()
