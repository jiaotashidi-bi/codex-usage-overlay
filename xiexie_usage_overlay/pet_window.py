from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


WS_CAPTION = 0x00C00000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    rect: Rect
    visible: bool
    cloaked: bool
    title: str
    class_name: str
    process_name: str
    style: int
    ex_style: int
    process_id: int = 0


class PetPresenceDebouncer:
    """Keep the pet present through brief, consecutive detection misses."""

    def __init__(self, miss_threshold: int = 10) -> None:
        if miss_threshold < 1:
            raise ValueError("miss_threshold must be at least 1")
        self.miss_threshold = miss_threshold
        self.consecutive_misses = 0
        self.present = False

    def observe(self, found: bool) -> bool:
        if found:
            self.consecutive_misses = 0
            self.present = True
        elif self.present:
            self.consecutive_misses += 1
            if self.consecutive_misses >= self.miss_threshold:
                self.consecutive_misses = 0
                self.present = False
        return self.present


def pet_candidate_score(window: WindowInfo) -> int | None:
    """Score the special transparent ChatGPT pet overlay, excluding the main app window."""

    if not window.visible or window.cloaked:
        return None
    if window.rect.width < 120 or window.rect.height < 120:
        return None
    if window.rect.width > 1800 or window.rect.height > 1800:
        return None
    if not window.ex_style & WS_EX_TOOLWINDOW:
        return None
    if not window.ex_style & WS_EX_LAYERED:
        return None

    process_name = window.process_name.lower()
    if process_name and not any(name in process_name for name in ("chatgpt", "codex", "openai")):
        return None

    score = 100
    if window.class_name == "Chrome_WidgetWin_1":
        score += 30
    if window.ex_style & WS_EX_TOPMOST:
        score += 20
    if window.ex_style & WS_EX_TRANSPARENT:
        score += 20
    if not window.style & WS_CAPTION:
        score += 10
    if window.title.lower() in {"chatgpt", "codex"}:
        score += 8
    if process_name:
        score += 8
    return score


def calculate_follow_position(
    pet_rect: Rect,
    overlay_width: int,
    overlay_height: int,
    pointer_offset_y: int,
    gap: int,
    work_area: Rect,
    offset_x: int = 0,
    offset_y: int = 0,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return the clamped target and the raw zero-offset base position."""

    # The character occupies the lower-right part of the transparent pet host.
    # Anchor the bubble's right-side pointer near her left shoulder.
    pet_anchor_x = pet_rect.right - round(pet_rect.width * 0.310)
    pet_anchor_y = pet_rect.bottom - round(pet_rect.height * 0.290)
    base_x = pet_anchor_x - overlay_width - gap
    base_y = pet_anchor_y - pointer_offset_y

    target_x = base_x + offset_x
    target_y = base_y + offset_y
    max_x = max(work_area.left, work_area.right - overlay_width)
    max_y = max(work_area.top, work_area.bottom - overlay_height)
    target_x = max(work_area.left, min(target_x, max_x))
    target_y = max(work_area.top, min(target_y, max_y))
    return (target_x, target_y), (base_x, base_y)


if os.name == "nt":
    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]


    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _RECT),
            ("rcWork", _RECT),
            ("dwFlags", wintypes.DWORD),
        ]


class PetWindowLocator:
    supported = os.name == "nt"
    FULL_SCAN_INTERVAL_SECONDS = 0.75

    def __init__(self) -> None:
        self._last_handle: int | None = None
        self._last_process_id: int | None = None
        self._last_process_name = ""
        self._next_full_scan_at = 0.0
        if not self.supported:
            return

        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.dwmapi = ctypes.windll.dwmapi
        self._enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        self.user32.EnumWindows.argtypes = [self._enum_proc_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user32.MonitorFromWindow.restype = wintypes.HMONITOR
        self.user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        self.user32.GetMonitorInfoW.restype = wintypes.BOOL

        get_long = self.user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else self.user32.GetWindowLongW
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        self._get_window_long = get_long

        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def find(self) -> WindowInfo | None:
        if not self.supported:
            return None

        if self._last_handle is not None:
            cached = self._read_window(self._last_handle)
            if cached is not None and pet_candidate_score(cached) is not None:
                self._remember(cached)
                return cached
            self._forget_cached_window()

        now = time.monotonic()
        if now < self._next_full_scan_at:
            return None
        self._next_full_scan_at = now + self.FULL_SCAN_INTERVAL_SECONDS

        candidates: list[tuple[int, WindowInfo]] = []

        @self._enum_proc_type
        def callback(hwnd, _lparam):
            info = self._read_window(hwnd)
            if info:
                score = pet_candidate_score(info)
                if score is not None:
                    candidates.append((score, info))
            return True

        self.user32.EnumWindows(callback, 0)
        if not candidates:
            self._forget_cached_window()
            return None
        candidates.sort(key=lambda pair: (pair[0], -(pair[1].rect.width * pair[1].rect.height)), reverse=True)
        selected = candidates[0][1]
        self._remember(selected)
        return selected

    def _remember(self, window: WindowInfo) -> None:
        self._last_handle = window.handle
        self._last_process_id = window.process_id
        self._last_process_name = window.process_name

    def _forget_cached_window(self) -> None:
        self._last_handle = None
        self._last_process_id = None
        self._last_process_name = ""

    def work_area(self, hwnd: int) -> Rect:
        if not self.supported:
            return Rect(0, 0, 32767, 32767)
        monitor = self.user32.MonitorFromWindow(wintypes.HWND(hwnd), 2)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if monitor and self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return Rect(info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom)
        return Rect(0, 0, self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1))

    def _read_window(self, hwnd) -> WindowInfo | None:
        rect = _RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        visible = bool(self.user32.IsWindowVisible(hwnd))
        title = self._window_string(self.user32.GetWindowTextW, hwnd)
        class_name = self._window_string(self.user32.GetClassNameW, hwnd)
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        cloaked = self._is_cloaked(hwnd)
        style = int(self._get_window_long(hwnd, -16))
        ex_style = int(self._get_window_long(hwnd, -20))
        process_id = int(pid.value)
        cached_process_name = (
            self._last_process_name
            if int(hwnd) == self._last_handle and process_id == self._last_process_id
            else None
        )
        preliminary = WindowInfo(
            handle=int(hwnd),
            rect=Rect(rect.left, rect.top, rect.right, rect.bottom),
            visible=visible,
            cloaked=cloaked,
            title=title,
            class_name=class_name,
            process_name=cached_process_name or "",
            style=style,
            ex_style=ex_style,
            process_id=process_id,
        )
        if cached_process_name is not None or pet_candidate_score(preliminary) is None:
            return preliminary
        return WindowInfo(
            handle=preliminary.handle,
            rect=preliminary.rect,
            visible=preliminary.visible,
            cloaked=preliminary.cloaked,
            title=preliminary.title,
            class_name=preliminary.class_name,
            process_name=self._process_name(process_id),
            style=preliminary.style,
            ex_style=preliminary.ex_style,
            process_id=process_id,
        )

    @staticmethod
    def _window_string(function, hwnd) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        function(hwnd, buffer, len(buffer))
        return buffer.value

    def _process_name(self, pid: int) -> str:
        process = self.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if self.kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name
            return ""
        finally:
            self.kernel32.CloseHandle(process)

    def _is_cloaked(self, hwnd) -> bool:
        cloaked = wintypes.DWORD()
        result = self.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return result == 0 and bool(cloaked.value)
