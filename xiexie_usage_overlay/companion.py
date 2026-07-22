from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .settings import app_data_dir
from .usage import UsageSnapshot


InsightTone = Literal["normal", "warning", "critical", "unknown"]


@dataclass(frozen=True)
class UsageInsight:
    message: str
    tone: InsightTone = "unknown"
    rate_per_hour: float | None = None
    hours_to_empty: float | None = None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def _duration_text(hours: float) -> str:
    minutes = max(1, round(hours * 60))
    if minutes < 60:
        return f"{minutes} 分钟"
    if minutes < 24 * 60:
        whole_hours = minutes // 60
        remainder = minutes % 60
        return f"{whole_hours} 小时 {remainder} 分" if remainder else f"{whole_hours} 小时"
    days = minutes // (24 * 60)
    hours_left = (minutes % (24 * 60)) // 60
    return f"{days} 天 {hours_left} 小时" if hours_left else f"{days} 天"


class CompanionStore:
    """Persist display-only snapshots and derive local, best-effort usage trends."""

    HISTORY_VERSION = 1
    MAX_SAMPLES = 1_000
    MAX_AGE_DAYS = 8
    MIN_TREND_MINUTES = 10
    MAX_TREND_HOURS = 12

    def __init__(self, directory: Path | None = None, history_enabled: bool = True) -> None:
        self.directory = directory or app_data_dir()
        self.history_enabled = history_enabled
        self.cache_path = self.directory / "last-usage.json"
        self.history_path = self.directory / "usage-history.json"
        self._lock = threading.RLock()

    def load_cached_snapshot(self) -> UsageSnapshot | None:
        with self._lock:
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                return UsageSnapshot.from_safe_dict(data)
            except (OSError, json.JSONDecodeError, ValueError):
                return None

    def record(self, snapshot: UsageSnapshot) -> UsageInsight:
        with self._lock:
            self._write_json(self.cache_path, snapshot.to_safe_dict())
            samples = self._load_samples()
            if self.history_enabled:
                sample = self._sample_from_snapshot(snapshot)
                if not samples or not self._same_measurement(samples[-1], sample):
                    samples.append(sample)
                samples = self._prune_samples(samples, snapshot.received_at)
                self._write_json(
                    self.history_path,
                    {"version": self.HISTORY_VERSION, "samples": samples},
                )
            return self.insight(snapshot, samples)

    def set_history_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.history_enabled = bool(enabled)
            if not self.history_enabled:
                try:
                    self.history_path.unlink()
                except FileNotFoundError:
                    pass

    def insight(self, snapshot: UsageSnapshot, samples: list[dict[str, Any]] | None = None) -> UsageInsight:
        with self._lock:
            history = list(samples) if samples is not None else self._load_samples()
        minimum = snapshot.minimum_remaining
        if minimum is None:
            return UsageInsight("还没有可分析的百分比，我继续盯着。", "unknown")

        current_at = snapshot.received_at
        current_rows = snapshot.display_rows(limit=20)
        candidates: list[tuple[float, float, int | None]] = []
        for row in current_rows:
            key = self._window_key(row.window.duration_minutes, row.label)
            current_reset = row.window.resets_at
            previous = self._find_baseline(history, key, current_reset, current_at)
            if previous is None:
                continue
            previous_at = _parse_datetime(previous.get("at"))
            if previous_at is None:
                continue
            elapsed_hours = max(0.0, (current_at - previous_at).total_seconds() / 3600)
            if elapsed_hours <= 0:
                continue
            previous_remaining = previous.get("remaining")
            if not isinstance(previous_remaining, int):
                continue
            consumed = previous_remaining - row.window.remaining_percent
            if consumed < 0:
                continue
            rate = consumed / elapsed_hours
            if rate <= 0.01:
                candidates.append((0.0, float("inf"), current_reset))
                continue
            candidates.append((rate, row.window.remaining_percent / rate, current_reset))

        active = [item for item in candidates if item[0] > 0]
        if not active:
            if candidates:
                return UsageInsight("最近额度变化不大，稳得住。", "normal", 0.0, None)
            if minimum <= 10:
                return UsageInsight(f"只剩 {minimum}%，别硬撑。", "critical")
            if minimum <= 20:
                return UsageInsight(f"只剩 {minimum}%，我建议省着点。", "warning")
            return UsageInsight("趋势样本还不够，我先替你记着。", "unknown")

        now_ts = current_at.timestamp()
        def urgency(item: tuple[float, float, int | None]) -> float:
            _, hours_to_empty, resets_at = item
            hours_to_reset = max(0.0, (resets_at - now_ts) / 3600) if resets_at else 0.0
            return hours_to_empty - hours_to_reset

        rate, hours_to_empty, resets_at = min(active, key=urgency)
        hours_to_reset = max(0.0, (resets_at - now_ts) / 3600) if resets_at else None
        if hours_to_reset and hours_to_empty < hours_to_reset * 0.45:
            return UsageInsight(
                f"照这个速度，约 {_duration_text(hours_to_empty)} 后会见底。",
                "critical",
                rate,
                hours_to_empty,
            )
        if hours_to_reset and hours_to_empty < hours_to_reset * 0.9:
            lead = max(0.0, hours_to_reset - hours_to_empty)
            return UsageInsight(
                f"消耗偏快，可能比重置早 {_duration_text(lead)} 用完。",
                "warning",
                rate,
                hours_to_empty,
            )
        return UsageInsight(
            f"最近约每小时消耗 {rate:.1f}%，目前节奏还稳。",
            "normal",
            rate,
            hours_to_empty,
        )

    def _load_samples(self) -> list[dict[str, Any]]:
        if not self.history_enabled:
            return []
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        samples = data.get("samples") if isinstance(data, dict) else None
        return [item for item in samples if isinstance(item, dict)] if isinstance(samples, list) else []

    @staticmethod
    def _window_key(duration_minutes: int | None, label: str) -> str:
        return f"duration:{duration_minutes}|label:{label}" if duration_minutes else f"label:{label}"

    def _sample_from_snapshot(self, snapshot: UsageSnapshot) -> dict[str, Any]:
        return {
            "at": snapshot.received_at.isoformat(),
            "limits": [
                {
                    "key": self._window_key(row.window.duration_minutes, row.label),
                    "remaining": row.window.remaining_percent,
                    "resetsAt": row.window.resets_at,
                }
                for row in snapshot.display_rows(limit=20)
            ],
        }

    @staticmethod
    def _same_measurement(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return left.get("limits") == right.get("limits")

    def _prune_samples(self, samples: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
        cutoff = now - timedelta(days=self.MAX_AGE_DAYS)
        recent = [sample for sample in samples if (_parse_datetime(sample.get("at")) or now) >= cutoff]
        return recent[-self.MAX_SAMPLES :]

    def _find_baseline(
        self,
        samples: list[dict[str, Any]],
        key: str,
        resets_at: int | None,
        current_at: datetime,
    ) -> dict[str, Any] | None:
        minimum_age = timedelta(minutes=self.MIN_TREND_MINUTES)
        maximum_age = timedelta(hours=self.MAX_TREND_HOURS)
        for sample in samples:
            sample_at = _parse_datetime(sample.get("at"))
            if sample_at is None:
                continue
            age = current_at - sample_at
            if age < minimum_age or age > maximum_age:
                continue
            limits = sample.get("limits")
            if not isinstance(limits, list):
                continue
            for item in limits:
                if not isinstance(item, dict) or item.get("key") != key:
                    continue
                if resets_at and item.get("resetsAt") != resets_at:
                    continue
                return {"at": sample.get("at"), **item}
        return None

    def _write_json(self, path: Path, data: object) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
