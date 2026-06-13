import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone


def celsius_to_fahrenheit(celsius: float) -> float:
    return round(celsius * 9 / 5 + 32, 1)


@dataclass
class SensorReading:
    temperature_c: float
    temperature_f: float
    humidity: int
    last_sensor_update: str


class BaseSensor(ABC):
    @abstractmethod
    def read(self) -> tuple[float, float] | None:
        """Return (celsius, humidity_percent) or None on failure."""


class MockSensor(BaseSensor):
    def read(self) -> tuple[float, float] | None:
        celsius = round(20.0 + random.uniform(-2, 2), 1)
        humidity = round(50.0 + random.uniform(-5, 5), 1)
        return celsius, humidity


class SHT31Sensor(BaseSensor):
    _ADDRESS = 0x44
    _MEASURE_CMD = [0x2C, 0x06]

    def __init__(self, bus: int = 1) -> None:
        from smbus2 import SMBus

        self._bus = SMBus(bus)

    def read(self) -> tuple[float, float] | None:
        self._bus.write_i2c_block_data(self._ADDRESS, self._MEASURE_CMD[0], self._MEASURE_CMD[1:])
        time.sleep(0.015)
        data = self._bus.read_i2c_block_data(self._ADDRESS, 0x00, 6)

        raw_temp = (data[0] << 8) | data[1]
        raw_humidity = (data[3] << 8) | data[4]

        celsius = -45 + 175 * (raw_temp / 65535)
        humidity = 100 * (raw_humidity / 65535)
        return round(celsius, 1), round(humidity, 1)

    def close(self) -> None:
        self._bus.close()


def create_sensor(dev_mode: bool) -> BaseSensor:
    if dev_mode:
        return MockSensor()
    return SHT31Sensor()


class SensorService:
    def __init__(
        self,
        sensor: BaseSensor,
        poll_interval_seconds: int,
        logger: logging.Logger,
    ) -> None:
        self._sensor = sensor
        self._poll_interval = poll_interval_seconds
        self._logger = logger.getChild("sensor")
        self._lock = threading.Lock()
        self._reading: SensorReading | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_success: float | None = None
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._logger.info("Sensor service started (interval=%ss)", self._poll_interval)
        self._thread = threading.Thread(target=self._poll_loop, name="sensor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval + 1)
        if hasattr(self._sensor, "close"):
            self._sensor.close()
        self._logger.info("Sensor service stopped")

    def get_reading(self) -> SensorReading | None:
        with self._lock:
            if self._reading is None:
                return None
            return SensorReading(
                temperature_c=self._reading.temperature_c,
                temperature_f=self._reading.temperature_f,
                humidity=self._reading.humidity,
                last_sensor_update=self._reading.last_sensor_update,
            )

    def is_healthy(self) -> bool:
        if self._last_success is None:
            return False
        return (time.monotonic() - self._last_success) < (self._poll_interval * 3)

    def _poll_loop(self) -> None:
        while self._running:
            try:
                result = self._sensor.read()
                if result is None:
                    self._consecutive_failures += 1
                    self._logger.warning("Sensor read returned no data")
                else:
                    celsius, humidity = result
                    reading = SensorReading(
                        temperature_c=celsius,
                        temperature_f=celsius_to_fahrenheit(celsius),
                        humidity=round(humidity),
                        last_sensor_update=datetime.now(timezone.utc)
                        .replace(microsecond=0)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    )
                    with self._lock:
                        self._reading = reading
                    self._last_success = time.monotonic()
                    self._consecutive_failures = 0
                    self._logger.info(
                        "Sensor read: %.1f°C (%.1f°F), %d%% humidity",
                        celsius,
                        reading.temperature_f,
                        reading.humidity,
                    )
            except Exception:
                self._consecutive_failures += 1
                self._logger.exception("Sensor read failed; keeping last cached values")

            time.sleep(self._poll_interval)
