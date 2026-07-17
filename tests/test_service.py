from __future__ import annotations

import unittest
from unittest import mock

from xiexie_usage_overlay.service import UsageService


class _UnexpectedFailureClient:
    def add_notification_handler(self, _handler) -> None:
        return

    def start(self) -> None:
        raise RuntimeError("unexpected failure")

    def close(self) -> None:
        return


class UsageServiceRecoveryTests(unittest.TestCase):
    def test_refresh_interval_can_be_updated_live(self) -> None:
        service = UsageService(lambda _event: None)

        service.set_refresh_seconds(5)

        self.assertEqual(service.refresh_seconds, 30)
        self.assertTrue(service._refresh.is_set())

    def test_unexpected_failure_is_reported_instead_of_killing_thread(self) -> None:
        events = []
        service = UsageService(events.append)

        with (
            mock.patch(
                "xiexie_usage_overlay.service.CodexAppServerClient",
                return_value=_UnexpectedFailureClient(),
            ),
            mock.patch.object(service._stop, "wait", return_value=True),
            self.assertLogs("xiexie_usage_overlay.service", level="ERROR"),
        ):
            service._run()

        self.assertEqual(events[0].kind, "loading")
        self.assertEqual(events[1].kind, "error")
        self.assertIn("unexpected failure", events[1].message or "")


if __name__ == "__main__":
    unittest.main()
