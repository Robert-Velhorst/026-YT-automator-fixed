import hmac
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash

from audit import record_audit
from errors import ApiError
from extensions import db


operator_bp = Blueprint("operator", __name__)
_failures = {}


def _client_key():
    return request.remote_addr or "unknown"


def _local_bypass_active():
    if current_app.config.get("PUBLIC_BASE_URL") or not current_app.config.get("LOCAL_AUTH_BYPASS"):
        return False
    return _client_key() in {"127.0.0.1", "::1"}


def _require_allowed_origin():
    origin = request.headers.get("Origin")
    if not origin:
        return
    allowed = {value.rstrip("/") for value in current_app.config.get("CORS_ORIGINS", [])}
    if current_app.config.get("PUBLIC_BASE_URL"):
        allowed.add(current_app.config["PUBLIC_BASE_URL"])
    if origin.rstrip("/") not in allowed:
        raise ApiError("Request origin is not allowed", 403, "origin_not_allowed")


def operator_authenticated():
    return _local_bypass_active() or session.get("operator_authenticated") is True


def enforce_operator_access():
    path = request.path
    if not path.startswith("/api/"):
        return None
    if path in {"/api/health", "/api/readiness", "/api/operator/status", "/api/operator/login", "/api/auth/callback"}:
        return None
    if path.startswith("/api/integrations/hai/"):
        return None
    if not operator_authenticated():
        raise ApiError("Operator authentication is required", 401, "operator_authentication_required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_allowed_origin()
    return None


@operator_bp.get("/status")
def status():
    required = not _local_bypass_active()
    return jsonify({"required": required, "authenticated": operator_authenticated(), "local_bypass": not required})


@operator_bp.post("/login")
def login():
    _require_allowed_origin()
    key = _client_key()
    now = datetime.now(timezone.utc)
    attempts = [value for value in _failures.get(key, []) if value > now - timedelta(minutes=15)]
    _failures[key] = attempts
    if len(attempts) >= 8:
        raise ApiError("Too many login attempts; try again later", 429, "login_rate_limited")
    configured = current_app.config.get("OPERATOR_PASSWORD_HASH", "")
    password = str((request.get_json(silent=True) or {}).get("password", ""))
    if not configured or not check_password_hash(configured, password):
        attempts.append(now)
        _failures[key] = attempts
        raise ApiError("Invalid operator password", 401, "invalid_operator_credentials")
    _failures.pop(key, None)
    session.clear()
    session["operator_authenticated"] = True
    session.permanent = True
    record_audit("operator.login", actor="operator", commit=True)
    return jsonify({"authenticated": True})


@operator_bp.post("/logout")
def logout():
    if session.get("operator_authenticated"):
        record_audit("operator.logout", actor="operator", commit=True)
    session.clear()
    return jsonify({"authenticated": False})
