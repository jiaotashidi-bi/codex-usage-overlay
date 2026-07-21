from __future__ import annotations

import unittest
from unittest import mock

from xiexie_usage_overlay.overlay import UsageOverlay
from xiexie_usage_overlay.pet_identity import PetIdentity
from xiexie_usage_overlay.settings import Settings


class _FailingLocator:
    def find(self):
        raise OSError("temporary window API failure")


class OverlayRecoveryTests(unittest.TestCase):
    def test_pet_follow_loop_reschedules_after_failure(self) -> None:
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay._closing = False
        overlay._pet_locator = _FailingLocator()
        overlay.root = mock.Mock()

        with self.assertLogs("xiexie_usage_overlay.overlay", level="ERROR"):
            overlay._sync_to_pet()

        overlay.root.after.assert_called_once()
        self.assertEqual(overlay.root.after.call_args.args[0], 150)

    def test_authentication_error_has_actionable_message(self) -> None:
        message = UsageOverlay._short_error(
            "codex account authentication required to read rate limits"
        )
        self.assertIn("codex.cmd login", message)

    def test_snapshot_height_grows_for_two_rows_and_credits(self) -> None:
        self.assertEqual(UsageOverlay._snapshot_pixel_height(1, False), 150)
        self.assertEqual(UsageOverlay._snapshot_pixel_height(2, False), 230)
        self.assertEqual(UsageOverlay._snapshot_pixel_height(2, True), 250)

    def test_two_rows_have_additional_vertical_spacing(self) -> None:
        self.assertEqual(UsageOverlay._row_step(1), 34)
        self.assertEqual(UsageOverlay._row_step(2), 40)

    def test_percentage_uses_same_color_as_progress_bar(self) -> None:
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.canvas = mock.Mock()
        overlay._font = mock.Mock(return_value=("font",))
        overlay._rounded_rectangle = mock.Mock()

        for remaining, expected in ((75, UsageOverlay.GREEN), (42, UsageOverlay.AMBER), (14, UsageOverlay.CORAL)):
            with self.subTest(remaining=remaining):
                overlay.canvas.reset_mock()
                overlay._rounded_rectangle.reset_mock()
                overlay._draw_limit_row(35, "7 天额度", remaining, "1 小时后重置")

                percentage = [
                    call for call in overlay.canvas.create_text.call_args_list
                    if call.kwargs.get("text") == f"{remaining}%"
                ]
                self.assertEqual(percentage[0].kwargs["fill"], expected)
                self.assertTrue(
                    any(call.kwargs.get("fill") == expected for call in overlay._rounded_rectangle.call_args_list)
                )

    def test_reference_and_low_dpi_sizes_are_consistent(self) -> None:
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.settings = Settings(size_mode="auto")

        reference_x, reference_y = overlay._calculate_scales(192)
        low_x, low_y = overlay._calculate_scales(96)

        self.assertAlmostEqual(reference_x, UsageOverlay.REFERENCE_SCALE_X)
        self.assertAlmostEqual(reference_y, UsageOverlay.REFERENCE_SCALE_Y)
        self.assertAlmostEqual(low_x, reference_x / 2)
        self.assertAlmostEqual(low_y, reference_y / 2)

    def test_pet_identity_change_updates_all_visible_labels(self) -> None:
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay._closing = False
        overlay._identity = PetIdentity("custom:xiexie", "xiexie", "custom")
        overlay._pet_name = "xiexie"
        overlay._identity_resolver = mock.Mock(
            resolve=mock.Mock(return_value=PetIdentity("custom:maomao", "maomao", "custom"))
        )
        overlay.root = mock.Mock()
        overlay._menu = mock.Mock()
        overlay._exit_menu_index = 4
        overlay._redraw = mock.Mock()

        overlay._sync_pet_identity()

        self.assertEqual(overlay._pet_name, "maomao")
        overlay.root.title.assert_called_once_with("maomao Codex 余量")
        overlay._menu.entryconfigure.assert_called_once_with(4, label="退出 maomao 余量")
        overlay._redraw.assert_called_once()
        overlay.root.after.assert_called_once_with(UsageOverlay.IDENTITY_POLL_MS, overlay._sync_pet_identity)


if __name__ == "__main__":
    unittest.main()
