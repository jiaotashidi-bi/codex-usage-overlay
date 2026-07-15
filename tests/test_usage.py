from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone

from xiexie_usage_overlay.usage import RateWindow, UsageSnapshot


class RateWindowTests(unittest.TestCase):
    def test_weekly_window_and_remaining(self) -> None:
        window = RateWindow(used_percent=68, duration_minutes=10080, resets_at=2_000_000_000)
        self.assertEqual(window.remaining_percent, 32)
        self.assertEqual(window.duration_label(), "7 天额度")

    def test_reset_countdown(self) -> None:
        now = time.time()
        window = RateWindow(used_percent=10, duration_minutes=300, resets_at=int(now + 7260))
        self.assertIn("小时", window.reset_text(now=now))

    def test_reset_countdown_uses_relative_time_for_hours_and_days(self) -> None:
        now = 1_000.0
        hourly = RateWindow(used_percent=10, resets_at=int(now + 84 * 60))
        weekly = RateWindow(used_percent=10, resets_at=int(now + 6 * 86400 + 3 * 3600))

        self.assertEqual(hourly.reset_text(now=now), "1 小时 24 分后重置")
        self.assertEqual(weekly.reset_text(now=now), "6 天 3 小时后重置")

    def test_percent_is_clamped(self) -> None:
        window = RateWindow.from_mapping({"usedPercent": 130})
        self.assertIsNotNone(window)
        self.assertEqual(window.used_percent, 100)
        self.assertEqual(window.remaining_percent, 0)


class UsageSnapshotTests(unittest.TestCase):
    def test_parses_current_camel_case_response(self) -> None:
        snapshot = UsageSnapshot.from_response(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "planType": "plus",
                        "primary": {
                            "usedPercent": 68,
                            "windowDurationMins": 10080,
                            "resetsAt": 2_000_000_000,
                        },
                        "secondary": None,
                        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
                    }
                }
            }
        )
        self.assertEqual(snapshot.plan_type, "PLUS")
        self.assertEqual(snapshot.minimum_remaining, 32)
        self.assertEqual(snapshot.display_rows()[0].label, "7 天额度")

    def test_parses_snake_case_compatibility(self) -> None:
        snapshot = UsageSnapshot.from_response(
            {
                "rate_limits": {
                    "limit_id": "codex",
                    "plan_type": "pro",
                    "primary": {
                        "used_percent": 25,
                        "window_duration_mins": 300,
                        "resets_at": 2_000_000_000,
                    },
                }
            }
        )
        self.assertEqual(snapshot.plan_type, "PRO")
        self.assertEqual(snapshot.minimum_remaining, 75)
        self.assertEqual(snapshot.display_rows()[0].label, "5 小时额度")

    def test_notification_wrapper(self) -> None:
        snapshot = UsageSnapshot.from_notification(
            {
                "rateLimits": {
                    "planType": "plus",
                    "primary": {"usedPercent": 5, "windowDurationMins": 60},
                }
            }
        )
        self.assertEqual(snapshot.minimum_remaining, 95)

    def test_stale_snapshot_detection(self) -> None:
        received = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
        snapshot = UsageSnapshot((), received)

        self.assertFalse(snapshot.is_stale(120, received + timedelta(seconds=120)))
        self.assertTrue(snapshot.is_stale(120, received + timedelta(seconds=121)))


if __name__ == "__main__":
    unittest.main()
