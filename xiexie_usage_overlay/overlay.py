from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Protocol

from .companion import UsageInsight
from .pet_identity import PetIdentityResolver, compact_display_name
from .pet_window import (
    PetPresenceDebouncer,
    PetWindowLocator,
    WindowInfo,
    calculate_follow_position,
    display_scale_factor,
)
from .service import ServiceEvent
from .settings import Settings
from .startup import is_startup_enabled, set_startup
from .usage import UsageSnapshot


logger = logging.getLogger(__name__)


class OverlayService(Protocol):
    def start(self) -> None: ...

    def refresh_now(self) -> None: ...

    def set_refresh_seconds(self, seconds: int) -> None: ...

    def set_history_enabled(self, enabled: bool) -> None: ...

    def stop(self) -> None: ...


class UsageOverlay:
    WIDTH = 190
    REFERENCE_SCALE_X = 1.36
    REFERENCE_SCALE_Y = 150 / 89
    IDENTITY_POLL_MS = 2_000
    PET_MISS_THRESHOLD = 10
    TRANSPARENT = "#010203"
    BODY = "#FFF9E9"
    BODY_BORDER = "#D7E2EF"
    INK = "#26384D"
    MUTED = "#718096"
    BLUE = "#5E86B8"
    BLUE_SOFT = "#E9F0F8"
    GREEN = "#58A77A"
    AMBER = "#D7A33D"
    CORAL = "#D96F62"
    BAR_BG = "#E3E8EE"

    def __init__(self, settings: Settings, service_factory) -> None:
        self.settings = settings
        self._identity_resolver = PetIdentityResolver()
        self._identity = self._identity_resolver.resolve()
        self._pet_name = self._identity.display_name
        self._pet_locator = PetWindowLocator() if PetWindowLocator.supported else None
        self.root = tk.Tk()
        self.root.title(f"{self._pet_name} Codex 余量")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", settings.always_on_top)
        self.root.configure(bg=self.TRANSPARENT)
        is_windows = self.root.tk.call("tk", "windowingsystem") == "win32"
        if is_windows:
            self.root.wm_attributes("-transparentcolor", self.TRANSPARENT)
        self._display_dpi = self._pet_locator.system_dpi() if self._pet_locator is not None else 96
        self._scale_x, self._scale_y = self._calculate_scales(self._display_dpi)
        self._pixel_width = round(self.WIDTH * self._scale_x)

        self.canvas = tk.Canvas(
            self.root,
            width=self._pixel_width,
            height=round(89 * self._scale_y),
            bg=self.TRANSPARENT,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._events: queue.Queue[ServiceEvent] = queue.Queue()
        self._service: OverlayService = service_factory(self._events.put)
        self._snapshot: UsageSnapshot | None = None
        self._insight: UsageInsight | None = None
        self._data_source = "live"
        self._connection_error = ""
        self._status = "loading"
        self._error = ""
        self._height = 89
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._drag_moved = False
        self._expanded = settings.interface_mode == "expanded"
        self._expanded_locked = settings.interface_mode == "expanded"
        self._collapse_job: str | None = None
        self._closing = False
        self._pet_presence = PetPresenceDebouncer(self.PET_MISS_THRESHOLD)
        self._pet_window: WindowInfo | None = None
        self._pet_shown = self._pet_locator is None
        self._follow_base: tuple[int, int] | None = None
        self._settings_window: tk.Toplevel | None = None

        self._menu = tk.Menu(self.root, tearoff=False, font=("Microsoft YaHei UI", 9))
        self._menu.add_command(label="立即刷新", command=self._service.refresh_now)
        self._menu.add_command(label="设置…", command=self._open_settings)
        self._topmost_var = tk.BooleanVar(value=settings.always_on_top)
        self._menu.add_checkbutton(label="保持置顶", variable=self._topmost_var, command=self._toggle_topmost)
        if self._pet_locator is not None:
            self._menu.add_command(label="重置跟随位置", command=self._reset_follow_position)
        self._menu.add_separator()
        self._menu.add_command(label=f"退出 {self._pet_name} 余量", command=self.close)
        self._exit_menu_index = self._menu.index("end")

        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)
        self.canvas.bind("<Double-Button-1>", lambda _event: self._service.refresh_now())
        self.canvas.bind("<Button-3>", self._show_menu)
        self.canvas.bind("<Enter>", self._pointer_enter)
        self.canvas.bind("<Leave>", self._pointer_leave)
        self.canvas.tag_bind("refresh", "<Button-1>", self._refresh_clicked)
        self.canvas.tag_bind("close", "<Button-1>", self._close_clicked)
        self.root.bind("<Escape>", lambda _event: self.close())

        self._place_initially()
        self._draw_loading("正在读取 Codex 余量…")
        if self._pet_locator is not None:
            self.root.withdraw()
            self.root.after(50, self._sync_to_pet)
        self.root.after(100, self._drain_events)
        self.root.after(30_000, self._tick)
        self.root.after(self.IDENTITY_POLL_MS, self._sync_pet_identity)
        self._service.start()

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._save_position()
        self._service.stop()
        self.root.destroy()

    def _calculate_scales(self, dpi: int) -> tuple[float, float]:
        factor = display_scale_factor(dpi, self.settings.size_multiplier)
        return self.REFERENCE_SCALE_X * factor, self.REFERENCE_SCALE_Y * factor

    def _apply_display_scale(self, dpi: int, force: bool = False) -> bool:
        dpi = max(72, min(int(dpi or 96), 768))
        scale_x, scale_y = self._calculate_scales(dpi)
        if not force and abs(scale_x - self._scale_x) < 0.001 and abs(scale_y - self._scale_y) < 0.001:
            self._display_dpi = dpi
            return False

        self.root.update_idletasks()
        old_height = round(self._height * self._scale_y)
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self._display_dpi = dpi
        self._scale_x = scale_x
        self._scale_y = scale_y
        self._pixel_width = round(self.WIDTH * self._scale_x)
        new_height = round(self._height * self._scale_y)
        new_y = max(0, y + old_height - new_height)
        self.canvas.configure(width=self._pixel_width, height=new_height)
        self.root.geometry(f"{self._pixel_width}x{new_height}+{x}+{new_y}")
        self._redraw()
        return True

    def _font(self, family: str, points: int, weight: str | None = None):
        factor = display_scale_factor(self._display_dpi, self.settings.size_multiplier)
        reference_pixels = points * 192 / 72
        pixel_size = max(5, round(reference_pixels * factor))
        return (family, -pixel_size, weight) if weight else (family, -pixel_size)

    def _sync_pet_identity(self) -> None:
        if self._closing:
            return
        try:
            identity = self._identity_resolver.resolve()
            if identity != self._identity:
                logger.info(
                    "Selected Codex pet changed from %s to %s",
                    self._identity.avatar_id or "unknown",
                    identity.avatar_id or "unknown",
                )
                self._identity = identity
                self._pet_name = identity.display_name
                self.root.title(f"{self._pet_name} Codex 余量")
                self._menu.entryconfigure(self._exit_menu_index, label=f"退出 {self._pet_name} 余量")
                self._redraw()
        except Exception:
            logger.exception("Unable to refresh selected Codex pet identity")
        finally:
            if not self._closing:
                self.root.after(self.IDENTITY_POLL_MS, self._sync_pet_identity)

    def _place_initially(self) -> None:
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        pixel_height = round(self._height * self._scale_y)
        x = self.settings.x if self.settings.x is not None else screen_width - self._pixel_width - round(36 * self._scale_x)
        y = (
            self.settings.y
            if self.settings.y is not None
            else screen_height - pixel_height - round(260 * self._scale_y)
        )
        x = max(0, min(x, screen_width - self._pixel_width))
        y = max(0, min(y, screen_height - pixel_height))
        self.root.geometry(f"{self._pixel_width}x{pixel_height}+{x}+{y}")

    def _set_height(self, height: int) -> None:
        if height == self._height:
            return
        self.root.update_idletasks()
        x = self.root.winfo_x()
        old_pixel_height = round(self._height * self._scale_y)
        new_pixel_height = round(height * self._scale_y)
        y = self.root.winfo_y() + old_pixel_height - new_pixel_height
        self._height = height
        self.canvas.configure(height=new_pixel_height)
        self.root.geometry(f"{self._pixel_width}x{new_pixel_height}+{x}+{max(0, y)}")

    def _drain_events(self) -> None:
        if self._closing:
            return
        changed = False
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            changed = True
            self._status = event.kind
            if event.snapshot is not None:
                self._snapshot = event.snapshot
            if event.insight is not None:
                self._insight = event.insight
            self._data_source = event.source
            if event.kind == "error":
                self._connection_error = event.message or "暂时无法连接。"
            elif event.source == "live":
                self._connection_error = ""
            if event.message:
                self._error = event.message

        if changed:
            self._redraw()
        self.root.after(100, self._drain_events)

    def _tick(self) -> None:
        if self._closing:
            return
        if self._snapshot is not None:
            self._redraw()
        self.root.after(30_000, self._tick)

    def _sync_to_pet(self) -> None:
        if self._closing or self._pet_locator is None:
            return

        try:
            self._sync_to_pet_once()
        except Exception:
            logger.exception("Pet follow update failed; the loop will continue")
        finally:
            if not self._closing:
                try:
                    self.root.after(150, self._sync_to_pet)
                except tk.TclError:
                    pass

    def _sync_to_pet_once(self) -> None:
        if self._pet_locator is None:
            return

        pet = self._pet_locator.find()
        pet_present = self._pet_presence.observe(pet is not None)
        if pet is None and not pet_present:
            self._pet_window = None
            self._follow_base = None
            self._drag_origin = None
            if self._pet_shown:
                logger.info("Codex pet hidden; hiding usage overlay")
                self.root.withdraw()
                self._pet_shown = False
        elif pet is not None:
            self._pet_window = pet
            self._apply_display_scale(self._pet_locator.dpi(pet.handle))
            work_area = self._pet_locator.work_area(pet.handle)
            overlay_height = round(self._height * self._scale_y)
            pointer_offset_y = round(self._height * 0.50 * self._scale_y)
            gap = round(8 * self._scale_x)
            target, base = calculate_follow_position(
                pet.rect,
                self._pixel_width,
                overlay_height,
                pointer_offset_y,
                gap,
                work_area,
                self.settings.follow_offset_x,
                self.settings.follow_offset_y,
            )
            self._follow_base = base
            if self._drag_origin is None:
                x, y = target
                if abs(self.root.winfo_x() - x) > 1 or abs(self.root.winfo_y() - y) > 1:
                    self.root.geometry(f"{self._pixel_width}x{overlay_height}+{x}+{y}")
            if not self._pet_shown:
                logger.info("Codex pet visible; showing usage overlay")
                self.root.deiconify()
                self.root.attributes("-topmost", self.settings.always_on_top)
                self.root.lift()
                self._pet_shown = True

    def _redraw(self) -> None:
        if self._snapshot is not None:
            if self._should_compact():
                self._draw_compact(self._snapshot)
            else:
                self._draw_snapshot(self._snapshot)
        elif self._status == "error":
            self._draw_error(self._error)
        else:
            self._draw_loading(self._error or "正在读取 Codex 余量…")

    def _should_compact(self) -> bool:
        if self.settings.interface_mode == "compact":
            return True
        if self.settings.interface_mode == "expanded":
            return False
        return not self._expanded

    def _pointer_enter(self, _event=None) -> None:
        if self.settings.interface_mode != "smart" or self._expanded:
            return
        self._cancel_collapse()
        self._expanded = True
        self._redraw()

    def _pointer_leave(self, _event=None) -> None:
        if self.settings.interface_mode != "smart" or self._expanded_locked:
            return
        self._cancel_collapse()
        self._collapse_job = self.root.after(self.settings.collapse_seconds * 1000, self._collapse_smart_view)

    def _collapse_smart_view(self) -> None:
        self._collapse_job = None
        if self._closing or self.settings.interface_mode != "smart" or self._expanded_locked:
            return
        self._expanded = False
        self._redraw()

    def _cancel_collapse(self) -> None:
        if self._collapse_job is None:
            return
        try:
            self.root.after_cancel(self._collapse_job)
        except tk.TclError:
            pass
        self._collapse_job = None

    def _toggle_smart_lock(self) -> None:
        if self.settings.interface_mode != "smart":
            return
        self._cancel_collapse()
        self._expanded_locked = not self._expanded_locked
        self._expanded = self._expanded_locked
        self._redraw()

    def _draw_compact(self, snapshot: UsageSnapshot) -> None:
        rows = snapshot.display_rows(limit=20)
        limiting = min(rows, key=lambda row: row.window.remaining_percent) if rows else None
        remaining = limiting.window.remaining_percent if limiting else None
        status_color = self._status_color(snapshot, remaining)
        height = 40
        self._set_height(height)
        self.canvas.delete("all")
        body_right = self.WIDTH - 12
        body_bottom = height - 4
        pointer_y = height / 2
        self._rounded_rectangle(4, 4, body_right, body_bottom, 12, fill=self.BODY, outline=self.BODY_BORDER)
        self.canvas.create_polygon(
            body_right - 2,
            pointer_y - 8,
            body_right - 2,
            pointer_y + 8,
            self.WIDTH - 2,
            pointer_y,
            fill=self.BODY,
            outline=self.BODY_BORDER,
        )
        self.canvas.create_line(body_right - 2, pointer_y - 7, body_right - 2, pointer_y + 7, fill=self.BODY)
        self.canvas.create_oval(10, 16, 17, 23, fill=status_color, outline="")
        self.canvas.create_text(
            21,
            19.5,
            anchor="w",
            text=compact_display_name(self._pet_name, max_columns=6),
            fill=self.INK,
            font=self._font("Microsoft YaHei UI", 7, "bold"),
        )
        if remaining is not None:
            self.canvas.create_text(
                108,
                19.5,
                anchor="e",
                text=f"{remaining}%",
                fill=self._remaining_color(remaining),
                font=self._font("Microsoft YaHei UI", 8, "bold"),
            )
        self.canvas.create_line(113, 13, 113, 27, fill=self.BODY_BORDER)
        if self._connection_error:
            reset_text = "离线 · 重连中"
        elif self._data_source == "cache" or snapshot.is_stale(max(120, self.settings.refresh_seconds * 2 + 30)):
            reset_text = "上次数据"
        elif limiting is not None:
            reset_text = self._compact_reset_text(limiting.window.reset_text())
        else:
            reset_text = "正在读取"
        self.canvas.create_text(
            119,
            19.5,
            anchor="w",
            text=reset_text,
            fill=self.MUTED if not self._connection_error else self.CORAL,
            font=self._font("Microsoft YaHei UI", 6, "bold" if self._connection_error else None),
        )
        self._finish_drawing()

    def _draw_chrome(self, height: int, status_color: str) -> int:
        self._set_height(height)
        self.canvas.delete("all")
        body_right = self.WIDTH - 12
        body_bottom = height - 4
        pointer_y = max(30, min(height - 22, round(height * 0.50)))
        self._rounded_rectangle(4, 4, body_right, body_bottom, 14, fill=self.BODY, outline=self.BODY_BORDER)
        self.canvas.create_polygon(
            body_right - 2,
            pointer_y - 10,
            body_right - 2,
            pointer_y + 10,
            self.WIDTH - 2,
            pointer_y,
            fill=self.BODY,
            outline=self.BODY_BORDER,
        )
        self.canvas.create_line(body_right - 2, pointer_y - 9, body_right - 2, pointer_y + 9, fill=self.BODY)

        self.canvas.create_oval(11, 14, 18, 21, fill=status_color, outline="")
        self.canvas.create_text(
            23,
            17.5,
            anchor="w",
            text=f"{compact_display_name(self._pet_name)} 余量",
            fill=self.INK,
            font=self._font("Microsoft YaHei UI", 6, "bold"),
        )
        self.canvas.create_text(
            self.WIDTH - 42,
            17.5,
            text="↻",
            fill=self.BLUE,
            font=self._font("Segoe UI Symbol", 8, "bold"),
            tags=("refresh",),
        )
        self.canvas.create_text(
            self.WIDTH - 23,
            17.5,
            text="×",
            fill=self.MUTED,
            font=self._font("Segoe UI", 9),
            tags=("close",),
        )
        return body_bottom

    def _draw_loading(self, message: str) -> None:
        self._draw_chrome(78, self.AMBER)
        self.canvas.create_text(
            12,
            42,
            anchor="w",
            text=message,
            fill=self.INK,
            font=self._font("Microsoft YaHei UI", 6),
        )
        self.canvas.create_text(
            12,
            59,
            anchor="w",
            text="我在核对。",
            fill=self.MUTED,
            font=self._font("Microsoft YaHei UI", 6),
        )
        self._finish_drawing()

    def _draw_error(self, message: str) -> None:
        self._draw_chrome(104, self.CORAL)
        self.canvas.create_text(
            12,
            39,
            anchor="w",
            text="暂时读不到余量。",
            fill=self.INK,
            font=self._font("Microsoft YaHei UI", 6, "bold"),
        )
        short = self._short_error(message)
        self.canvas.create_text(
            12,
            53,
            anchor="nw",
            width=(self.WIDTH - 34) * self._scale_x,
            text=short,
            fill=self.MUTED,
            font=self._font("Microsoft YaHei UI", 6),
        )
        self.canvas.create_text(
            12,
            84,
            anchor="w",
            text="会自动重试，也可双击刷新。",
            fill=self.CORAL,
            font=self._font("Microsoft YaHei UI", 6, "bold"),
        )
        self._finish_drawing()

    def _draw_snapshot(self, snapshot: UsageSnapshot) -> None:
        rows = snapshot.display_rows(limit=2)
        credits = snapshot.credits
        show_credits = bool(credits and credits.should_show)
        pixel_height = self._snapshot_pixel_height(len(rows), show_credits)
        height = pixel_height / self.REFERENCE_SCALE_Y
        minimum = snapshot.minimum_remaining
        stale_after = max(120, self.settings.refresh_seconds * 2 + 30)
        is_stale = snapshot.is_stale(stale_after)
        status_color = self._status_color(snapshot, minimum)
        self._draw_chrome(height, status_color)

        pill_text = snapshot.plan_type[:12]
        pill_width = max(34, 10 + len(pill_text) * 5)
        pill_x2 = self.WIDTH - 53
        pill_x1 = pill_x2 - pill_width
        self._rounded_rectangle(pill_x1, 11, pill_x2, 24, 7, fill=self.BLUE_SOFT, outline="")
        self.canvas.create_text(
            (pill_x1 + pill_x2) / 2,
            17.5,
            text=pill_text,
            fill=self.BLUE,
            font=self._font("Segoe UI", 6, "bold"),
        )

        y = 35
        row_step = self._row_step(len(rows))
        if rows:
            for row in rows:
                self._draw_limit_row(y, row.label, row.window.remaining_percent, row.window.reset_text())
                y += row_step
        else:
            self.canvas.create_text(
                12,
                y + 12,
                anchor="w",
                text="Codex 暂未提供可显示的限额窗口。",
                fill=self.MUTED,
                font=self._font("Microsoft YaHei UI", 6),
            )
            y += 34

        has_two_rows = len(rows) >= 2
        if self._connection_error:
            personality = f"离线 · {self._age_text(snapshot)}更新，正在重连。"
        elif self._data_source == "cache" or is_stale:
            personality = f"先显示{self._age_text(snapshot)}的数据，我在重连。"
        elif self.settings.show_insights and self._insight is not None:
            personality = self._insight.message
        elif minimum is None:
            personality = "暂无百分比，我继续盯着。"
        elif minimum <= 10:
            personality = f"只剩 {minimum}%，快到顶了。"
        elif minimum <= self.settings.warning_threshold:
            personality = f"只剩 {minimum}%，省着点。"
        else:
            personality = "额度正常，我盯着。"
        self.canvas.create_text(
            12,
            y - 3 if has_two_rows else y + 1,
            anchor="nw",
            text=compact_display_name(personality, max_columns=64),
            width=(self.WIDTH - 34) * self._scale_x,
            justify="left",
            fill=self.CORAL if self._connection_error else status_color,
            font=self._font("Microsoft YaHei UI", 7, "bold"),
        )
        # Reserve room for an optional credits line in the 250 px layout.
        y += 24 if has_two_rows else 38

        if show_credits and credits:
            self.canvas.create_text(
                12,
                y + 1,
                anchor="w",
                text=credits.display_text(),
                fill=self.MUTED,
                font=self._font("Microsoft YaHei UI", 7),
            )
            y += 15
        self._finish_drawing()

    @staticmethod
    def _snapshot_pixel_height(row_count: int, show_credits: bool) -> int:
        if show_credits:
            return 250
        if row_count >= 2:
            return 230
        return 170

    @staticmethod
    def _row_step(row_count: int) -> int:
        return 38 if row_count >= 2 else 34

    def _draw_limit_row(self, y: int, label: str, remaining: int, reset_text: str) -> None:
        color = self._remaining_color(remaining)
        self.canvas.create_text(
            12,
            y,
            anchor="w",
            text=label,
            fill=self.INK,
            font=self._font("Microsoft YaHei UI", 8, "bold"),
        )
        self.canvas.create_text(
            self.WIDTH - 22,
            y,
            anchor="e",
            text=f"{remaining}%",
            fill=color,
            font=self._font("Microsoft YaHei UI", 8, "bold"),
        )

        x1, x2 = 12, self.WIDTH - 22
        bar_y1, bar_y2 = y + 10, y + 14
        self._rounded_rectangle(x1, bar_y1, x2, bar_y2, 4, fill=self.BAR_BG, outline="")
        fill_width = (x2 - x1) * remaining / 100
        if fill_width > 1:
            self._rounded_rectangle(x1, bar_y1, x1 + fill_width, bar_y2, 4, fill=color, outline="")
        self.canvas.create_text(
            12,
            y + 23,
            anchor="w",
            text=reset_text,
            fill=self.MUTED,
            font=self._font("Microsoft YaHei UI", 7),
        )

    def _remaining_color(self, remaining: int) -> str:
        if remaining <= self.settings.warning_threshold:
            return self.CORAL
        if remaining <= self.settings.amber_threshold:
            return self.AMBER
        return self.GREEN

    def _status_color(self, snapshot: UsageSnapshot, minimum: int | None) -> str:
        if self._connection_error or self._data_source == "cache":
            return self.CORAL
        if snapshot.is_stale(max(120, self.settings.refresh_seconds * 2 + 30)):
            return self.CORAL
        return self._remaining_color(minimum) if minimum is not None else self.GREEN

    @staticmethod
    def _compact_reset_text(value: str) -> str:
        return (
            value.replace("后重置", "")
            .replace("小时", "时")
            .replace("分钟", "分")
            .replace(" ", "")[:9]
        )

    @staticmethod
    def _age_text(snapshot: UsageSnapshot) -> str:
        age = snapshot.age_seconds()
        if age < 60:
            return "不到 1 分钟前"
        if age < 3600:
            return f"{max(1, round(age / 60))} 分钟前"
        if age < 86400:
            return f"{max(1, round(age / 3600))} 小时前"
        return f"{max(1, round(age / 86400))} 天前"

    def _rounded_rectangle(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _finish_drawing(self) -> None:
        if self._scale_x != 1.0 or self._scale_y != 1.0:
            self.canvas.scale("all", 0, 0, self._scale_x, self._scale_y)

    def _start_drag(self, event) -> None:
        current = self.canvas.gettags("current")
        if "refresh" in current or "close" in current:
            self._drag_origin = None
            return
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._drag_moved = False

    def _drag(self, event) -> None:
        if self._drag_origin is None:
            return
        mouse_x, mouse_y, window_x, window_y = self._drag_origin
        if abs(event.x_root - mouse_x) > 3 or abs(event.y_root - mouse_y) > 3:
            self._drag_moved = True
        x = window_x + event.x_root - mouse_x
        y = window_y + event.y_root - mouse_y
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event) -> None:
        if self._drag_origin is not None and self._drag_moved:
            if self._pet_window is not None and self._follow_base is not None:
                self.settings.follow_offset_x = self.root.winfo_x() - self._follow_base[0]
                self.settings.follow_offset_y = self.root.winfo_y() - self._follow_base[1]
            self._save_position()
        elif self._drag_origin is not None:
            self._toggle_smart_lock()
        self._drag_origin = None

    def _save_position(self) -> None:
        try:
            self.settings.x = self.root.winfo_x()
            self.settings.y = self.root.winfo_y()
            self.settings.save()
        except (OSError, tk.TclError):
            pass

    def _open_settings(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self._settings_window = dialog
        dialog.title("Codex Usage Overlay 设置")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", self.settings.always_on_top)
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_settings_window(dialog))

        frame = ttk.Frame(dialog, padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="当前宠物").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(frame, text=f"{self._pet_name}（自动识别）").grid(row=0, column=1, sticky="w", pady=4)

        interface_labels = {
            "smart": "智能（悬停展开）",
            "compact": "始终极简",
            "expanded": "始终展开",
        }
        reverse_interface_labels = {label: mode for mode, label in interface_labels.items()}
        interface_var = tk.StringVar(
            value=interface_labels.get(self.settings.interface_mode, interface_labels["smart"])
        )
        ttk.Label(frame, text="界面形态").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(
            frame,
            textvariable=interface_var,
            values=list(interface_labels.values()),
            state="readonly",
            width=18,
        ).grid(row=1, column=1, sticky="ew", pady=4)

        size_labels = {
            "auto": "自动（推荐）",
            "small": "小（85%）",
            "medium": "中（100%）",
            "large": "大（115%）",
            "custom": "自定义",
        }
        reverse_size_labels = {label: mode for mode, label in size_labels.items()}
        size_var = tk.StringVar(value=size_labels.get(self.settings.size_mode, size_labels["auto"]))
        ttk.Label(frame, text="浮窗尺寸").grid(row=2, column=0, sticky="w", pady=4)
        size_box = ttk.Combobox(
            frame,
            textvariable=size_var,
            values=list(size_labels.values()),
            state="readonly",
            width=18,
        )
        size_box.grid(row=2, column=1, sticky="ew", pady=4)

        custom_var = tk.IntVar(value=round(self.settings.size_adjust * 100))
        ttk.Label(frame, text="自定义比例").grid(row=3, column=0, sticky="w", pady=4)
        custom_spin = tk.Spinbox(frame, from_=70, to=150, textvariable=custom_var, width=8)
        custom_spin.grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(frame, text="%（仅自定义模式生效）").grid(row=3, column=1, sticky="e", pady=4)

        refresh_var = tk.IntVar(value=self.settings.refresh_seconds)
        ttk.Label(frame, text="刷新间隔").grid(row=4, column=0, sticky="w", pady=4)
        tk.Spinbox(frame, from_=30, to=900, increment=30, textvariable=refresh_var, width=8).grid(
            row=4, column=1, sticky="w", pady=4
        )
        ttk.Label(frame, text="秒").grid(row=4, column=1, sticky="e", pady=4)

        warning_var = tk.IntVar(value=self.settings.warning_threshold)
        ttk.Label(frame, text="红色阈值").grid(row=5, column=0, sticky="w", pady=4)
        tk.Spinbox(frame, from_=1, to=50, textvariable=warning_var, width=8).grid(
            row=5, column=1, sticky="w", pady=4
        )
        ttk.Label(frame, text="%").grid(row=5, column=1, sticky="e", pady=4)

        amber_var = tk.IntVar(value=self.settings.amber_threshold)
        ttk.Label(frame, text="黄色阈值").grid(row=6, column=0, sticky="w", pady=4)
        tk.Spinbox(frame, from_=10, to=90, textvariable=amber_var, width=8).grid(
            row=6, column=1, sticky="w", pady=4
        )
        ttk.Label(frame, text="%").grid(row=6, column=1, sticky="e", pady=4)

        collapse_var = tk.IntVar(value=self.settings.collapse_seconds)
        ttk.Label(frame, text="离开后收起").grid(row=7, column=0, sticky="w", pady=4)
        tk.Spinbox(frame, from_=1, to=30, textvariable=collapse_var, width=8).grid(
            row=7, column=1, sticky="w", pady=4
        )
        ttk.Label(frame, text="秒").grid(row=7, column=1, sticky="e", pady=4)

        topmost_var = tk.BooleanVar(value=self.settings.always_on_top)
        startup_var = tk.BooleanVar(value=is_startup_enabled())
        insight_var = tk.BooleanVar(value=self.settings.show_insights)
        history_var = tk.BooleanVar(value=self.settings.history_enabled)
        ttk.Checkbutton(frame, text="显示本地趋势建议", variable=insight_var).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )
        ttk.Checkbutton(frame, text="在本机保存额度历史", variable=history_var).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=2
        )
        ttk.Checkbutton(frame, text="保持置顶", variable=topmost_var).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=2
        )
        ttk.Checkbutton(frame, text="登录 Windows 后自动启动", variable=startup_var).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=2
        )

        button_row = ttk.Frame(frame)
        button_row.grid(row=12, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(button_row, text="取消", command=lambda: self._close_settings_window(dialog)).pack(
            side="right", padx=(8, 0)
        )

        def apply_and_close() -> None:
            size_mode = reverse_size_labels.get(size_var.get(), "auto")
            interface_mode = reverse_interface_labels.get(interface_var.get(), "smart")
            try:
                custom_adjust = max(70, min(150, int(custom_var.get()))) / 100
                refresh_seconds = max(30, min(900, int(refresh_var.get())))
                warning_threshold = max(1, min(50, int(warning_var.get())))
                amber_threshold = max(10, min(90, int(amber_var.get())))
                collapse_seconds = max(1, min(30, int(collapse_var.get())))
                if amber_threshold <= warning_threshold:
                    raise ValueError("黄色阈值必须高于红色阈值。")
                set_startup(bool(startup_var.get()))
            except (OSError, ValueError) as exc:
                messagebox.showerror("无法保存设置", str(exc), parent=dialog)
                return

            self.settings.size_mode = size_mode
            self.settings.size_adjust = custom_adjust
            self.settings.interface_mode = interface_mode
            self.settings.collapse_seconds = collapse_seconds
            self.settings.refresh_seconds = refresh_seconds
            self.settings.warning_threshold = warning_threshold
            self.settings.amber_threshold = amber_threshold
            self.settings.show_insights = bool(insight_var.get())
            self.settings.history_enabled = bool(history_var.get())
            self.settings.always_on_top = bool(topmost_var.get())
            self.settings.start_with_windows = bool(startup_var.get())
            self.settings.save()
            self._topmost_var.set(self.settings.always_on_top)
            self.root.attributes("-topmost", self.settings.always_on_top)
            self._service.set_refresh_seconds(refresh_seconds)
            self._service.set_history_enabled(self.settings.history_enabled)
            self._cancel_collapse()
            self._expanded = interface_mode == "expanded"
            self._expanded_locked = interface_mode == "expanded"
            self._apply_display_scale(self._display_dpi, force=True)
            self._close_settings_window(dialog)

        ttk.Button(button_row, text="应用", command=apply_and_close).pack(side="right")
        dialog.update_idletasks()
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.lift()
        dialog.focus_force()

    def _close_settings_window(self, dialog: tk.Toplevel) -> None:
        if dialog.winfo_exists():
            dialog.destroy()
        if self._settings_window is dialog:
            self._settings_window = None

    def _show_menu(self, event) -> None:
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _toggle_topmost(self) -> None:
        value = bool(self._topmost_var.get())
        self.settings.always_on_top = value
        self.root.attributes("-topmost", value)
        self._save_position()

    def _reset_follow_position(self) -> None:
        self.settings.follow_offset_x = 0
        self.settings.follow_offset_y = 0
        self.settings.save()

    def _refresh_clicked(self, _event) -> str:
        self._service.refresh_now()
        return "break"

    def _close_clicked(self, _event) -> str:
        self.close()
        return "break"

    @staticmethod
    def _short_error(message: str) -> str:
        clean = " ".join(message.split())
        lowered = clean.lower()
        if "authentication required" in lowered or "not logged in" in lowered:
            return "Codex CLI 未登录，请运行 codex.cmd login。"
        if len(clean) > 96:
            return clean[:93] + "…"
        return clean
