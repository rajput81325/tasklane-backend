import logging

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, origins=app.config["CORS_ORIGINS"])

    from .routes_auth import bp as auth_bp
    from .routes_tasks import bp as tasks_bp

    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(tasks_bp, url_prefix="/api")

    @app.get("/")
    def root():
        return jsonify(name="Tasklane API", status="ok")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        return jsonify(error=e.description), e.code

    @app.errorhandler(Exception)
    def unhandled(e: Exception):
        app.logger.exception("Unhandled error")
        return jsonify(error="Something went wrong on our side. Please try again."), 500

    return app
