from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable


class AppServerError(RuntimeError):
    """Raised when the local Codex app-server cannot satisfy a request."""


NotificationHandler = Callable[[dict[str, Any]], None]


def _windows_command_for(executable: Path) -> list[str]:
    if executable.suffix.lower() in {".cmd", ".bat"}:
        root = executable.parent
        node = root / "node.exe"
        script = root / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if node.exists() and script.exists():
            return [str(node), str(script), "app-server"]

        comspec = os.environ.get("ComSpec", "cmd.exe")
        command_text = subprocess.list2cmdline([str(executable), "app-server"])
        return [comspec, "/d", "/s", "/c", command_text]

    return [str(executable), "app-server"]


def resolve_app_server_command() -> list[str]:
    """Resolve a launch command without exposing or copying Codex credentials."""

    override = os.environ.get("XIEXIE_CODEX_BIN")
    if override:
        path = Path(os.path.expandvars(os.path.expanduser(override))).resolve()
        if not path.exists():
            raise AppServerError(f"XIEXIE_CODEX_BIN 指向的文件不存在：{path}")
        return _windows_command_for(path) if os.name == "nt" else [str(path), "app-server"]

    if os.name == "nt":
        wrapper = shutil.which("codex.cmd") or shutil.which("codex")
        if wrapper:
            return _windows_command_for(Path(wrapper))

        native = shutil.which("codex.exe")
        if native:
            return [native, "app-server"]
    else:
        native = shutil.which("codex")
        if native:
            return [native, "app-server"]

    raise AppServerError("没有找到 Codex CLI。请先确认终端中可以运行 codex --version。")


class CodexAppServerClient:
    def __init__(self, request_timeout: float = 15.0) -> None:
        self.request_timeout = request_timeout
        self._process: subprocess.Popen[str] | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._request_id = 0
        self._closing = threading.Event()
        self._handlers: list[NotificationHandler] = []
        self._stderr_tail: deque[str] = deque(maxlen=20)

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def add_notification_handler(self, handler: NotificationHandler) -> None:
        self._handlers.append(handler)

    def start(self) -> None:
        if self.is_running:
            return

        self._closing.clear()
        command = resolve_app_server_command()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise AppServerError(f"无法启动 Codex App Server：{exc}") from exc

        threading.Thread(target=self._read_stdout, name="codex-app-server-stdout", daemon=True).start()
        threading.Thread(target=self._read_stderr, name="codex-app-server-stderr", daemon=True).start()

        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "xiexie_usage_overlay",
                        "title": "xiexie Usage Overlay",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.notify("initialized", {})
        except Exception:
            self.close()
            raise

    def read_rate_limits(self) -> dict[str, Any]:
        result = self.request("account/rateLimits/read", None)
        if not isinstance(result, dict):
            raise AppServerError("Codex 返回了无法识别的限额数据。")
        return result

    def request(self, method: str, params: Any, timeout: float | None = None) -> Any:
        if not self.is_running or self._process is None:
            raise AppServerError("Codex App Server 尚未运行。")

        with self._pending_lock:
            self._request_id += 1
            request_id = self._request_id
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue

        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params

        try:
            self._send(message)
            try:
                response = response_queue.get(timeout=timeout or self.request_timeout)
            except queue.Empty as exc:
                detail = self._diagnostic_tail()
                raise AppServerError(f"等待 Codex 响应超时。{detail}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if "error" in response:
            error = response.get("error") or {}
            message_text = error.get("message") if isinstance(error, dict) else str(error)
            raise AppServerError(f"Codex 请求失败：{message_text}")
        return response.get("result")

    def notify(self, method: str, params: Any) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def close(self) -> None:
        self._closing.set()
        process = self._process
        self._process = None
        if process is None:
            return

        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

        self._fail_pending("Codex App Server 已关闭。")

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise AppServerError(f"Codex App Server 已退出。{self._diagnostic_tail()}")

        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                process.stdin.write(payload)
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AppServerError(f"与 Codex 的本地连接已断开。{self._diagnostic_tail()}") from exc

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue

            request_id = message.get("id")
            if isinstance(request_id, int):
                with self._pending_lock:
                    response_queue = self._pending.get(request_id)
                if response_queue is not None:
                    try:
                        response_queue.put_nowait(message)
                    except queue.Full:
                        pass
                continue

            if message.get("method"):
                for handler in tuple(self._handlers):
                    try:
                        handler(message)
                    except Exception:
                        continue

        if not self._closing.is_set():
            self._fail_pending(f"Codex App Server 意外退出。{self._diagnostic_tail()}")

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        for line in process.stderr:
            clean = ansi.sub("", line).strip()
            if clean:
                self._stderr_tail.append(clean)

    def _diagnostic_tail(self) -> str:
        if not self._stderr_tail:
            return ""
        return f" 最近的 Codex 信息：{self._stderr_tail[-1][:240]}"

    def _fail_pending(self, message: str) -> None:
        response = {"error": {"code": -1, "message": message}}
        with self._pending_lock:
            queues = tuple(self._pending.values())
        for response_queue in queues:
            try:
                response_queue.put_nowait(response)
            except queue.Full:
                pass

    def __enter__(self) -> "CodexAppServerClient":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

