from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from xiexie_usage_overlay.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_invalid_field_types_fall_back_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.json").write_text(
                json.dumps(
                    {
                        "x": True,
                        "y": "200",
                        "refresh_seconds": "invalid",
                        "always_on_top": "false",
                        "warning_threshold": None,
                        "follow_offset_x": "12",
                        "follow_offset_y": True,
                        "layout_version": 2,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch("xiexie_usage_overlay.settings.app_data_dir", return_value=root):
                settings = Settings.load()

        self.assertIsNone(settings.x)
        self.assertIsNone(settings.y)
        self.assertEqual(settings.refresh_seconds, 60)
        self.assertTrue(settings.always_on_top)
        self.assertEqual(settings.warning_threshold, 20)
        self.assertEqual(settings.follow_offset_x, 12)
        self.assertEqual(settings.follow_offset_y, 0)

    def test_numeric_fields_are_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.json").write_text(
                json.dumps({"refresh_seconds": 1, "warning_threshold": 100}),
                encoding="utf-8",
            )
            with mock.patch("xiexie_usage_overlay.settings.app_data_dir", return_value=root):
                settings = Settings.load()

        self.assertEqual(settings.refresh_seconds, 30)
        self.assertEqual(settings.warning_threshold, 50)

    def test_old_layout_offsets_are_reset_for_left_side_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.json").write_text(
                json.dumps({"follow_offset_x": 80, "follow_offset_y": -90}),
                encoding="utf-8",
            )
            with mock.patch("xiexie_usage_overlay.settings.app_data_dir", return_value=root):
                settings = Settings.load()

        self.assertEqual(settings.layout_version, 2)
        self.assertEqual(settings.follow_offset_x, 0)
        self.assertEqual(settings.follow_offset_y, 0)


if __name__ == "__main__":
    unittest.main()
