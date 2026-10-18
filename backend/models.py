import json
from datetime import datetime, timezone
from uuid import uuid4

from extensions import db


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class User(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    email = db.Column(db.String(255), unique=True)
    display_name = db.Column(db.String(255))


class YouTubeAccount(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False, index=True)
    channel_id = db.Column(db.String(128), unique=True, nullable=False)
    channel_title = db.Column(db.String(255), nullable=False)
    thumbnail_url = db.Column(db.Text)
    token_encrypted = db.Column(db.LargeBinary, nullable=False)
    token_expiry = db.Column(db.DateTime(timezone=True))
    scopes_json = db.Column(db.Text, default="[]", nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))


class VideoDraft(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(32), default="draft", nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.Text, nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)
    mime_type = db.Column(db.String(100))
    checksum = db.Column(db.String(64), nullable=False, index=True)
    title = db.Column(db.String(100), default="", nullable=False)
    description = db.Column(db.Text, default="", nullable=False)
    tags_json = db.Column(db.Text, default="[]", nullable=False)
    hashtags_json = db.Column(db.Text, default="[]", nullable=False)
    seo_keywords_json = db.Column(db.Text, default="[]", nullable=False)
    category_id = db.Column(db.String(16), default="22", nullable=False)
    playlist_id = db.Column(db.String(128))
    privacy_status = db.Column(db.String(16), default="private", nullable=False)
    scheduled_at = db.Column(db.DateTime(timezone=True))
    metadata_source = db.Column(db.String(16), default="manual", nullable=False)
    manually_edited = db.Column(db.Boolean, default=False, nullable=False)
    youtube_video_id = db.Column(db.String(64), unique=True)
    youtube_url = db.Column(db.Text)
    upload_response_json = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id, "status": self.status, "filename": self.filename,
            "file_size": self.file_size, "mime_type": self.mime_type, "title": self.title,
            "description": self.description, "tags": json.loads(self.tags_json),
            "hashtags": json.loads(self.hashtags_json), "seo_keywords": json.loads(self.seo_keywords_json),
            "category_id": self.category_id, "playlist_id": self.playlist_id,
            "privacy_status": self.privacy_status, "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "metadata_source": self.metadata_source, "manually_edited": self.manually_edited,
            "youtube_video_id": self.youtube_video_id, "youtube_url": self.youtube_url,
            "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
        }


class Transcript(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    draft_id = db.Column(db.String(36), db.ForeignKey("video_draft.id"), unique=True, nullable=False)
    text = db.Column(db.Text, default="", nullable=False)
    language = db.Column(db.String(16), default="en", nullable=False)
    provider = db.Column(db.String(32), default="manual", nullable=False)
    status = db.Column(db.String(32), default="ready", nullable=False)
    error = db.Column(db.Text)


class Thumbnail(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    draft_id = db.Column(db.String(36), db.ForeignKey("video_draft.id"), nullable=False, index=True)
    file_path = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(32), nullable=False)
    selected = db.Column(db.Boolean, default=False, nullable=False)
    upload_status = db.Column(db.String(32), default="pending", nullable=False)
    error = db.Column(db.Text)


class Playlist(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    account_id = db.Column(db.String(36), db.ForeignKey("you_tube_account.id"), nullable=False)
    youtube_playlist_id = db.Column(db.String(128), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    privacy_status = db.Column(db.String(16), default="private", nullable=False)


class BatchJob(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(32), default="queued", nullable=False)
    total_count = db.Column(db.Integer, default=0, nullable=False)


class UploadJob(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    draft_id = db.Column(db.String(36), db.ForeignKey("video_draft.id"), nullable=False, index=True)
    batch_id = db.Column(db.String(36), db.ForeignKey("batch_job.id"))
    status = db.Column(db.String(32), default="queued", nullable=False, index=True)
    run_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False, index=True)
    locked_at = db.Column(db.DateTime(timezone=True))
    worker_id = db.Column(db.String(128))
    lease_expires_at = db.Column(db.DateTime(timezone=True), index=True)
    progress = db.Column(db.Integer, default=0, nullable=False)
    retry_count = db.Column(db.Integer, default=0, nullable=False)
    max_retries = db.Column(db.Integer, default=3, nullable=False)
    last_error = db.Column(db.Text)
    cancelled_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))
    idempotency_key = db.Column(db.String(128), unique=True, index=True)
    upload_session_uri = db.Column(db.Text)
    youtube_video_id = db.Column(db.String(64), index=True)
    processing_status = db.Column(db.String(32))
    processing_checked_at = db.Column(db.DateTime(timezone=True))
    verification_attempts = db.Column(db.Integer, default=0, nullable=False)
    postprocess_json = db.Column(db.Text, default="{}", nullable=False)

    def to_dict(self, include_logs=False):
        result = {"id": self.id, "draft_id": self.draft_id, "batch_id": self.batch_id,
                  "status": self.status, "progress": self.progress, "retry_count": self.retry_count,
                  "max_retries": self.max_retries, "run_at": self.run_at.isoformat(),
                  "last_error": self.last_error, "youtube_video_id": self.youtube_video_id,
                  "processing_status": self.processing_status,
                  "verification_attempts": self.verification_attempts,
                  "created_at": self.created_at.isoformat(),
                  "updated_at": self.updated_at.isoformat()}
        if include_logs:
            result["logs"] = [log.to_dict() for log in JobLog.query.filter_by(job_id=self.id).order_by(JobLog.created_at).all()]
        return result


class JobLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey("upload_job.id"), nullable=False, index=True)
    level = db.Column(db.String(16), default="info", nullable=False)
    event = db.Column(db.String(64), nullable=False)
    message = db.Column(db.Text, nullable=False)
    details_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)

    def to_dict(self):
        return {"level": self.level, "event": self.event, "message": self.message,
                "details": json.loads(self.details_json) if self.details_json else None,
                "created_at": self.created_at.isoformat()}


class ErrorLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(36), index=True)
    code = db.Column(db.String(64), nullable=False)
    message = db.Column(db.Text, nullable=False)
    details_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class WorkerHeartbeat(db.Model):
    worker_id = db.Column(db.String(128), primary_key=True)
    hostname = db.Column(db.String(255), nullable=False)
    process_id = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    last_seen_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False, index=True)
    current_job_id = db.Column(db.String(36), db.ForeignKey("upload_job.id"))


class AuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(64), nullable=False, index=True)
    action = db.Column(db.String(96), nullable=False, index=True)
    target_type = db.Column(db.String(64))
    target_id = db.Column(db.String(128), index=True)
    request_id = db.Column(db.String(36), index=True)
    details_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False, index=True)


class ConnectorAction(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    connector = db.Column(db.String(32), nullable=False, index=True)
    idempotency_key = db.Column(db.String(128), nullable=False, unique=True, index=True)
    action = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="started")
    task_id = db.Column(db.String(128))
    approval_source = db.Column(db.String(255))
    approval_digest = db.Column(db.String(128))
    request_json = db.Column(db.Text, nullable=False, default="{}")
    response_json = db.Column(db.Text)
    error = db.Column(db.Text)
