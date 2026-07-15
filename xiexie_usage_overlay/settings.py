from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


CURRENT_LAYOUT_VERSION = 3


def app_data_dir() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"])
    else:
        root = Path.home() / ".local" / "share"
    return root / "xiexie-usage-overlay"


def _optional_int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, parsed))


def _boolean(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


@dataclass
class Settings:
    x: int | None = None
    y: int | None = None
    refresh_seconds: int = 60
    always_on_top: bool = True
    warning_threshold: int = 20
    follow_offset_x: int = 0
    follow_offset_y: int = 0
    layout_version: int = CURRENT_LAYOUT_VERSION

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        stored_layout_version = _bounded_int(
            data.get("layout_version", 1), 1, 1, CURRENT_LAYOUT_VERSION
        )
        settings = cls(
            x=_optional_int(data.get("x")),
            y=_optional_int(data.get("y")),
            refresh_seconds=_bounded_int(data.get("refresh_seconds", 60), 60, 30, 900),
            always_on_top=_boolean(data.get("always_on_top", True), True),
            warning_threshold=_bounded_int(data.get("warning_threshold", 20), 20, 1, 50),
            follow_offset_x=_bounded_int(data.get("follow_offset_x", 0), 0, -20_000, 20_000),
            follow_offset_y=_bounded_int(data.get("follow_offset_y", 0), 0, -20_000, 20_000),
            layout_version=CURRENT_LAYOUT_VERSION,
        )
        if stored_layout_version < CURRENT_LAYOUT_VERSION:
            settings.follow_offset_x = 0
            settings.follow_offset_y = 0
        return settings

    def save(self) -> None:
        directory = app_data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
