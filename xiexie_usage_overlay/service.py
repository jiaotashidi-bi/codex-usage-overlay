from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

from .app_server import AppServerError, CodexAppServerClient
from .usage import UsageSnapshot


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceEvent:
    kind: Literal["loading", "snapshot", "error"]
    snapshot: UsageSnapshot | None = None
    message: str | None = None


EventHandler = Callable[[ServiceEvent], None]


class UsageService:
    def __init__(self, handler: EventHandler, refresh_seconds: int = 60) -> None:
        self.handler = handler
        self.refresh_seconds = max(30, refresh_seconds)
        self._stop = threading.Event()
        self._refresh = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: CodexAppServerClient | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="xiexie-usage-service", daemon=True)
        self._thread.start()

    def refresh_now(self) -> None:
        self._refresh.set()

    def stop(self) -> None:
        self._stop.set()
        self._refresh.set()
        client = self._client
        if client:
            client.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=4)

    def _run(self) -> None:
        self.handler(ServiceEvent("loading", message="正在读取 Codex 套餐余量…"))
        backoff = 2
        while not self._stop.is_set():
            client = CodexAppServerClient()
            self._client = client
            client.add_notification_handler(self._on_notification)
            try:
                client.start()
                self._publish(client.read_rate_limits())
                backoff = 2
                while not self._stop.is_set():
                    self._refresh.wait(self.refresh_seconds)
                    self._refresh.clear()
                    if self._stop.is_set():
                        break
                    self._publish(client.read_rate_limits())
            except (AppServerError, ValueError, OSError) as exc:
                if self._stop.is_set():
                    break
                logger.warning("Usage refresh failed: %s", exc)
                self.handler(ServiceEvent("error", message=str(exc)))
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.exception("Unexpected usage service failure")
                self.handler(ServiceEvent("error", message=str(exc)))
            finally:
                client.close()
                if self._client is client:
                    self._client = None

            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, 60)

    def _publish(self, response: dict) -> None:
        snapshot = UsageSnapshot.from_response(response)
        self.handler(ServiceEvent("snapshot", snapshot=snapshot))

    def _on_notification(self, message: dict) -> None:
        if message.get("method") != "account/rateLimits/updated":
            return
        try:
            snapshot = UsageSnapshot.from_notification(message.get("params"))
        except ValueError:
            return
        self.handler(ServiceEvent("snapshot", snapshot=snapshot))


class DemoUsageService:
    def __init__(self, handler: EventHandler) -> None:
        self.handler = handler

    def start(self) -> None:
        now = int(time.time())
        response = {
            "rateLimits": {
                "limitId": "codex",
                "planType": "plus",
                "primary": {
                    "usedPercent": 68,
                    "windowDurationMins": 10080,
                    "resetsAt": now + 4 * 24 * 60 * 60 + 7 * 60 * 60,
                },
                "secondary": {
                    "usedPercent": 86,
                    "windowDurationMins": 300,
                    "resetsAt": now + 2 * 60 * 60 + 18 * 60,
                },
                "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
            }
        }
        self.handler(ServiceEvent("snapshot", snapshot=UsageSnapshot.from_response(response)))

    def refresh_now(self) -> None:
        self.start()

    def stop(self) -> None:
        return
