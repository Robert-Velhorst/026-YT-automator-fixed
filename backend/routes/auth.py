import json
import os
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, redirect, request, session
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest

from errors import ApiError
from extensions import db
from models import User, YouTubeAccount
from audit import record_audit
from security import encrypt_token
from services.youtube_service import SCOPES, channel_info, credentials_for, service_for


auth_bp = Blueprint("auth", __name__)


def default_user():
    user = User.query.first()
    if not user:
        user = User(display_name="Local operator")
        db.session.add(user)
        db.session.commit()
    return user


def callback_url():
    base = current_app.config.get("PUBLIC_BASE_URL") or request.url_root.rstrip("/")
    return base + "/api/auth/callback"


@auth_bp.get("/status")
def status():
    account = YouTubeAccount.query.filter_by(user_id=default_user().id, revoked_at=None).first()
    return jsonify({"authenticated": bool(account), "channel": {"id": account.channel_id,
        "title": account.channel_title, "thumbnail": account.thumbnail_url} if account else None})


@auth_bp.get("/login")
def login():
    credentials_file = current_app.config["GOOGLE_CLIENT_SECRETS_FILE"]
    if not credentials_file or not os.path.exists(credentials_file):
        raise ApiError("Google OAuth credentials are not configured", 503, "oauth_not_configured")
    redirect_uri = callback_url()
    flow = Flow.from_client_secrets_file(credentials_file, scopes=SCOPES, redirect_uri=redirect_uri)
    url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    session["oauth_state"] = state
    return jsonify({"auth_url": url})


@auth_bp.get("/callback")
def callback():
    state = session.pop("oauth_state", None)
    if not state or request.args.get("state") != state:
        raise ApiError("OAuth state validation failed", 400, "invalid_oauth_state")
    redirect_uri = callback_url()
    flow = Flow.from_client_secrets_file(current_app.config["GOOGLE_CLIENT_SECRETS_FILE"], scopes=SCOPES,
                                         state=state, redirect_uri=redirect_uri)
    authorization_response = request.url
    if current_app.config.get("PUBLIC_BASE_URL"):
        authorization_response = current_app.config["PUBLIC_BASE_URL"] + request.full_path.rstrip("?")
    flow.fetch_token(authorization_response=authorization_response)
    info = channel_info(service_for_credentials(flow.credentials))
    user = default_user()
    account = YouTubeAccount.query.filter_by(channel_id=info["id"]).first() or YouTubeAccount(user_id=user.id, channel_id=info["id"])
    account.channel_title, account.thumbnail_url = info["title"], info["thumbnail"]
    account.token_encrypted = encrypt_token(flow.credentials.to_json())
    account.token_expiry = flow.credentials.expiry
    account.scopes_json = json.dumps(flow.credentials.scopes or SCOPES)
    account.revoked_at = None
    db.session.add(account)
    record_audit("youtube.connected", "youtube_account", account.id, details={"channel_id": info["id"]})
    db.session.commit()
    destination = current_app.config.get("PUBLIC_BASE_URL") or current_app.config["FRONTEND_URL"].rstrip("/")
    return redirect(destination + "/?oauth=success")


def service_for_credentials(credentials):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


@auth_bp.post("/refresh")
def refresh():
    account = YouTubeAccount.query.filter_by(user_id=default_user().id, revoked_at=None).first()
    if not account:
        raise ApiError("No connected YouTube account", 401, "authentication_required")
    service_for(account)
    return jsonify({"refreshed": True})


@auth_bp.post("/logout")
def logout():
    account = YouTubeAccount.query.filter_by(user_id=default_user().id, revoked_at=None).first()
    if account:
        try:
            credentials = credentials_for(account)
            GoogleRequest()(url="https://oauth2.googleapis.com/revoke", method="POST", body=f"token={credentials.token}",
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
        except Exception:
            current_app.logger.warning("Google token revocation failed; local credentials will still be removed", exc_info=True)
        account.revoked_at = datetime.now(timezone.utc)
        account.token_encrypted = b"revoked"
        record_audit("youtube.disconnected", "youtube_account", account.id)
        db.session.commit()
    session.pop("oauth_state", None)
    return jsonify({"authenticated": False})


@auth_bp.get("/channel")
def channel():
    account = YouTubeAccount.query.filter_by(user_id=default_user().id, revoked_at=None).first()
    if not account:
        raise ApiError("Connect YouTube first", 401, "authentication_required")
    return jsonify(channel_info(service_for(account)))

