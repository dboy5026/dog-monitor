import logging

from flask import Blueprint, render_template


def create_dashboard_blueprint(logger: logging.Logger) -> Blueprint:
    dashboard = Blueprint("dashboard", __name__)

    @dashboard.get("/")
    def index():
        logger.info("Dashboard requested")
        return render_template("dashboard.html")

    return dashboard
