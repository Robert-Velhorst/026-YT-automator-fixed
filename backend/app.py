import logging
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, abort, request, send_from_directory
from flask_compress import Compress
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config, validate_runtime_config
from errors import register_error_handlers
from extensions import db, migrate


@event.listens_for(Engine, "connect")
def configure_sqlite(connection, _record):
    if connection.__class__.__module__.split(".")[0] != "sqlite3":
        return
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_app(config_object=Config):
    load_dotenv(Path(__file__).with_name(".env"))
    frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    app = Flask(__name__, static_folder=str(frontend_dist), static_url_path="")
    app.config.from_object(Config)
    if config_object is not Config:
        app.config.from_object(config_object)
    validate_runtime_config(app.config)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["GENERATED_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    Compress(app)
    CORS(app, origins=app.config["CORS_ORIGINS"], supports_credentials=True)

    from routes.auth import auth_bp
    from routes.core import api_bp
    from routes.playlists import playlists_bp
    from routes.operator import enforce_operator_access, operator_bp
    from routes.hai import hai_bp, hai_public_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(playlists_bp, url_prefix="/api/playlists")
    app.register_blueprint(operator_bp, url_prefix="/api/operator")
    app.register_blueprint(hai_bp, url_prefix="/api/integrations/hai")
    app.register_blueprint(hai_public_bp)
    register_error_handlers(app)

    @app.before_request
    def request_context():
        request.request_id = request.headers.get("X-Request-ID", str(uuid4()))

    app.before_request(enforce_operator_access)

    @app.after_request
    def response_headers(response):
        response.headers["X-Request-ID"] = getattr(request, "request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; "
            "img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'"
        )
        if app.config.get("PUBLIC_BASE_URL"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path=""):
        if path.startswith("api/"):
            abort(404)
        candidate = frontend_dist / path
        if path and candidate.is_file():
            return send_from_directory(frontend_dist, path)
        index = frontend_dist / "index.html"
        if index.is_file():
            return send_from_directory(frontend_dist, "index.html")
        return (
            "StudioPilot frontend is not built. Run npm ci and npm run build in frontend/.",
            503,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    @app.cli.command("init-db")
    def init_db():
        """Create development tables; production should use flask db upgrade."""
        db.create_all()
        print("Database initialized")

    return app


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")

