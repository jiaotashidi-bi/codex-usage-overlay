from __future__ import annotations

import os
import sys
from pathlib import Path


STARTUP_FILENAME = "Codex Usage Overlay.vbs"
LEGACY_STARTUP_FILENAMES = ("xiexie Codex Usage Overlay.lnk",)


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return Path.home() / ".config" / "autostart"


def startup_path() -> Path:
    return startup_dir() / STARTUP_FILENAME


def is_startup_enabled() -> bool:
    directory = startup_dir()
    return startup_path().exists() or any((directory / name).exists() for name in LEGACY_STARTUP_FILENAMES)


def project_main_path() -> Path:
    return Path(__file__).resolve().parent.parent / "main.py"


def pythonw_path(executable: str | Path | None = None) -> Path:
    python = Path(executable or sys.executable).resolve()
    if os.name == "nt" and python.name.lower() == "python.exe":
        candidate = python.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return python


def set_startup(enabled: bool, executable: str | Path | None = None, main_path: Path | None = None) -> Path:
    directory = startup_dir()
    target = startup_path()
    legacy_paths = [directory / name for name in LEGACY_STARTUP_FILENAMES]

    if not enabled:
        for path in (target, *legacy_paths):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return target

    directory.mkdir(parents=True, exist_ok=True)
    pythonw = pythonw_path(executable)
    entry = (main_path or project_main_path()).resolve()
    if not pythonw.exists():
        raise FileNotFoundError(f"pythonw executable not found: {pythonw}")
    if not entry.exists():
        raise FileNotFoundError(f"overlay entry point not found: {entry}")

    command = f'"{pythonw}" "{entry}"'
    working_directory = str(entry.parent).replace('"', '""')
    command_literal = command.replace('"', '""')
    script = (
        'Set shell = CreateObject("WScript.Shell")\r\n'
        f'shell.CurrentDirectory = "{working_directory}"\r\n'
        f'shell.Run "{command_literal}", 0, False\r\n'
    )
    temporary = target.with_suffix(".tmp")
    temporary.write_text(script, encoding="utf-16")
    temporary.replace(target)
    for path in legacy_paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return target


def migrate_legacy_startup(executable: str | Path | None = None, main_path: Path | None = None) -> bool:
    directory = startup_dir()
    has_legacy = any((directory / name).exists() for name in LEGACY_STARTUP_FILENAMES)
    if not has_legacy or startup_path().exists():
        return False
    set_startup(True, executable=executable, main_path=main_path)
    return True
