import logging
import socket
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from dogmonitor.sensor import SensorService

_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", True),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", False),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", True),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", False),
)


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont

    preferred = [path for path, is_bold in _FONT_CANDIDATES if is_bold == bold]
    fallback = [path for path, _ in _FONT_CANDIDATES]
    for path in preferred + fallback:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _format_updated(updated_at: str) -> str:
    if updated_at == "--":
        return "No reading yet"
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        hour = dt.strftime("%I").lstrip("0") or "12"
        return f"Updated {hour}:{dt.strftime('%M %p')}"
    except ValueError:
        return updated_at[:19]


def _format_temp_parts(temp_f: Any) -> tuple[str, str]:
    if temp_f == "--":
        return "--", "F"
    try:
        return str(int(round(float(temp_f)))), "°F"
    except (TypeError, ValueError):
        return "--", "F"


def _build_landscape_image(epd, temp_f: Any, humidity: Any, wifi_ok: bool, updated_at: str):
    from PIL import Image, ImageDraw

    width, height = epd.height, epd.width
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    temp_num, temp_unit = _format_temp_parts(temp_f)
    num_font = _load_font(58, bold=True)
    unit_font = _load_font(22, bold=True)
    small_font = _load_font(14, bold=False)
    tiny_font = _load_font(11, bold=False)

    num_bbox = draw.textbbox((0, 0), temp_num, font=num_font)
    unit_bbox = draw.textbbox((0, 0), temp_unit, font=unit_font)
    num_h = num_bbox[3] - num_bbox[1]
    unit_h = unit_bbox[3] - unit_bbox[1]
    block_h = num_h + unit_h + 2
    block_y = (height - block_h) // 2
    left_center_x = width // 4

    num_w = num_bbox[2] - num_bbox[0]
    draw.text((left_center_x - num_w // 2, block_y), temp_num, font=num_font, fill=0)

    unit_w = unit_bbox[2] - unit_bbox[0]
    draw.text(
        (left_center_x - unit_w // 2, block_y + num_h + 2),
        temp_unit,
        font=unit_font,
        fill=0,
    )

    divider_x = width // 2
    draw.line([(divider_x, 10), (divider_x, height - 10)], fill=0, width=1)

    info_x = divider_x + 10
    humidity_text = f"{humidity}% humidity" if humidity != "--" else "--% humidity"
    wifi_text = f"WiFi {'OK' if wifi_ok else 'DOWN'}"
    updated_text = _format_updated(updated_at)

    draw.text((info_x, 22), humidity_text, font=small_font, fill=0)
    draw.text((info_x, 48), wifi_text, font=small_font, fill=0)
    draw.text((info_x, 74), updated_text, font=tiny_font, fill=0)

    return image


class BaseDisplay(ABC):
    @abstractmethod
    def render(
        self,
        temp_f: Any,
        humidity: Any,
        wifi_ok: bool,
        updated_at: str,
    ) -> None:
        """Draw the current monitoring state on the display."""


class MockDisplay(BaseDisplay):
    def render(
        self,
        temp_f: Any,
        humidity: Any,
        wifi_ok: bool,
        updated_at: str,
    ) -> None:
        wifi_label = "OK" if wifi_ok else "DOWN"
        print(
            f"[DISPLAY] {temp_f}°F  {humidity}%  WiFi:{wifi_label}  Updated:{updated_at}",
            flush=True,
        )


class EInkDisplay(BaseDisplay):
    def render(
        self,
        temp_f: Any,
        humidity: Any,
        wifi_ok: bool,
        updated_at: str,
    ) -> None:
        from waveshare_epd import epd2in13_V4

        epd = epd2in13_V4.EPD()
        epd.init()

        image = _build_landscape_image(epd, temp_f, humidity, wifi_ok, updated_at)
        epd.display(epd.getbuffer(image))
        epd.sleep()


def create_display(dev_mode: bool) -> BaseDisplay:
    if dev_mode:
        return MockDisplay()
    return EInkDisplay()


def check_wifi_status() -> bool:
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=2):
            return True
    except OSError:
        return False


class DisplayService:
    def __init__(
        self,
        display: BaseDisplay,
        sensor: SensorService,
        refresh_interval_seconds: int,
        logger: logging.Logger,
    ) -> None:
        self._display = display
        self._sensor = sensor
        self._refresh_interval = refresh_interval_seconds
        self._logger = logger.getChild("display")
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_success: float | None = None
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._logger.info(
            "Display service started (interval=%ss)",
            self._refresh_interval,
        )
        self._thread = threading.Thread(target=self._refresh_loop, name="display", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._refresh_interval + 1)
        self._logger.info("Display service stopped")

    def is_healthy(self) -> bool:
        if self._last_success is None:
            return False
        return (time.monotonic() - self._last_success) < (self._refresh_interval * 3)

    def _refresh_loop(self) -> None:
        while self._running:
            try:
                reading = self._sensor.get_reading()
                temp_f = reading.temperature_f if reading else "--"
                humidity = reading.humidity if reading else "--"
                updated_at = reading.last_sensor_update if reading else "--"

                wifi_ok = check_wifi_status()
                self._display.render(
                    temp_f,
                    humidity,
                    wifi_ok,
                    updated_at,
                )
                self._last_success = time.monotonic()
                self._consecutive_failures = 0
                self._logger.info(
                    "Display updated: %s°F, %s%%, WiFi %s",
                    temp_f,
                    humidity,
                    "OK" if wifi_ok else "DOWN",
                )
            except Exception:
                self._consecutive_failures += 1
                self._logger.exception("Display update failed")

            time.sleep(self._refresh_interval)
