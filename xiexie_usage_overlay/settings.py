from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def app_data_dir() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"])
    else:
        root = Path.home() / ".local" / "share"
    return root / "xiexie-usage-overlay"


@dataclass
class Settings:
    x: int | None = None
    y: int | None = None
    refresh_seconds: int = 60
    always_on_top: bool = True
    warning_threshold: int = 20
    follow_offset_x: int = 0
    follow_offset_y: int = 0

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        settings = cls(
            x=data.get("x") if isinstance(data.get("x"), int) else None,
            y=data.get("y") if isinstance(data.get("y"), int) else None,
            refresh_seconds=data.get("refresh_seconds", 60),
            always_on_top=bool(data.get("always_on_top", True)),
            warning_threshold=data.get("warning_threshold", 20),
            follow_offset_x=data.get("follow_offset_x", 0),
            follow_offset_y=data.get("follow_offset_y", 0),
        )
        settings.refresh_seconds = max(30, min(900, int(settings.refresh_seconds)))
        settings.warning_threshold = max(1, min(50, int(settings.warning_threshold)))
        settings.follow_offset_x = int(settings.follow_offset_x) if isinstance(settings.follow_offset_x, int) else 0
        settings.follow_offset_y = int(settings.follow_offset_y) if isinstance(settings.follow_offset_y, int) else 0
        return settings

    def save(self) -> None:
        directory = app_data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
