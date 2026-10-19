"""Unit tests for the identity layer. No server, no root, no browser needed."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


class TestNaming(unittest.TestCase):
    def test_flatpak_ids_become_product_names(self):
        # known apps come from labels.json; unknown ones get prettified
        self.assertEqual(server.name_for_flatpak("com.brave.Browser"), "Brave")
        self.assertEqual(server.name_for_flatpak("org.localsend.localsend_app"), "LocalSend")
        self.assertEqual(server.name_for_flatpak("com.example.Thing"), "Example Thing")

    def test_generic_parents_are_not_identities(self):
        # comm is truncated to 15 chars by the kernel, so this is what we see
        self.assertTrue(server.is_generic("cinnamon-sessio"))
        self.assertTrue(server.is_generic("systemd"))
        self.assertTrue(server.is_generic("dbus-daemon"))
        self.assertFalse(server.is_generic("chromium"))
        self.assertFalse(server.is_generic("brave"))

    def test_interpreter_processes_are_named_by_their_script(self):
        self.assertEqual(
            server.derive_name("python3", "python3 /home/a/heartbeat.py --serve"),
            "Heartbeat")
        self.assertEqual(
            server.derive_name("python3", "python3 -u /opt/x/vitals_server.py"),
            "Vitals Server")

    def test_own_cgroup_is_readable(self):
        path = server.read_cgroup(os.getpid())
        self.assertTrue(path.startswith("/"), path)


if __name__ == "__main__":
    unittest.main()
