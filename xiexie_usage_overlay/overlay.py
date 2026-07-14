from __future__ import annotations

import logging
import queue
import tkinter as tk
from typing import Protocol

from .pet_window import PetPresenceDebouncer, PetWindowLocator, WindowInfo, calculate_follow_position
from .service import ServiceEvent
from .settings import Settings
from .usage import UsageSnapshot


class OverlayService(Protocol):
    def start(self) -> None: ...

    def refresh_now(self) -> None: ...

    def stop(self) -> None: ...


class UsageOverlay:
    WIDTH = 220
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
        self.root = tk.Tk()
        self.root.title("xiexie Codex 余量")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", settings.always_on_top)
        self.root.configure(bg=self.TRANSPARENT)
        is_windows = self.root.tk.call("tk", "windowingsystem") == "win32"
        if is_windows:
            self.root.wm_attributes("-transparentcolor", self.TRANSPARENT)
        self._scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0) if is_windows else 1.0
        self._pixel_width = round(self.WIDTH * self._scale)

        self.canvas = tk.Canvas(
            self.root,
            width=self._pixel_width,
            height=round(108 * self._scale),
            bg=self.TRANSPARENT,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._events: queue.Queue[ServiceEvent] = queue.Queue()
        self._service: OverlayService = service_factory(self._events.put)
        self._snapshot: UsageSnapshot | None = None
        self._status = "loading"
        self._error = ""
        self._height = 108
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._closing = False
        self._pet_locator = PetWindowLocator() if PetWindowLocator.supported else None
        self._pet_presence = PetPresenceDebouncer(self.PET_MISS_THRESHOLD)
        self._pet_window: WindowInfo | None = None
        self._pet_shown = self._pet_locator is None
        self._follow_base: tuple[int, int] | None = None

        self._menu = tk.Menu(self.root, tearoff=False, font=("Microsoft YaHei UI", 9))
        self._menu.add_command(label="立即刷新", command=self._service.refresh_now)
        self._topmost_var = tk.BooleanVar(value=settings.always_on_top)
        self._menu.add_checkbutton(label="保持置顶", variable=self._topmost_var, command=self._toggle_topmost)
        if self._pet_locator is not None:
            self._menu.add_command(label="重置跟随位置", command=self._reset_follow_position)
        self._menu.add_separator()
        self._menu.add_command(label="退出 xiexie 余量", command=self.close)

        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)
        self.canvas.bind("<Double-Button-1>", lambda _event: self._service.refresh_now())
        self.canvas.bind("<Button-3>", self._show_menu)
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

    def _place_initially(self) -> None:
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        pixel_height = round(self._height * self._scale)
        x = self.settings.x if self.settings.x is not None else screen_width - self._pixel_width - round(36 * self._scale)
        y = (
            self.settings.y
            if self.settings.y is not None
            else screen_height - pixel_height - round(260 * self._scale)
        )
        x = max(0, min(x, screen_width - self._pixel_width))
        y = max(0, min(y, screen_height - pixel_height))
        self.root.geometry(f"{self._pixel_width}x{pixel_height}+{x}+{y}")

    def _set_height(self, height: int) -> None:
        if height == self._height:
            return
        self.root.update_idletasks()
        x = self.root.winfo_x()
        old_pixel_height = round(self._height * self._scale)
        new_pixel_height = round(height * self._scale)
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

        pet = self._pet_locator.find()
        pet_present = self._pet_presence.observe(pet is not None)
        if pet is None and not pet_present:
            self._pet_window = None
            self._follow_base = None
            self._drag_origin = None
            if self._pet_shown:
                logging.getLogger(__name__).info("Codex pet hidden; hiding usage overlay")
                self.root.withdraw()
                self._pet_shown = False
        elif pet is not None:
            self._pet_window = pet
            work_area = self._pet_locator.work_area(pet.handle)
            overlay_height = round(self._height * self._scale)
            tail_offset = round((self.WIDTH - 91) * self._scale)
            target, base = calculate_follow_position(
                pet.rect,
                self._pixel_width,
                overlay_height,
                tail_offset,
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
                logging.getLogger(__name__).info("Codex pet visible; showing usage overlay")
                self.root.deiconify()
                self.root.attributes("-topmost", self.settings.always_on_top)
                self.root.lift()
                self._pet_shown = True

        self.root.after(150, self._sync_to_pet)

    def _redraw(self) -> None:
        if self._status == "snapshot" and self._snapshot is not None:
            self._draw_snapshot(self._snapshot)
        elif self._status == "error":
            self._draw_error(self._error)
        else:
            self._draw_loading(self._error or "正在读取 Codex 余量…")

    def _draw_chrome(self, height: int, status_color: str) -> int:
        self._set_height(height)
        self.canvas.delete("all")
        body_bottom = height - 16
        self._rounded_rectangle(4, 4, self.WIDTH - 4, body_bottom, 18, fill=self.BODY, outline=self.BODY_BORDER)
        self.canvas.create_polygon(
            self.WIDTH - 116,
            body_bottom - 2,
            self.WIDTH - 72,
            body_bottom - 2,
            self.WIDTH - 91,
            height - 3,
            fill=self.BODY,
            outline=self.BODY_BORDER,
        )
        self.canvas.create_line(self.WIDTH - 115, body_bottom - 1, self.WIDTH - 73, body_bottom - 1, fill=self.BODY)

        self.canvas.create_oval(13, 17, 20, 24, fill=status_color, outline="")
        self.canvas.create_text(
            27,
            20.5,
            anchor="w",
            text="xiexie 余量",
            fill=self.INK,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.canvas.create_text(
            self.WIDTH - 35,
            20.5,
            text="↻",
            fill=self.BLUE,
            font=("Segoe UI Symbol", 10, "bold"),
            tags=("refresh",),
        )
        self.canvas.create_text(
            self.WIDTH - 16,
            20.5,
            text="×",
            fill=self.MUTED,
            font=("Segoe UI", 11),
            tags=("close",),
        )
        return body_bottom

    def _draw_loading(self, message: str) -> None:
        self._draw_chrome(91, self.AMBER)
        self.canvas.create_text(
            14,
            49,
            anchor="w",
            text=message,
            fill=self.INK,
            font=("Microsoft YaHei UI", 7),
        )
        self.canvas.create_text(
            14,
            67,
            anchor="w",
            text="我在核对。",
            fill=self.MUTED,
            font=("Microsoft YaHei UI", 6),
        )
        self._finish_drawing()

    def _draw_error(self, message: str) -> None:
        self._draw_chrome(118, self.CORAL)
        self.canvas.create_text(
            14,
            45,
            anchor="w",
            text="暂时读不到余量。",
            fill=self.INK,
            font=("Microsoft YaHei UI", 7, "bold"),
        )
        short = self._short_error(message)
        self.canvas.create_text(
            14,
            62,
            anchor="nw",
            width=(self.WIDTH - 28) * self._scale,
            text=short,
            fill=self.MUTED,
            font=("Microsoft YaHei UI", 6),
        )
        self.canvas.create_text(
            14,
            94,
            anchor="w",
            text="会自动重试，也可双击刷新。",
            fill=self.CORAL,
            font=("Microsoft YaHei UI", 6, "bold"),
        )
        self._finish_drawing()

    def _draw_snapshot(self, snapshot: UsageSnapshot) -> None:
        rows = snapshot.display_rows(limit=2)
        credits = snapshot.credits
        show_credits = bool(credits and credits.should_show)
        height = 78 + max(1, len(rows)) * 38 + (15 if show_credits else 0)
        minimum = snapshot.minimum_remaining
        status_color = self.GREEN if minimum is None or minimum > 20 else self.AMBER if minimum > 10 else self.CORAL
        self._draw_chrome(height, status_color)

        pill_text = snapshot.plan_type[:12]
        pill_width = max(48, 14 + len(pill_text) * 8)
        pill_x2 = self.WIDTH - 54
        pill_x1 = pill_x2 - pill_width
        self._rounded_rectangle(pill_x1, 14, pill_x2, 28, 7, fill=self.BLUE_SOFT, outline="")
        self.canvas.create_text(
            (pill_x1 + pill_x2) / 2,
            21,
            text=pill_text,
            fill=self.BLUE,
            font=("Segoe UI", 6, "bold"),
        )

        y = 42
        if rows:
            for row in rows:
                self._draw_limit_row(y, row.label, row.window.remaining_percent, row.window.reset_text())
                y += 38
        else:
            self.canvas.create_text(
                14,
                y + 14,
                anchor="w",
                text="Codex 暂未提供可显示的限额窗口。",
                fill=self.MUTED,
                font=("Microsoft YaHei UI", 6),
            )
            y += 38

        if minimum is None:
            personality = "暂无百分比，我继续盯着。"
        elif minimum <= 10:
            personality = f"只剩 {minimum}%，快到顶了。"
        elif minimum <= self.settings.warning_threshold:
            personality = f"只剩 {minimum}%，省着点。"
        else:
            personality = "额度正常，我盯着。"
        self.canvas.create_text(
            14,
            y + 1,
            anchor="w",
            text=personality,
            fill=status_color,
            font=("Microsoft YaHei UI", 7, "bold"),
        )
        y += 18

        if show_credits and credits:
            self.canvas.create_text(
                14,
                y + 1,
                anchor="w",
                text=credits.display_text(),
                fill=self.MUTED,
                font=("Microsoft YaHei UI", 6),
            )
            y += 15
        self._finish_drawing()

    def _draw_limit_row(self, y: int, label: str, remaining: int, reset_text: str) -> None:
        self.canvas.create_text(
            14,
            y,
            anchor="w",
            text=label,
            fill=self.INK,
            font=("Microsoft YaHei UI", 7, "bold"),
        )
        self.canvas.create_text(
            self.WIDTH - 14,
            y,
            anchor="e",
            text=f"剩余 {remaining}%",
            fill=self.INK,
            font=("Microsoft YaHei UI", 7, "bold"),
        )

        x1, x2 = 14, self.WIDTH - 14
        bar_y1, bar_y2 = y + 12, y + 17
        self._rounded_rectangle(x1, bar_y1, x2, bar_y2, 4, fill=self.BAR_BG, outline="")
        fill_width = (x2 - x1) * remaining / 100
        color = self.GREEN if remaining > 50 else self.AMBER if remaining > 20 else self.CORAL
        if fill_width > 1:
            self._rounded_rectangle(x1, bar_y1, x1 + fill_width, bar_y2, 4, fill=color, outline="")
        self.canvas.create_text(
            14,
            y + 27,
            anchor="w",
            text=reset_text,
            fill=self.MUTED,
            font=("Microsoft YaHei UI", 6),
        )

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
        if self._scale != 1.0:
            self.canvas.scale("all", 0, 0, self._scale, self._scale)

    def _start_drag(self, event) -> None:
        current = self.canvas.gettags("current")
        if "refresh" in current or "close" in current:
            self._drag_origin = None
            return
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag(self, event) -> None:
        if self._drag_origin is None:
            return
        mouse_x, mouse_y, window_x, window_y = self._drag_origin
        x = window_x + event.x_root - mouse_x
        y = window_y + event.y_root - mouse_y
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event) -> None:
        if self._drag_origin is not None:
            if self._pet_window is not None and self._follow_base is not None:
                self.settings.follow_offset_x = self.root.winfo_x() - self._follow_base[0]
                self.settings.follow_offset_y = self.root.winfo_y() - self._follow_base[1]
            self._save_position()
        self._drag_origin = None

    def _save_position(self) -> None:
        try:
            self.settings.x = self.root.winfo_x()
            self.settings.y = self.root.winfo_y()
            self.settings.save()
        except (OSError, tk.TclError):
            pass

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
        if len(clean) > 96:
            return clean[:93] + "…"
        return clean
