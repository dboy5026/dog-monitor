import logging
import tempfile
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw


class BaseCamera(ABC):
    @abstractmethod
    def capture_jpeg(self, path: Path, resolution: tuple[int, int]) -> None:
        """Write a JPEG still image to path."""


class MockCamera(BaseCamera):
    def capture_jpeg(self, path: Path, resolution: tuple[int, int]) -> None:
        img = Image.new("RGB", resolution, color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text(
            (20, 20),
            f"Mock snapshot\n{timestamp}",
            fill=(220, 220, 220),
        )
        img.save(path, "JPEG", quality=85)


class PiCamera(BaseCamera):
    def capture_jpeg(self, path: Path, resolution: tuple[int, int]) -> None:
        from picamera2 import Picamera2

        picam = Picamera2()
        try:
            config = picam.create_still_configuration(main={"size": resolution})
            picam.configure(config)
            picam.start()
            picam.capture_file(str(path))
        finally:
            picam.stop()
            picam.close()


def create_camera(dev_mode: bool) -> BaseCamera:
    if dev_mode:
        return MockCamera()
    return PiCamera()


class CameraService:
    def __init__(
        self,
        camera: BaseCamera,
        resolution: tuple[int, int],
        logger: logging.Logger,
    ) -> None:
        self._camera = camera
        self._resolution = resolution
        self._logger = logger.getChild("camera")
        self._temp_dir = Path(tempfile.gettempdir()) / "dogmonitor"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._last_success: float | None = None
        self._consecutive_failures = 0

    def capture(self) -> Path:
        path = self._temp_dir / f"snapshot_{int(time.time() * 1000)}.jpg"
        try:
            self._camera.capture_jpeg(path, self._resolution)
            self._last_success = time.monotonic()
            self._consecutive_failures = 0
            self._logger.info("Camera capture saved to %s", path.name)
            return path
        except Exception:
            self._consecutive_failures += 1
            self._logger.exception("Camera capture failed")
            if path.exists():
                path.unlink(missing_ok=True)
            raise

    def is_healthy(self) -> bool:
        if self._consecutive_failures == 0:
            return True
        if self._last_success is None:
            return False
        return (time.monotonic() - self._last_success) < 3600
