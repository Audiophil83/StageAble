import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from engine.bridge_installer import _remote_scripts_roots


class BridgeInstallerPathTests(SimpleTestCase):
    @patch.object(sys, "platform", "win32")
    def test_windows_remote_scripts_roots(self):
        roots = _remote_scripts_roots()
        joined = [str(path).replace("\\", "/") for path in roots]
        self.assertTrue(any("Documents/Ableton/User Library/Remote Scripts" in path for path in joined))

    @patch.object(sys, "platform", "darwin")
    def test_macos_remote_scripts_roots(self):
        roots = _remote_scripts_roots()
        self.assertTrue(
            any(path == Path.home() / "Music/Ableton/User Library/Remote Scripts" for path in roots)
        )
