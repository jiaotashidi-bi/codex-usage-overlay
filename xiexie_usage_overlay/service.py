from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

from .app_server import AppServerError, CodexAppServerClient
from .companion import CompanionStore, UsageInsight
from .usage import UsageSnapshot


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceEvent:
    kind: Literal["loading", "snapshot", "error"]
    snapshot: UsageSnapshot | None = None
    message: str | None = None
    source: Literal["live", "cache"] = "live"
    insight: UsageInsight | None = None


EventHandler = Callable[[ServiceEvent], None]


class UsageService:
    def __init__(
        self,
        handler: EventHandler,
        refresh_seconds: int = 60,
        history_enabled: bool = True,
        store: CompanionStore | None = None,
    ) -> None:
        self.handler = handler
        self.refresh_seconds = max(30, refresh_seconds)
        self._stop = threading.Event()
        self._refresh = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: CodexAppServerClient | None = None
        self._store = store or CompanionStore(history_enabled=history_enabled)
        self._last_snapshot: UsageSnapshot | None = None
        self._last_insight: UsageInsight | None = None
        self._last_source: Literal["live", "cache"] = "live"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="codex-usage-overlay-service", daemon=True)
        self._thread.start()

    def refresh_now(self) -> None:
        self._refresh.set()

    def set_refresh_seconds(self, seconds: int) -> None:
        self.refresh_seconds = max(30, min(900, int(seconds)))
        self._refresh.set()

    def set_history_enabled(self, enabled: bool) -> None:
        try:
            self._store.set_history_enabled(enabled)
        except OSError:
            logger.warning("Unable to update local history preference", exc_info=True)

    def stop(self) -> None:
        self._stop.set()
        self._refresh.set()
        client = self._client
        if client:
            client.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=4)

    def _run(self) -> None:
        cached = self._store.load_cached_snapshot()
        if cached is not None:
            self._last_snapshot = cached
            self._last_insight = self._store.insight(cached)
            self._last_source = "cache"
            self.handler(
                ServiceEvent(
                    "snapshot",
                    snapshot=cached,
                    message="正在连接，先显示上次数据。",
                    source="cache",
                    insight=self._last_insight,
                )
            )
        else:
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
                self.handler(
                    ServiceEvent(
                        "error",
                        snapshot=self._last_snapshot,
                        message=str(exc),
                        source=self._last_source,
                        insight=self._last_insight,
                    )
                )
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.exception("Unexpected usage service failure")
                self.handler(
                    ServiceEvent(
                        "error",
                        snapshot=self._last_snapshot,
                        message=str(exc),
                        source=self._last_source,
                        insight=self._last_insight,
                    )
                )
            finally:
                client.close()
                if self._client is client:
                    self._client = None

            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, 60)

    def _publish(self, response: dict) -> None:
        snapshot = UsageSnapshot.from_response(response)
        self._publish_snapshot(snapshot)

    def _publish_snapshot(self, snapshot: UsageSnapshot) -> None:
        try:
            insight = self._store.record(snapshot)
        except OSError:
            logger.warning("Unable to persist local usage history", exc_info=True)
            insight = self._store.insight(snapshot)
        self._last_snapshot = snapshot
        self._last_insight = insight
        self._last_source = "live"
        self.handler(ServiceEvent("snapshot", snapshot=snapshot, source="live", insight=insight))

    def _on_notification(self, message: dict) -> None:
        if message.get("method") != "account/rateLimits/updated":
            return
        try:
            snapshot = UsageSnapshot.from_notification(message.get("params"))
        except ValueError:
            return
        self._publish_snapshot(snapshot)


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
        snapshot = UsageSnapshot.from_response(response)
        self.handler(
            ServiceEvent(
                "snapshot",
                snapshot=snapshot,
                insight=UsageInsight("今天用得有点猛，我已经替你算着了。", "warning", 3.4, 4.1),
            )
        )

    def refresh_now(self) -> None:
        self.start()

    def set_refresh_seconds(self, _seconds: int) -> None:
        return

    def set_history_enabled(self, _enabled: bool) -> None:
        return

    def stop(self) -> None:
        return
