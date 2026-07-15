from __future__ import annotations

import unittest
from unittest import mock

from xiexie_usage_overlay.overlay import UsageOverlay


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


if __name__ == "__main__":
    unittest.main()
