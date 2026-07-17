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
                        "size_mode": "giant",
                        "size_adjust": "invalid",
                        "start_with_windows": "yes",
                        "follow_offset_x": "12",
                        "follow_offset_y": True,
                        "layout_version": 4,
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
        self.assertEqual(settings.size_mode, "auto")
        self.assertEqual(settings.size_adjust, 1.0)
        self.assertFalse(settings.start_with_windows)
        self.assertEqual(settings.follow_offset_x, 12)
        self.assertEqual(settings.follow_offset_y, 0)

    def test_numeric_fields_are_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.json").write_text(
                json.dumps({"refresh_seconds": 1, "warning_threshold": 100, "size_adjust": 99}),
                encoding="utf-8",
            )
            with mock.patch("xiexie_usage_overlay.settings.app_data_dir", return_value=root):
                settings = Settings.load()

        self.assertEqual(settings.refresh_seconds, 30)
        self.assertEqual(settings.warning_threshold, 50)
        self.assertEqual(settings.size_adjust, 1.5)

    def test_old_layout_offsets_are_reset_for_left_side_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.json").write_text(
                json.dumps({"follow_offset_x": 80, "follow_offset_y": -90}),
                encoding="utf-8",
            )
            with mock.patch("xiexie_usage_overlay.settings.app_data_dir", return_value=root):
                settings = Settings.load()

        self.assertEqual(settings.layout_version, 4)
        self.assertEqual(settings.follow_offset_x, 0)
        self.assertEqual(settings.follow_offset_y, 0)

    def test_size_presets_and_custom_adjustment(self) -> None:
        self.assertEqual(Settings(size_mode="small").size_multiplier, 0.85)
        self.assertEqual(Settings(size_mode="medium").size_multiplier, 1.0)
        self.assertEqual(Settings(size_mode="large").size_multiplier, 1.15)
        self.assertEqual(Settings(size_mode="custom", size_adjust=1.22).size_multiplier, 1.22)

    def test_legacy_settings_are_migrated_to_generic_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "codex-usage-overlay"
            legacy = root / "xiexie-usage-overlay"
            legacy.mkdir()
            (legacy / "settings.json").write_text(
                json.dumps({"always_on_top": False, "layout_version": 4}),
                encoding="utf-8",
            )

            with mock.patch("xiexie_usage_overlay.settings.app_data_dir", return_value=current), mock.patch(
                "xiexie_usage_overlay.settings.legacy_app_data_dir", return_value=legacy
            ):
                settings = Settings.load()

            migrated = json.loads((current / "settings.json").read_text(encoding="utf-8"))

        self.assertFalse(settings.always_on_top)
        self.assertFalse(migrated["always_on_top"])


if __name__ == "__main__":
    unittest.main()
