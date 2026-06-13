import logging
import socket
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from dogmonitor.sensor import SensorService


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
        from PIL import Image, ImageDraw, ImageFont
        from waveshare_epd import epd2in13_V2

        epd = epd2in13_V2.EPD()
        epd.init()

        image = Image.new("1", (epd.width, epd.height), 255)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        wifi_label = "OK" if wifi_ok else "DOWN"
        updated_label = updated_at if updated_at != "--" else "N/A"
        if len(updated_label) > 19:
            updated_label = updated_label[:19]

        lines = [
            "Dog Monitor",
            f"Temp: {temp_f} F",
            f"Humidity: {humidity}%",
            f"WiFi: {wifi_label}",
            f"Updated:",
            updated_label,
        ]

        y = 4
        for line in lines:
            draw.text((4, y), line, font=font, fill=0)
            y += 18

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
