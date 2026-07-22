from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from xiexie_usage_overlay.app_server import CodexAppServerClient
    from xiexie_usage_overlay.overlay import UsageOverlay
    from xiexie_usage_overlay.service import DemoUsageService, UsageService
    from xiexie_usage_overlay.settings import Settings, app_data_dir
    from xiexie_usage_overlay.startup import is_startup_enabled, migrate_legacy_startup, set_startup
    from xiexie_usage_overlay.usage import UsageSnapshot
else:
    from .app_server import CodexAppServerClient
    from .overlay import UsageOverlay
    from .service import DemoUsageService, UsageService
    from .settings import Settings, app_data_dir
    from .startup import is_startup_enabled, migrate_legacy_startup, set_startup
    from .usage import UsageSnapshot


_mutex_handle = None


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _acquire_single_instance() -> bool:
    global _mutex_handle
    if os.name != "nt":
        return True
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\codex_usage_overlay")
    return ctypes.windll.kernel32.GetLastError() != 183


def _configure_logging() -> None:
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "overlay.log", maxBytes=300_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _show_fatal_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Codex Usage Overlay", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="跟随当前 Codex 宠物的套餐余量悬浮窗")
    parser.add_argument("--once", action="store_true", help="读取一次并输出 JSON，不打开界面")
    parser.add_argument("--demo", action="store_true", help="使用演示数据打开界面")
    parser.add_argument("--reset-position", action="store_true", help="忘记上次保存的悬浮位置")
    parser.add_argument("--refresh-seconds", type=int, help="轮询间隔，最短 30 秒")
    parser.add_argument(
        "--view",
        choices=("smart", "compact", "expanded"),
        help="仅本次运行覆盖界面形态",
    )
    parser.add_argument("--install-startup", action="store_true", help="安装当前用户的 Windows 开机启动项")
    parser.add_argument("--uninstall-startup", action="store_true", help="删除当前用户的 Windows 开机启动项")
    return parser.parse_args()


def run_once() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with CodexAppServerClient() as client:
        snapshot = UsageSnapshot.from_response(client.read_rate_limits())
    print(json.dumps(snapshot.to_safe_dict(), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    if args.once:
        return run_once()
    if args.install_startup or args.uninstall_startup:
        enabled = bool(args.install_startup)
        path = set_startup(enabled)
        settings = Settings.load()
        settings.start_with_windows = enabled
        settings.save()
        action = "已安装" if enabled else "已删除"
        print(f"{action}开机启动项：{path}")
        return 0

    _enable_dpi_awareness()
    _configure_logging()
    if not _acquire_single_instance():
        return 0

    try:
        settings = Settings.load()
        try:
            migrate_legacy_startup()
        except OSError:
            logging.warning("Unable to migrate the legacy startup entry", exc_info=True)
        startup_enabled = is_startup_enabled()
        if settings.start_with_windows != startup_enabled:
            settings.start_with_windows = startup_enabled
            settings.save()
        if args.reset_position:
            settings.x = None
            settings.y = None
        if args.refresh_seconds is not None:
            settings.refresh_seconds = max(30, min(900, args.refresh_seconds))
        if args.view is not None:
            settings.interface_mode = args.view

        if args.demo:
            service_factory = lambda handler: DemoUsageService(handler)
        else:
            service_factory = lambda handler: UsageService(
                handler,
                settings.refresh_seconds,
                history_enabled=settings.history_enabled,
            )
        UsageOverlay(settings, service_factory).run()
    except Exception as exc:
        logging.exception("overlay failed")
        _show_fatal_error(f"Codex 余量悬浮窗启动失败：\n{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
