import logging

from flask import Blueprint, make_response, render_template


def create_dashboard_blueprint(logger: logging.Logger) -> Blueprint:
    dashboard = Blueprint("dashboard", __name__)

    @dashboard.get("/")
    def index():
        logger.info("Dashboard requested")
        response = make_response(render_template("dashboard.html"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    return dashboard
