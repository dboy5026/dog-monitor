import logging
import shutil
import subprocess
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

_CAPTURE_TIMEOUT_SECONDS = 25
_LOCK_TIMEOUT_SECONDS = 5


class CameraBusyError(RuntimeError):
    pass


class BaseCamera(ABC):
    @abstractmethod
    def capture_jpeg(self, path: Path, resolution: tuple[int, int]) -> None:
        """Write a JPEG still image to path."""

    def close(self) -> None:
        """Release hardware resources."""


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
        width, height = resolution
        for binary in ("rpicam-still", "libcamera-still"):
            if shutil.which(binary):
                self._capture_with_cli(binary, path, width, height)
                return
        self._capture_with_picamera2(path, resolution)

    def _capture_with_cli(self, binary: str, path: Path, width: int, height: int) -> None:
        result = subprocess.run(
            [
                binary,
                "-o",
                str(path),
                "-t",
                "2000",
                "-n",
                "--width",
                str(width),
                "--height",
                str(height),
            ],
            capture_output=True,
            timeout=_CAPTURE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(stderr or f"{binary} failed with code {result.returncode}")
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"{binary} produced an empty image")

    def _capture_with_picamera2(self, path: Path, resolution: tuple[int, int]) -> None:
        from picamera2 import Picamera2

        picam = Picamera2()
        try:
            config = picam.create_still_configuration(main={"size": resolution})
            picam.configure(config)
            picam.start()
            time.sleep(0.8)
            picam.capture_file(str(path))
        finally:
            try:
                picam.stop()
            except Exception:
                pass
            try:
                picam.close()
            except Exception:
                pass

    def close(self) -> None:
        return


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
        self._lock = threading.Lock()

    def capture(self) -> Path:
        if not self._lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
            raise CameraBusyError("Camera busy")

        path = self._temp_dir / f"snapshot_{int(time.time() * 1000)}.jpg"
        try:
            self._camera.capture_jpeg(path, self._resolution)
            self._last_success = time.monotonic()
            self._consecutive_failures = 0
            self._logger.info("Camera capture saved to %s", path.name)
            return path
        except subprocess.TimeoutExpired:
            self._consecutive_failures += 1
            self._logger.error("Camera capture timed out after %ss", _CAPTURE_TIMEOUT_SECONDS)
            if path.exists():
                path.unlink(missing_ok=True)
            raise TimeoutError("Camera capture timed out") from None
        except Exception:
            self._consecutive_failures += 1
            self._logger.exception("Camera capture failed")
            self._camera.close()
            if path.exists():
                path.unlink(missing_ok=True)
            raise
        finally:
            self._lock.release()

    def close(self) -> None:
        if self._lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
            try:
                self._camera.close()
            finally:
                self._lock.release()

    def is_healthy(self) -> bool:
        if self._consecutive_failures == 0:
            return True
        if self._last_success is None:
            return False
        return (time.monotonic() - self._last_success) < 3600
