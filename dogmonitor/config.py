import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG_PATH = _PACKAGE_DIR / "config.json"

_DEFAULTS: dict[str, Any] = {
    "dev_mode": True,
    "server_port": 5000,
    "sensor_poll_interval_seconds": 5,
    "display_refresh_interval_seconds": 30,
    "camera_resolution": [1920, 1080],
    "log_dir": "logs",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 5,
}


@dataclass(frozen=True)
class Config:
    dev_mode: bool
    server_port: int
    sensor_poll_interval_seconds: int
    display_refresh_interval_seconds: int
    camera_resolution: tuple[int, int]
    log_dir: Path
    log_max_bytes: int
    log_backup_count: int


def _resolve_log_dir(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return _PACKAGE_DIR.parent / path


def load_config(path: Path | str | None = None) -> Config:
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    data = dict(_DEFAULTS)

    if config_path.is_file():
        with config_path.open(encoding="utf-8") as f:
            data.update(json.load(f))

    resolution = data["camera_resolution"]
    if not isinstance(resolution, list) or len(resolution) != 2:
        raise ValueError("camera_resolution must be a list of two integers")

    return Config(
        dev_mode=bool(data["dev_mode"]),
        server_port=int(data["server_port"]),
        sensor_poll_interval_seconds=int(data["sensor_poll_interval_seconds"]),
        display_refresh_interval_seconds=int(data["display_refresh_interval_seconds"]),
        camera_resolution=(int(resolution[0]), int(resolution[1])),
        log_dir=_resolve_log_dir(str(data["log_dir"])),
        log_max_bytes=int(data["log_max_bytes"]),
        log_backup_count=int(data["log_backup_count"]),
    )
