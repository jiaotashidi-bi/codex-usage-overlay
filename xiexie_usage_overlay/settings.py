from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


CURRENT_LAYOUT_VERSION = 4
SIZE_MODES = {"auto", "small", "medium", "large", "custom"}
SIZE_MULTIPLIERS = {"auto": 1.0, "small": 0.85, "medium": 1.0, "large": 1.15}


def app_data_dir() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"])
    else:
        root = Path.home() / ".local" / "share"
    return root / "codex-usage-overlay"


def legacy_app_data_dir() -> Path:
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


def _bounded_float(value, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, parsed))


def _size_mode(value) -> str:
    return value if isinstance(value, str) and value in SIZE_MODES else "auto"


@dataclass
class Settings:
    x: int | None = None
    y: int | None = None
    refresh_seconds: int = 60
    always_on_top: bool = True
    warning_threshold: int = 20
    size_mode: str = "auto"
    size_adjust: float = 1.0
    start_with_windows: bool = False
    follow_offset_x: int = 0
    follow_offset_y: int = 0
    layout_version: int = CURRENT_LAYOUT_VERSION

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        source = path if path.exists() else legacy_app_data_dir() / "settings.json"
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
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
            size_mode=_size_mode(data.get("size_mode", "auto")),
            size_adjust=_bounded_float(data.get("size_adjust", 1.0), 1.0, 0.7, 1.5),
            start_with_windows=_boolean(data.get("start_with_windows", False), False),
            follow_offset_x=_bounded_int(data.get("follow_offset_x", 0), 0, -20_000, 20_000),
            follow_offset_y=_bounded_int(data.get("follow_offset_y", 0), 0, -20_000, 20_000),
            layout_version=CURRENT_LAYOUT_VERSION,
        )
        if stored_layout_version < CURRENT_LAYOUT_VERSION:
            settings.follow_offset_x = 0
            settings.follow_offset_y = 0
        if source != path:
            settings.save()
        return settings

    @property
    def size_multiplier(self) -> float:
        if self.size_mode == "custom":
            return self.size_adjust
        return SIZE_MULTIPLIERS.get(self.size_mode, 1.0)

    def save(self) -> None:
        directory = app_data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
