import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    APP_ENV = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower()
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'automator.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 2 * 1024 * 1024 * 1024))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
    GENERATED_FOLDER = os.getenv("GENERATED_FOLDER", str(BASE_DIR / "generated"))
    GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    CORS_ORIGINS = [origin.strip().rstrip("/") for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:8080,http://localhost:5173"
    ).split(",") if origin.strip()]
    if APP_ENV == "production" and "*" in CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS must contain exact frontend origins in production; '*' is not allowed")
    TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    OPERATOR_PASSWORD_HASH = os.getenv("OPERATOR_PASSWORD_HASH", "")
    LOCAL_AUTH_BYPASS = os.getenv("LOCAL_AUTH_BYPASS", "true").lower() == "true"
    HAI_CONNECTOR_ENABLED = os.getenv("HAI_CONNECTOR_ENABLED", "false").lower() == "true"
    HAI_CONNECTOR_TOKEN = os.getenv("HAI_CONNECTOR_TOKEN", "")
    WORKER_POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "5"))
    JOB_MAX_RETRIES = int(os.getenv("JOB_MAX_RETRIES", "3"))
    JOB_LEASE_SECONDS = int(os.getenv("JOB_LEASE_SECONDS", "300"))
    JOB_VERIFY_SECONDS = int(os.getenv("JOB_VERIFY_SECONDS", "30"))
    STALE_WORKER_SECONDS = int(os.getenv("STALE_WORKER_SECONDS", "120"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = PUBLIC_BASE_URL.startswith("https://")
    PERMANENT_SESSION_LIFETIME = 12 * 60 * 60
    MAX_DASHBOARD_ITEMS = int(os.getenv("MAX_DASHBOARD_ITEMS", "200"))


def validate_runtime_config(config):
    errors = []
    public = bool(config.get("PUBLIC_BASE_URL"))
    production = config.get("APP_ENV") == "production"
    if production or public:
        if len(config.get("SECRET_KEY", "")) < 32 or config.get("SECRET_KEY") == "dev-only-change-me":
            errors.append("SECRET_KEY must be a unique value of at least 32 characters")
        if not config.get("OPERATOR_PASSWORD_HASH"):
            errors.append("OPERATOR_PASSWORD_HASH is required for public or production operation")
        if public:
            parsed = urlparse(config["PUBLIC_BASE_URL"])
            if parsed.scheme != "https" or not parsed.netloc:
                errors.append("PUBLIC_BASE_URL must be an absolute HTTPS URL")
        if config.get("LOCAL_AUTH_BYPASS"):
            errors.append("LOCAL_AUTH_BYPASS must be false for public or production operation")
    if config.get("GOOGLE_CLIENT_SECRETS_FILE") and not config.get("TOKEN_ENCRYPTION_KEY"):
        errors.append("TOKEN_ENCRYPTION_KEY is required when Google OAuth is configured")
    if config.get("HAI_CONNECTOR_ENABLED") and len(config.get("HAI_CONNECTOR_TOKEN", "")) < 32:
        errors.append("HAI_CONNECTOR_TOKEN must contain at least 32 characters when the connector is enabled")
    if config.get("JOB_LEASE_SECONDS", 0) < 30:
        errors.append("JOB_LEASE_SECONDS must be at least 30")
    if errors:
        raise RuntimeError("Invalid runtime configuration: " + "; ".join(errors))
