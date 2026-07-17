from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from xiexie_usage_overlay.startup import is_startup_enabled, set_startup


class StartupTests(unittest.TestCase):
    def test_install_writes_hidden_vbs_launcher_and_removes_legacy_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pythonw = root / "pythonw.exe"
            main = root / "main.py"
            pythonw.touch()
            main.touch()
            (root / "xiexie Codex Usage Overlay.lnk").touch()

            with mock.patch("xiexie_usage_overlay.startup.startup_dir", return_value=root):
                target = set_startup(True, executable=pythonw, main_path=main)
                enabled = is_startup_enabled()

            script = target.read_text(encoding="utf-16")
            legacy_exists = (root / "xiexie Codex Usage Overlay.lnk").exists()

        self.assertTrue(enabled)
        self.assertIn(str(pythonw), script)
        self.assertIn(str(main), script)
        self.assertIn(', 0, False', script)
        self.assertFalse(legacy_exists)

    def test_disable_removes_new_and_legacy_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Codex Usage Overlay.vbs").touch()
            (root / "xiexie Codex Usage Overlay.lnk").touch()

            with mock.patch("xiexie_usage_overlay.startup.startup_dir", return_value=root):
                set_startup(False)

            self.assertFalse(any(root.iterdir()))


if __name__ == "__main__":
    unittest.main()
