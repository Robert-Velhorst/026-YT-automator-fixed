import hashlib
import json
import mimetypes
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from dateutil.parser import isoparse
from flask import Blueprint, current_app, jsonify, request, send_file
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from errors import ApiError
from extensions import db
from audit import record_audit
from models import BatchJob, Thumbnail, Transcript, UploadJob, User, VideoDraft, WorkerHeartbeat, YouTubeAccount
from services.job_service import enqueue_job
from services.metadata_service import generate_metadata
from services.thumbnail_service import generate_thumbnail
from services.transcription_service import TranscriptionUnavailable, transcribe_video


api_bp = Blueprint("api", __name__)
ALLOWED_EXTENSIONS = {"mp4", "mov", "m4v", "webm", "mkv", "avi"}
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
PRIVACY = {"private", "unlisted", "public"}


def user():
    value = User.query.first()
    if not value:
        value = User(display_name="Local operator")
        db.session.add(value); db.session.commit()
    return value


def draft_or_404(draft_id):
    draft = VideoDraft.query.filter_by(id=draft_id, user_id=user().id).first()
    if not draft:
        raise ApiError("Draft not found", 404, "not_found")
    return draft


def parse_run_at(value):
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = isoparse(value)
    except (TypeError, ValueError) as exc:
        raise ApiError("run_at must be an ISO 8601 timestamp", 422, "validation_error") from exc
    if parsed.tzinfo is None:
        raise ApiError("run_at must include a timezone", 422, "validation_error")
    return parsed.astimezone(timezone.utc)


def runtime_checks():
    checks = {
        "database": False,
        "oauth_configured": bool(current_app.config["GOOGLE_CLIENT_SECRETS_FILE"]),
        "ai_configured": bool(current_app.config["OPENAI_API_KEY"]),
        "token_encryption_configured": bool(current_app.config["TOKEN_ENCRYPTION_KEY"]),
        "operator_auth_configured": bool(current_app.config["OPERATOR_PASSWORD_HASH"]) or not current_app.config.get("PUBLIC_BASE_URL"),
        "hai_connector_configured": bool(current_app.config.get("HAI_CONNECTOR_ENABLED") and current_app.config.get("HAI_CONNECTOR_TOKEN")),
        "worker_online": False,
    }
    try:
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = True
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=current_app.config["STALE_WORKER_SECONDS"])
        checks["worker_online"] = WorkerHeartbeat.query.filter(WorkerHeartbeat.last_seen_at >= cutoff).first() is not None
    except Exception:
        db.session.rollback()
    return checks


@api_bp.get("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})


@api_bp.get("/readiness")
def readiness():
    checks = runtime_checks()
    return jsonify({"status": "ready" if checks["database"] else "not_ready", "checks": checks}), (200 if checks["database"] else 503)


@api_bp.get("/settings")
def settings():
    checks = runtime_checks()
    return jsonify({"status": "ready" if checks["database"] else "not_ready", "checks": checks})


@api_bp.get("/dashboard")
def dashboard():
    limit = min(max(request.args.get("limit", type=int) or 100, 1), current_app.config["MAX_DASHBOARD_ITEMS"])
    operator = user()
    drafts = VideoDraft.query.filter_by(user_id=operator.id).order_by(VideoDraft.updated_at.desc()).limit(limit).all()
    jobs = (
        UploadJob.query.join(VideoDraft, UploadJob.draft_id == VideoDraft.id)
        .filter(VideoDraft.user_id == operator.id)
        .order_by(UploadJob.updated_at.desc())
        .limit(limit)
        .all()
    )
    account = YouTubeAccount.query.filter_by(user_id=operator.id, revoked_at=None).first()
    checks = runtime_checks()
    return jsonify({
        "drafts": [value.to_dict() for value in drafts],
        "jobs": [value.to_dict() for value in jobs],
        "auth": {
            "authenticated": bool(account),
            "channel": {"id": account.channel_id, "title": account.channel_title, "thumbnail": account.thumbnail_url} if account else None,
        },
        "checks": checks,
        "server_time": datetime.now(timezone.utc).isoformat(),
    })


@api_bp.post("/videos/validate")
def validate_video():
    file = request.files.get("video")
    if not file or not file.filename:
        raise ApiError("A video file is required", 400, "validation_error")
    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    file.seek(0, os.SEEK_END); size = file.tell(); file.seek(0)
    if extension not in ALLOWED_EXTENSIONS:
        raise ApiError("Unsupported video type", 415, "unsupported_media_type", sorted(ALLOWED_EXTENSIONS))
    if size == 0 or size > current_app.config["MAX_CONTENT_LENGTH"]:
        raise ApiError("Video is empty or exceeds the configured upload limit", 413, "file_size_invalid")
    return jsonify({"valid": True, "filename": secure_filename(file.filename), "size": size})


@api_bp.post("/drafts")
def create_draft():
    file = request.files.get("video")
    if not file or not file.filename:
        raise ApiError("A video file is required", 400, "validation_error")
    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ApiError("Unsupported video type", 415, "unsupported_media_type")
    draft_id, filename = str(uuid4()), secure_filename(file.filename)
    if not filename:
        raise ApiError("The video filename is invalid", 422, "validation_error")
    path = Path(current_app.config["UPLOAD_FOLDER"]) / f"{draft_id}-{filename}"
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("xb") as output:
            while True:
                chunk = file.stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > current_app.config["MAX_CONTENT_LENGTH"]:
                    raise ApiError("Video exceeds the configured upload limit", 413, "file_size_invalid")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise ApiError("Video is empty", 413, "file_size_invalid")
    checksum = digest.hexdigest()
    operator = user()
    duplicate = VideoDraft.query.filter(VideoDraft.user_id == operator.id, VideoDraft.checksum == checksum, VideoDraft.status != "cancelled").first()
    if duplicate and request.form.get("allow_duplicate") != "true":
        path.unlink(missing_ok=True)
        raise ApiError("This exact video already exists", 409, "duplicate_video", {"draft_id": duplicate.id})
    title = Path(filename).stem.replace("_", " ").replace("-", " ")[:100]
    draft = VideoDraft(id=draft_id, user_id=operator.id, filename=filename, file_path=str(path), file_size=size,
                       mime_type=file.mimetype or mimetypes.guess_type(filename)[0], checksum=checksum, title=title)
    try:
        db.session.add(draft)
        record_audit("draft.created", "video_draft", draft.id, details={"filename": filename, "size": size})
        db.session.commit()
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise
    return jsonify({"draft": draft.to_dict()}), 201


@api_bp.get("/drafts")
def list_drafts():
    limit = min(max(request.args.get("limit", type=int) or 100, 1), current_app.config["MAX_DASHBOARD_ITEMS"])
    values = VideoDraft.query.filter_by(user_id=user().id).order_by(VideoDraft.created_at.desc()).limit(limit).all()
    return jsonify({"drafts": [value.to_dict() for value in values]})


@api_bp.get("/drafts/<draft_id>")
def get_draft(draft_id):
    draft = draft_or_404(draft_id)
    transcript = Transcript.query.filter_by(draft_id=draft_id).first()
    thumbnails = Thumbnail.query.filter_by(draft_id=draft_id).all()
    result = draft.to_dict()
    result["transcript"] = {"text": transcript.text, "status": transcript.status, "provider": transcript.provider,
                            "error": transcript.error} if transcript else None
    result["thumbnails"] = [{"id": t.id, "source": t.source, "selected": t.selected,
                             "upload_status": t.upload_status, "error": t.error,
                             "url": f"/api/thumbnails/{t.id}/file"} for t in thumbnails]
    return jsonify({"draft": result})


@api_bp.patch("/drafts/<draft_id>")
def update_draft(draft_id):
    draft, data = draft_or_404(draft_id), (request.get_json(silent=True) or {})
    for field in ("title", "description", "category_id", "playlist_id", "privacy_status"):
        if field in data:
            setattr(draft, field, data[field] or (None if field == "playlist_id" else ""))
    if len(draft.title) > 100 or len(draft.description) > 5000:
        raise ApiError("Title or description exceeds YouTube limits", 422, "validation_error")
    if draft.privacy_status not in PRIVACY:
        raise ApiError("Privacy must be private, unlisted, or public", 422, "validation_error")
    for field in ("tags", "hashtags", "seo_keywords"):
        if field in data:
            values = data[field]
            if not isinstance(values, list):
                raise ApiError(f"{field} must be an array", 422, "validation_error")
            setattr(draft, f"{field}_json", json.dumps([str(v).strip()[:100] for v in values[:100] if str(v).strip()]))
    if len(",".join(json.loads(draft.tags_json))) > 500:
        raise ApiError("Combined tags exceed 500 characters", 422, "validation_error")
    if "scheduled_at" in data:
        draft.scheduled_at = parse_run_at(data["scheduled_at"]) if data["scheduled_at"] else None
    draft.manually_edited = True
    record_audit("draft.updated", "video_draft", draft.id)
    db.session.commit()
    return jsonify({"draft": draft.to_dict()})


@api_bp.post("/drafts/<draft_id>/metadata/generate")
def metadata(draft_id):
    draft = draft_or_404(draft_id)
    transcript = Transcript.query.filter_by(draft_id=draft_id).first()
    data = request.get_json(silent=True) or {}
    context = data.get("context") or (transcript.text if transcript else draft.title)
    result = generate_metadata(context, data.get("prompt"))
    draft.title, draft.description = result["title"], result["description"]
    draft.tags_json, draft.hashtags_json = json.dumps(result["tags"]), json.dumps(result.get("hashtags", []))
    draft.seo_keywords_json, draft.category_id = json.dumps(result.get("seo_keywords", [])), str(result.get("category_id", "22"))
    draft.metadata_source, draft.status = result["source"], "ready"
    db.session.commit()
    return jsonify({"metadata": result, "draft": draft.to_dict()})


@api_bp.post("/drafts/<draft_id>/transcript/generate")
def generate_transcript(draft_id):
    draft = draft_or_404(draft_id)
    transcript = Transcript.query.filter_by(draft_id=draft_id).first() or Transcript(draft_id=draft_id)
    try:
        transcript.text, transcript.provider, transcript.status, transcript.error = transcribe_video(draft.file_path), "openai-whisper", "ready", None
    except TranscriptionUnavailable as exc:
        transcript.status, transcript.error = "unavailable", str(exc)
        db.session.add(transcript); db.session.commit()
        raise ApiError(str(exc), 503, "transcription_unavailable")
    db.session.add(transcript); db.session.commit()
    return jsonify({"transcript": {"text": transcript.text, "status": transcript.status, "provider": transcript.provider}})


@api_bp.put("/drafts/<draft_id>/transcript")
def update_transcript(draft_id):
    draft_or_404(draft_id); data = request.get_json(silent=True) or {}
    transcript = Transcript.query.filter_by(draft_id=draft_id).first() or Transcript(draft_id=draft_id)
    transcript.text, transcript.provider, transcript.status, transcript.error = str(data.get("text", "")), "manual", "ready", None
    db.session.add(transcript); db.session.commit()
    return jsonify({"transcript": {"text": transcript.text, "status": transcript.status, "provider": transcript.provider}})


@api_bp.post("/drafts/<draft_id>/thumbnails/generate")
def generate_thumbnails(draft_id):
    draft = draft_or_404(draft_id)
    generated = []
    for style in ("modern", "bright", "bold"):
        target = Path(current_app.config["GENERATED_FOLDER"]) / f"{uuid4()}.jpg"
        generate_thumbnail(target, draft.title, style)
        thumbnail = Thumbnail(draft_id=draft.id, file_path=str(target), source=f"generated:{style}")
        db.session.add(thumbnail); generated.append(thumbnail)
    db.session.commit()
    return jsonify({"thumbnails": [{"id": t.id, "url": f"/api/thumbnails/{t.id}/file", "source": t.source} for t in generated]}), 201


@api_bp.post("/drafts/<draft_id>/thumbnails")
def custom_thumbnail(draft_id):
    draft_or_404(draft_id); file = request.files.get("thumbnail")
    ext = file.filename.rsplit(".", 1)[-1].lower() if file and file.filename and "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ApiError("Thumbnail must be JPG or PNG", 415, "unsupported_media_type")
    target = Path(current_app.config["GENERATED_FOLDER"]) / f"{uuid4()}.{ext}"
    size = 0
    try:
        with target.open("xb") as output:
            while chunk := file.stream.read(256 * 1024):
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    raise ApiError("YouTube thumbnails must be 2 MB or smaller", 413, "file_size_invalid")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if not size:
        target.unlink(missing_ok=True)
        raise ApiError("Thumbnail is empty", 422, "file_size_invalid")
    try:
        with Image.open(target) as image:
            image.verify()
        with Image.open(target) as image:
            width, height = image.size
            if width < 320 or height < 180 or width * height > 40_000_000:
                raise ApiError("Thumbnail dimensions must be at least 320x180 and no more than 40 megapixels", 422, "invalid_image_dimensions")
    except ApiError:
        target.unlink(missing_ok=True)
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        target.unlink(missing_ok=True)
        raise ApiError("Thumbnail content is not a valid image", 415, "unsupported_media_type")
    thumbnail = Thumbnail(draft_id=draft_id, file_path=str(target), source="custom")
    try:
        db.session.add(thumbnail)
        db.session.commit()
    except Exception:
        db.session.rollback()
        target.unlink(missing_ok=True)
        raise
    return jsonify({"thumbnail": {"id": thumbnail.id, "url": f"/api/thumbnails/{thumbnail.id}/file"}}), 201


@api_bp.post("/drafts/<draft_id>/thumbnails/<thumbnail_id>/select")
def select_thumbnail(draft_id, thumbnail_id):
    draft_or_404(draft_id)
    thumbnail = Thumbnail.query.filter_by(id=thumbnail_id, draft_id=draft_id).first()
    if not thumbnail or not Path(thumbnail.file_path).is_file():
        raise ApiError("Thumbnail not found", 404, "not_found")
    Thumbnail.query.filter_by(draft_id=draft_id).update({"selected": False}); thumbnail.selected = True; db.session.commit()
    return jsonify({"selected": thumbnail.id})


@api_bp.get("/thumbnails/<thumbnail_id>/file")
def thumbnail_file(thumbnail_id):
    thumbnail = Thumbnail.query.join(VideoDraft, Thumbnail.draft_id == VideoDraft.id).filter(
        Thumbnail.id == thumbnail_id, VideoDraft.user_id == user().id
    ).first()
    if not thumbnail: raise ApiError("Thumbnail not found", 404, "not_found")
    return send_file(thumbnail.file_path)


@api_bp.post("/drafts/<draft_id>/jobs")
def create_job(draft_id):
    draft, data = draft_or_404(draft_id), (request.get_json(silent=True) or {})
    key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
    job, replayed = enqueue_job(draft, parse_run_at(data.get("run_at")), idempotency_key=key)
    return jsonify({"job": job.to_dict(), "replayed": replayed}), (200 if replayed else 201)


@api_bp.post("/batch-jobs")
def create_batch():
    ids = (request.get_json(silent=True) or {}).get("draft_ids", [])
    if not ids or len(ids) > 50 or len(set(ids)) != len(ids):
        raise ApiError("draft_ids must contain 1 to 50 unique IDs", 422, "validation_error")
    drafts = [draft_or_404(draft_id) for draft_id in ids]
    batch = BatchJob(user_id=user().id, total_count=len(ids)); db.session.add(batch); db.session.flush()
    jobs = []
    for draft in drafts:
        job, _ = enqueue_job(draft, batch_id=batch.id, idempotency_key=f"batch:{batch.id}:{draft.id}", commit=False)
        jobs.append(job)
    db.session.commit()
    return jsonify({"batch_id": batch.id, "jobs": [job.to_dict() for job in jobs]}), 201


@api_bp.get("/jobs")
def jobs():
    limit = min(max(request.args.get("limit", type=int) or 100, 1), current_app.config["MAX_DASHBOARD_ITEMS"])
    values = UploadJob.query.join(VideoDraft).filter(VideoDraft.user_id == user().id).order_by(UploadJob.created_at.desc()).limit(limit).all()
    return jsonify({"jobs": [job.to_dict() for job in values]})


@api_bp.get("/jobs/<job_id>")
def get_job(job_id):
    job = UploadJob.query.join(VideoDraft).filter(UploadJob.id == job_id, VideoDraft.user_id == user().id).first()
    if not job: raise ApiError("Job not found", 404, "not_found")
    return jsonify({"job": job.to_dict(include_logs=True)})


@api_bp.post("/jobs/<job_id>/retry")
def retry(job_id):
    job = UploadJob.query.join(VideoDraft).filter(UploadJob.id == job_id, VideoDraft.user_id == user().id).first()
    if not job or job.status != "failed": raise ApiError("Only failed jobs can be retried", 409, "invalid_job_state")
    draft = draft_or_404(job.draft_id)
    next_status = "processing" if draft.youtube_video_id else "retry_pending"
    job.status, job.run_at, job.last_error = next_status, datetime.now(timezone.utc), None
    draft.status = next_status
    record_audit("upload_job.retried", "upload_job", job.id)
    db.session.commit()
    return jsonify({"job": job.to_dict()})


@api_bp.post("/jobs/<job_id>/cancel")
def cancel(job_id):
    job = UploadJob.query.join(VideoDraft).filter(UploadJob.id == job_id, VideoDraft.user_id == user().id).first()
    if not job or job.status not in {"queued", "scheduled", "retry_pending"}: raise ApiError("Job cannot be cancelled", 409, "invalid_job_state")
    job.status, job.cancelled_at = "cancelled", datetime.now(timezone.utc)
    draft_or_404(job.draft_id).status = "cancelled"
    record_audit("upload_job.cancelled", "upload_job", job.id)
    db.session.commit()
    return jsonify({"job": job.to_dict()})


@api_bp.get("/history")
def history():
    uploaded = VideoDraft.query.filter(VideoDraft.user_id == user().id, VideoDraft.status.in_(["uploaded", "failed"])).order_by(VideoDraft.updated_at.desc()).limit(current_app.config["MAX_DASHBOARD_ITEMS"]).all()
    return jsonify({"history": [draft.to_dict() for draft in uploaded]})
