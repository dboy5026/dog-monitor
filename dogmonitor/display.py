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
        return f"{hour}:{dt.strftime('%M %p')}"
    except ValueError:
        return updated_at[:19]


def _format_temp_number(temp_f: Any) -> str:
    if temp_f == "--":
        return "--"
    try:
        return str(int(round(float(temp_f))))
    except (TypeError, ValueError):
        return "--"


def get_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "N/A"


def _build_landscape_image(epd, temp_f: Any, humidity: Any, ip_address: str, updated_at: str):
    from PIL import Image, ImageDraw

    width, height = epd.height, epd.width
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    temp_num = _format_temp_number(temp_f)
    num_font = _load_font(58, bold=True)
    degree_font = _load_font(34, bold=True)
    label_font = _load_font(10, bold=False)
    value_font = _load_font(13, bold=False)

    num_bbox = draw.textbbox((0, 0), temp_num, font=num_font)
    degree_bbox = draw.textbbox((0, 0), "°", font=degree_font)
    num_w = num_bbox[2] - num_bbox[0]
    num_h = num_bbox[3] - num_bbox[1]
    degree_w = degree_bbox[2] - degree_bbox[0]
    temp_w = num_w + degree_w + 2
    temp_x = (width // 2 - temp_w) // 2
    temp_y = (height - num_h) // 2

    draw.text((temp_x, temp_y), temp_num, font=num_font, fill=0)
    draw.text((temp_x + num_w + 2, temp_y - 4), "°", font=degree_font, fill=0)

    divider_x = width // 2
    draw.line([(divider_x, 10), (divider_x, height - 10)], fill=0, width=1)

    info_x = divider_x + 10
    humidity_value = f"{humidity}%" if humidity != "--" else "--"
    rows = (
        ("Humidity", humidity_value),
        ("IP Address", ip_address),
        ("Updated", _format_updated(updated_at)),
    )

    y = 16
    for label, value in rows:
        draw.text((info_x, y), label, font=label_font, fill=0)
        draw.text((info_x, y + 13), value, font=value_font, fill=0)
        y += 34

    return image


class BaseDisplay(ABC):
    @abstractmethod
    def render(
        self,
        temp_f: Any,
        humidity: Any,
        ip_address: str,
        updated_at: str,
    ) -> None:
        """Draw the current monitoring state on the display."""


class MockDisplay(BaseDisplay):
    def render(
        self,
        temp_f: Any,
        humidity: Any,
        ip_address: str,
        updated_at: str,
    ) -> None:
        print(
            f"[DISPLAY] {temp_f}°  {humidity}%  {ip_address}  Updated:{updated_at}",
            flush=True,
        )


class EInkDisplay(BaseDisplay):
    def render(
        self,
        temp_f: Any,
        humidity: Any,
        ip_address: str,
        updated_at: str,
    ) -> None:
        from waveshare_epd import epd2in13_V4

        epd = epd2in13_V4.EPD()
        epd.init()

        image = _build_landscape_image(epd, temp_f, humidity, ip_address, updated_at)
        epd.display(epd.getbuffer(image))
        epd.sleep()


def create_display(dev_mode: bool) -> BaseDisplay:
    if dev_mode:
        return MockDisplay()
    return EInkDisplay()


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
                ip_address = get_ip_address()

                self._display.render(
                    temp_f,
                    humidity,
                    ip_address,
                    updated_at,
                )
                self._last_success = time.monotonic()
                self._consecutive_failures = 0
                self._logger.info(
                    "Display updated: %s°, %s%%, %s",
                    temp_f,
                    humidity,
                    ip_address,
                )
            except Exception:
                self._consecutive_failures += 1
                self._logger.exception("Display update failed")

            time.sleep(self._refresh_interval)
