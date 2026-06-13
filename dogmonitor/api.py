import io
import logging
import os
import time
from dataclasses import dataclass

from flask import Blueprint, Flask, jsonify, request, send_file

from dogmonitor.camera import CameraService
from dogmonitor.config import Config
from dogmonitor.dashboard import create_dashboard_blueprint
from dogmonitor.display import DisplayService
from dogmonitor.sensor import SensorService


@dataclass
class AppServices:
    sensor: SensorService
    camera: CameraService
    display: DisplayService
    start_time: float


def create_api_blueprint(services: AppServices, logger: logging.Logger) -> Blueprint:
    api = Blueprint("api", __name__)

    @api.before_request
    def log_request() -> None:
        logger.info("API %s %s", request.method, request.path)

    @api.get("/status")
    def status():
        reading = services.sensor.get_reading()
        if reading is None:
            return jsonify(
                {
                    "online": True,
                    "temperature_f": None,
                    "temperature_c": None,
                    "humidity": None,
                    "last_sensor_update": None,
                }
            )

        return jsonify(
            {
                "online": True,
                "temperature_f": reading.temperature_f,
                "temperature_c": reading.temperature_c,
                "humidity": reading.humidity,
                "last_sensor_update": reading.last_sensor_update,
            }
        )

    @api.get("/snapshot")
    def snapshot():
        try:
            path = services.camera.capture()
        except Exception:
            logger.exception("Snapshot request failed")
            return jsonify({"error": "Camera capture failed"}), 503

        try:
            data = path.read_bytes()
        finally:
            try:
                os.remove(path)
            except OSError:
                logger.warning("Failed to remove temporary snapshot %s", path.name)

        return send_file(io.BytesIO(data), mimetype="image/jpeg")

    @api.get("/health")
    def health():
        sensor_ok = services.sensor.is_healthy()
        camera_ok = services.camera.is_healthy()
        display_ok = services.display.is_healthy()
        all_ok = sensor_ok and camera_ok and display_ok

        return jsonify(
            {
                "status": "healthy" if all_ok else "degraded",
                "camera": camera_ok,
                "sensor": sensor_ok,
                "display": display_ok,
                "uptime_seconds": int(time.monotonic() - services.start_time),
            }
        )

    return api


def create_app(
    config: Config,
    logger: logging.Logger,
    services: AppServices,
) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.register_blueprint(create_api_blueprint(services, logger.getChild("api")))
    app.register_blueprint(create_dashboard_blueprint(logger.getChild("dashboard")))
    return app
