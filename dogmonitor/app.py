import os
import sys
import time
from pathlib import Path

from dogmonitor.api import AppServices, create_app
from dogmonitor.camera import CameraService, create_camera
from dogmonitor.config import load_config
from dogmonitor.display import DisplayService, create_display
from dogmonitor.logger import register_shutdown_logger, setup_logging
from dogmonitor.sensor import SensorService, create_sensor


def _configure_pi_environment(dev_mode: bool) -> None:
    if dev_mode:
        return

    os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

    for lib in (
        Path.home() / "e-Paper" / "RaspberryPi_JetsonNano" / "python" / "lib",
        Path.home() / "LAFVIN-2.13inch-ePaper-HAT" / "RaspberryPi" / "python" / "lib",
    ):
        if lib.is_dir():
            path = str(lib)
            if path not in sys.path:
                sys.path.insert(0, path)


def main() -> None:
    config = load_config()
    _configure_pi_environment(config.dev_mode)
    logger = setup_logging(config)
    register_shutdown_logger(logger)

    logger.info(
        "Dog Monitor starting (dev_mode=%s, mock_sensor=%s, port=%s)",
        config.dev_mode,
        config.mock_sensor,
        config.server_port,
    )

    start_time = time.monotonic()
    sensor_service = SensorService(
        create_sensor(config.dev_mode, config.mock_sensor),
        config.sensor_poll_interval_seconds,
        logger,
    )
    camera_service = CameraService(
        create_camera(config.dev_mode),
        config.camera_resolution,
        logger,
    )
    display_service = DisplayService(
        create_display(config.dev_mode),
        sensor_service,
        config.display_refresh_interval_seconds,
        logger,
    )

    sensor_service.start()
    display_service.start()

    services = AppServices(
        sensor=sensor_service,
        camera=camera_service,
        display=display_service,
        start_time=start_time,
    )
    app = create_app(config, logger, services)

    try:
        app.run(host="0.0.0.0", port=config.server_port, use_reloader=False)
    finally:
        display_service.stop()
        sensor_service.stop()


if __name__ == "__main__":
    main()
