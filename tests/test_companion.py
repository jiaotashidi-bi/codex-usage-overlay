from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiexie_usage_overlay.companion import CompanionStore
from xiexie_usage_overlay.usage import UsageSnapshot


def _snapshot(remaining: int, received_at: datetime, resets_at: int) -> UsageSnapshot:
    snapshot = UsageSnapshot.from_response(
        {
            "rateLimits": {
                "planType": "plus",
                "primary": {
                    "usedPercent": 100 - remaining,
                    "windowDurationMins": 300,
                    "resetsAt": resets_at,
                },
            }
        }
    )
    return replace(snapshot, received_at=received_at)


class CompanionStoreTests(unittest.TestCase):
    def test_cache_round_trip_keeps_display_only_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            store = CompanionStore(root)
            original = _snapshot(42, now, int((now + timedelta(hours=6)).timestamp()))

            store.record(original)
            restored = store.load_cached_snapshot()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.minimum_remaining, 42)
        self.assertEqual(restored.plan_type, "PLUS")

    def test_fast_consumption_predicts_exhaustion_before_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)
            reset_at = int((start + timedelta(hours=10)).timestamp())
            store = CompanionStore(root)
            store.record(_snapshot(90, start, reset_at))

            insight = store.record(_snapshot(70, start + timedelta(hours=1), reset_at))

        self.assertEqual(insight.tone, "critical")
        self.assertAlmostEqual(insight.rate_per_hour or 0, 20.0)
        self.assertIn("见底", insight.message)

    def test_slow_consumption_is_reported_as_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)
            reset_at = int((start + timedelta(hours=10)).timestamp())
            store = CompanionStore(root)
            store.record(_snapshot(90, start, reset_at))

            insight = store.record(_snapshot(88, start + timedelta(hours=1), reset_at))

        self.assertEqual(insight.tone, "normal")
        self.assertIn("节奏还稳", insight.message)

    def test_history_can_be_disabled_without_disabling_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            store = CompanionStore(root, history_enabled=False)

            store.record(_snapshot(80, now, int((now + timedelta(hours=2)).timestamp())))

            self.assertTrue(store.cache_path.exists())
            self.assertFalse(store.history_path.exists())

    def test_disabling_history_removes_existing_history_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            store = CompanionStore(root)
            store.record(_snapshot(80, now, int((now + timedelta(hours=2)).timestamp())))
            self.assertTrue(store.history_path.exists())

            store.set_history_enabled(False)

            self.assertFalse(store.history_path.exists())


if __name__ == "__main__":
    unittest.main()
