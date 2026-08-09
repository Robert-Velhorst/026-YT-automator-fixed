import json
import mimetypes
import random
import time
from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from extensions import db
from models import Thumbnail, YouTubeAccount
from security import decrypt_token, encrypt_token


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class YouTubeError(RuntimeError):
    def __init__(self, message, recoverable=False, code="youtube_error"):
        super().__init__(message)
        self.recoverable, self.code = recoverable, code


def credentials_for(account):
    try:
        creds = Credentials.from_authorized_user_info(json.loads(decrypt_token(account.token_encrypted)), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            account.token_encrypted = encrypt_token(creds.to_json())
            account.token_expiry = creds.expiry
            db.session.commit()
    except (RefreshError, ValueError, RuntimeError) as exc:
        account.revoked_at = account.revoked_at or datetime.now(timezone.utc)
        db.session.commit()
        raise YouTubeError("Google authorization must be renewed", code="reauthorization_required") from exc
    if not creds.valid:
        raise YouTubeError("Google authorization is expired or revoked", code="reauthorization_required")
    return creds


def service_for(account=None, user_id=None):
    if account is None:
        query = YouTubeAccount.query.filter_by(revoked_at=None)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        account = query.first()
    if not account:
        raise YouTubeError("Connect a YouTube account first", code="authentication_required")
    return build("youtube", "v3", credentials=credentials_for(account), cache_discovery=False)


def _error_reason(exc):
    status = getattr(exc.resp, "status", None)
    reason = None
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        error = payload.get("error", {})
        reason = error.get("message")
        details = error.get("errors") or []
        if details and details[0].get("reason"):
            reason = f"{reason or 'YouTube request failed'} ({details[0]['reason']})"
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return status, (reason or "YouTube request failed")[:500]


def classify_http_error(exc):
    status, message = _error_reason(exc)
    if status in (429, 500, 502, 503, 504):
        return YouTubeError(message, recoverable=True, code="youtube_temporarily_unavailable")
    if status == 401:
        return YouTubeError("Google authorization is invalid or revoked", code="reauthorization_required")
    if status == 403 and "quota" in message.lower():
        return YouTubeError("YouTube API quota is exhausted", code="quota_exceeded")
    return YouTubeError(message, code="youtube_request_rejected")


def execute_with_retry(callable_, attempts=4):
    for attempt in range(attempts):
        try:
            return callable_()
        except HttpError as exc:
            error = classify_http_error(exc)
            if not error.recoverable or attempt == attempts - 1:
                raise error from exc
            time.sleep(min(2 ** attempt + random.random(), 8))


def upload_video(draft, progress_callback=None, session_callback=None, resumable_uri=None):
    youtube = service_for(user_id=draft.user_id)
    body = {
        "snippet": {
            "title": draft.title,
            "description": draft.description,
            "tags": json.loads(draft.tags_json),
            "categoryId": draft.category_id,
        },
        "status": {"privacyStatus": draft.privacy_status, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(
        draft.file_path,
        mimetype=draft.mime_type or "application/octet-stream",
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )
    upload_request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    if resumable_uri:
        upload_request.resumable_uri = resumable_uri
    response = None
    while response is None:
        try:
            status, response = upload_request.next_chunk(num_retries=0)
        except HttpError as exc:
            raise classify_http_error(exc) from exc
        if upload_request.resumable_uri and session_callback:
            session_callback(upload_request.resumable_uri)
        if status and progress_callback:
            progress_callback(max(1, min(99, int(status.progress() * 100))))
    if not response or not response.get("id"):
        raise YouTubeError("YouTube did not return a video ID", code="invalid_upload_response")
    return response


def postprocess_video(draft, state=None, state_callback=None):
    youtube = service_for(user_id=draft.user_id)
    state = dict(state or {})
    warnings = []
    thumbnail = Thumbnail.query.filter_by(draft_id=draft.id, selected=True).first()
    if thumbnail and not state.get("thumbnail"):
        try:
            execute_with_retry(lambda: youtube.thumbnails().set(
                videoId=draft.youtube_video_id,
                media_body=MediaFileUpload(
                    thumbnail.file_path,
                    mimetype=mimetypes.guess_type(thumbnail.file_path)[0] or "image/jpeg",
                ),
            ).execute())
            thumbnail.upload_status = "uploaded"
            thumbnail.error = None
            state["thumbnail"] = "uploaded"
        except YouTubeError as exc:
            thumbnail.upload_status, thumbnail.error = "failed", str(exc)
            state["thumbnail"] = "failed"
            warnings.append(f"Thumbnail upload failed: {exc}")
        if state_callback:
            state_callback(state)
    if draft.playlist_id and not state.get("playlist"):
        try:
            existing = execute_with_retry(lambda: youtube.playlistItems().list(
                part="id", playlistId=draft.playlist_id, videoId=draft.youtube_video_id, maxResults=1
            ).execute())
            if not existing.get("items"):
                execute_with_retry(lambda: youtube.playlistItems().insert(part="snippet", body={"snippet": {
                    "playlistId": draft.playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": draft.youtube_video_id},
                }}).execute())
            state["playlist"] = "assigned"
        except YouTubeError as exc:
            state["playlist"] = "failed"
            warnings.append(f"Playlist assignment failed: {exc}")
        if state_callback:
            state_callback(state)
    return state, warnings


def video_processing_state(video_id, user_id=None):
    youtube = service_for(user_id=user_id)
    response = execute_with_retry(lambda: youtube.videos().list(
        part="status,processingDetails", id=video_id, maxResults=1
    ).execute())
    items = response.get("items") or []
    if not items:
        return "failed", "The uploaded video is no longer available"
    item = items[0]
    upload_status = item.get("status", {}).get("uploadStatus")
    details = item.get("processingDetails", {})
    processing = details.get("processingStatus")
    if processing == "succeeded" or upload_status == "processed":
        return "succeeded", None
    if processing in {"failed", "terminated"} or upload_status in {"failed", "rejected", "deleted"}:
        failure = details.get("processingFailureReason") or upload_status or "processing_failed"
        return "failed", f"YouTube processing failed: {failure}"
    return "processing", None


def channel_info(youtube):
    response = execute_with_retry(lambda: youtube.channels().list(part="id,snippet,statistics", mine=True).execute())
    if not response.get("items"):
        raise YouTubeError("No YouTube channel was found for this Google account")
    item = response["items"][0]
    return {
        "id": item["id"],
        "title": item["snippet"]["title"],
        "thumbnail": item["snippet"].get("thumbnails", {}).get("default", {}).get("url"),
        "statistics": item.get("statistics", {}),
    }
