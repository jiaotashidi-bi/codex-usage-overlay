from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


_SELECTED_AVATAR_RE = re.compile(
    r"^\s*selected-avatar-id\s*=\s*([\"'])(?P<value>.+?)\1\s*(?:#.*)?$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class PetIdentity:
    avatar_id: str
    display_name: str
    source: str


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def sanitize_display_name(value: object, fallback: str = "Codex") -> str:
    if not isinstance(value, str):
        return fallback
    printable = "".join(" " if unicodedata.category(char).startswith("C") else char for char in value)
    clean = " ".join(printable.split()).strip()
    return clean[:64] or fallback


def compact_display_name(value: str, max_columns: int = 8) -> str:
    """Fit a pet name into the compact header using approximate display columns."""

    clean = sanitize_display_name(value)
    width = 0
    result: list[str] = []
    for char in clean:
        char_width = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if width + char_width > max_columns:
            break
        result.append(char)
        width += char_width
    if len(result) == len(clean):
        return clean
    while result and width + 1 > max_columns:
        removed = result.pop()
        width -= 2 if unicodedata.east_asian_width(removed) in {"W", "F"} else 1
    return "".join(result) + "…"


class PetIdentityResolver:
    """Resolve the currently selected Codex pet from local Codex metadata only."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = (home or codex_home()).expanduser()

    def resolve(self) -> PetIdentity:
        avatar_id = self._read_selected_avatar_id()
        if not avatar_id:
            return PetIdentity("", "Codex", "fallback")

        if avatar_id.startswith("custom:"):
            pet_id = avatar_id.removeprefix("custom:").strip()
            display_name = self._read_custom_display_name(pet_id)
            return PetIdentity(avatar_id, display_name, "custom")

        builtin_id = avatar_id.split(":", 1)[-1].strip()
        display_name = sanitize_display_name(builtin_id.replace("-", " ").replace("_", " "), "Codex")
        return PetIdentity(avatar_id, display_name, "builtin")

    def _read_selected_avatar_id(self) -> str:
        try:
            text = (self.home / "config.toml").read_text(encoding="utf-8-sig")
        except OSError:
            return ""
        match = _SELECTED_AVATAR_RE.search(text)
        return match.group("value").strip() if match else ""

    def _read_custom_display_name(self, pet_id: str) -> str:
        fallback = sanitize_display_name(pet_id, "Codex")
        manifest = self._safe_manifest_path(pet_id)
        if manifest is None:
            return "Codex"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return fallback
        if not isinstance(data, dict):
            return fallback
        return sanitize_display_name(data.get("displayName"), fallback)

    def _safe_manifest_path(self, pet_id: str) -> Path | None:
        if not pet_id or "\x00" in pet_id:
            return None
        pets_root = (self.home / "pets").resolve()
        candidate = (pets_root / pet_id / "pet.json").resolve()
        if candidate.parent.parent != pets_root:
            return None
        return candidate
