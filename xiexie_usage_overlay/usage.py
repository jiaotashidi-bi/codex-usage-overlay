from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Iterable


def _value(data: dict[str, Any], camel: str, snake: str | None = None) -> Any:
    if camel in data:
        return data[camel]
    return data.get(snake or camel)


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RateWindow:
    used_percent: int
    duration_minutes: int | None = None
    resets_at: int | None = None

    @property
    def remaining_percent(self) -> int:
        return max(0, min(100, 100 - self.used_percent))

    @classmethod
    def from_mapping(cls, data: Any) -> "RateWindow | None":
        if not isinstance(data, dict):
            return None
        used = _integer(_value(data, "usedPercent", "used_percent"))
        if used is None:
            return None
        return cls(
            used_percent=max(0, min(100, used)),
            duration_minutes=_integer(_value(data, "windowDurationMins", "window_duration_mins")),
            resets_at=_integer(_value(data, "resetsAt", "resets_at")),
        )

    def duration_label(self, fallback: str = "套餐额度") -> str:
        minutes = self.duration_minutes
        if not minutes or minutes <= 0:
            return fallback
        if minutes % 1440 == 0:
            return f"{minutes // 1440} 天额度"
        if minutes % 60 == 0:
            return f"{minutes // 60} 小时额度"
        return f"{minutes} 分钟额度"

    def reset_text(self, now: float | None = None) -> str:
        if not self.resets_at:
            return "重置时间暂不可用"
        remaining = self.resets_at - (time.time() if now is None else now)
        if remaining <= 0:
            return "正在重置"
        if remaining < 60:
            return "不到 1 分钟后重置"
        if remaining < 3600:
            return f"{math.ceil(remaining / 60)} 分钟后重置"
        if remaining < 86400:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            return f"{hours} 小时 {minutes} 分后重置" if minutes else f"{hours} 小时后重置"
        days = int(remaining // 86400)
        hours = int((remaining % 86400) // 3600)
        return f"{days} 天 {hours} 小时后重置" if hours else f"{days} 天后重置"


@dataclass(frozen=True)
class Credits:
    has_credits: bool = False
    unlimited: bool = False
    balance: str | None = None

    @classmethod
    def from_mapping(cls, data: Any) -> "Credits | None":
        if not isinstance(data, dict):
            return None
        balance = data.get("balance")
        return cls(
            has_credits=bool(_value(data, "hasCredits", "has_credits")),
            unlimited=bool(data.get("unlimited")),
            balance=None if balance is None else str(balance),
        )

    @property
    def should_show(self) -> bool:
        return self.unlimited or self.has_credits or self.balance not in (None, "", "0", "0.0")

    def display_text(self) -> str:
        if self.unlimited:
            return "Credits：不限量"
        if self.balance not in (None, ""):
            return f"Credits：{self.balance}"
        return "Credits：可用" if self.has_credits else "Credits：暂无"


@dataclass(frozen=True)
class RateBucket:
    limit_id: str | None
    limit_name: str | None
    plan_type: str | None
    primary: RateWindow | None
    secondary: RateWindow | None
    credits: Credits | None

    @classmethod
    def from_mapping(cls, data: Any) -> "RateBucket | None":
        if not isinstance(data, dict):
            return None
        return cls(
            limit_id=_value(data, "limitId", "limit_id"),
            limit_name=_value(data, "limitName", "limit_name"),
            plan_type=_value(data, "planType", "plan_type"),
            primary=RateWindow.from_mapping(data.get("primary")),
            secondary=RateWindow.from_mapping(data.get("secondary")),
            credits=Credits.from_mapping(data.get("credits")),
        )

    def windows(self) -> Iterable[tuple[str, RateWindow]]:
        if self.primary:
            yield "主额度", self.primary
        if self.secondary:
            yield "次额度", self.secondary


@dataclass(frozen=True)
class DisplayRow:
    label: str
    window: RateWindow


@dataclass(frozen=True)
class UsageSnapshot:
    buckets: tuple[RateBucket, ...]
    received_at: datetime

    @classmethod
    def from_response(cls, response: Any) -> "UsageSnapshot":
        if not isinstance(response, dict):
            raise ValueError("限额响应不是对象。")

        buckets: list[RateBucket] = []
        by_id = _value(response, "rateLimitsByLimitId", "rate_limits_by_limit_id")
        if isinstance(by_id, dict):
            for limit_id, value in sorted(by_id.items(), key=lambda item: (item[0] != "codex", item[0])):
                bucket = RateBucket.from_mapping(value)
                if bucket:
                    if not bucket.limit_id:
                        bucket = replace(bucket, limit_id=str(limit_id))
                    buckets.append(bucket)

        if not buckets:
            legacy = _value(response, "rateLimits", "rate_limits")
            bucket = RateBucket.from_mapping(legacy)
            if bucket:
                buckets.append(bucket)

        if not buckets:
            raise ValueError("Codex 没有返回可显示的套餐限额。")
        return cls(tuple(buckets), datetime.now().astimezone())

    @classmethod
    def from_notification(cls, params: Any) -> "UsageSnapshot":
        if not isinstance(params, dict):
            raise ValueError("限额更新通知不是对象。")
        if "rateLimits" in params or "rate_limits" in params:
            return cls.from_response(params)
        return cls.from_response({"rateLimits": params})

    @property
    def plan_type(self) -> str:
        for bucket in self.buckets:
            if bucket.plan_type:
                return bucket.plan_type.upper()
        return "CODEX"

    @property
    def credits(self) -> Credits | None:
        for bucket in self.buckets:
            if bucket.credits:
                return bucket.credits
        return None

    def display_rows(self, limit: int = 3) -> tuple[DisplayRow, ...]:
        rows: list[DisplayRow] = []
        multiple_buckets = len(self.buckets) > 1
        for bucket in self.buckets:
            prefix = bucket.limit_name or bucket.limit_id or "Codex"
            windows = tuple(bucket.windows())
            for fallback, window in windows:
                label = window.duration_label(fallback)
                if multiple_buckets:
                    label = f"{prefix} · {label}"
                rows.append(DisplayRow(label, window))
        return tuple(rows[: max(1, limit)])

    @property
    def minimum_remaining(self) -> int | None:
        values = [row.window.remaining_percent for row in self.display_rows(limit=20)]
        return min(values) if values else None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "planType": self.plan_type,
            "updatedAt": self.received_at.isoformat(),
            "limits": [
                {
                    "label": row.label,
                    "usedPercent": row.window.used_percent,
                    "remainingPercent": row.window.remaining_percent,
                    "windowDurationMins": row.window.duration_minutes,
                    "resetsAt": row.window.resets_at,
                }
                for row in self.display_rows(limit=20)
            ],
            "credits": None
            if self.credits is None
            else {
                "hasCredits": self.credits.has_credits,
                "unlimited": self.credits.unlimited,
                "balance": self.credits.balance,
            },
        }

