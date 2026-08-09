import json
import os
import socket
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import current_app

from audit import record_audit
from errors import ApiError
from extensions import db
from models import BatchJob, JobLog, UploadJob, VideoDraft, WorkerHeartbeat
from security import decrypt_token, encrypt_token
from services.youtube_service import YouTubeError, postprocess_video, upload_video, video_processing_state


ACTIVE_JOB_STATUSES = {"queued", "scheduled", "uploading", "retry_pending", "processing", "verifying"}


def log(job, event, message, level="info", details=None):
    db.session.add(JobLog(
        job_id=job.id,
        event=event,
        message=message,
        level=level,
        details_json=json.dumps(details, separators=(",", ":")) if details else None,
    ))


def enqueue_job(draft, run_at=None, batch_id=None, idempotency_key=None, actor="operator", commit=True):
    if not draft.title.strip():
        raise ApiError("A title is required", 422, "draft_not_ready")
    if draft.youtube_video_id:
        raise ApiError("Draft has already been uploaded", 409, "already_uploaded")
    if idempotency_key:
        existing = UploadJob.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            if existing.draft_id != draft.id:
                raise ApiError("Idempotency key is already used for another draft", 409, "idempotency_conflict")
            return existing, True
    active = UploadJob.query.filter(
        UploadJob.draft_id == draft.id,
        UploadJob.status.in_(ACTIVE_JOB_STATUSES),
    ).first()
    if active:
        raise ApiError("An active upload job already exists", 409, "duplicate_job", {"job_id": active.id})
    now = datetime.now(timezone.utc)
    run_at = run_at or now
    status = "scheduled" if run_at > now else "queued"
    job = UploadJob(
        draft_id=draft.id,
        batch_id=batch_id,
        run_at=run_at,
        status=status,
        max_retries=current_app.config["JOB_MAX_RETRIES"],
        idempotency_key=idempotency_key or str(uuid4()),
    )
    draft.status = status
    draft.scheduled_at = run_at if status == "scheduled" else None
    db.session.add(job)
    db.session.flush()
    log(job, "created", f"Upload job {status}")
    record_audit("upload_job.created", "upload_job", job.id, actor=actor, details={"draft_id": draft.id, "run_at": run_at.isoformat()})
    if commit:
        db.session.commit()
    return job, False


def heartbeat(worker_id, current_job_id=None):
    value = db.session.get(WorkerHeartbeat, worker_id)
    now = datetime.now(timezone.utc)
    if value is None:
        value = WorkerHeartbeat(
            worker_id=worker_id,
            hostname=socket.gethostname(),
            process_id=os.getpid(),
            started_at=now,
        )
        db.session.add(value)
    value.last_seen_at = now
    value.current_job_id = current_job_id
    retention = max(current_app.config["STALE_WORKER_SECONDS"] * 10, 3600)
    WorkerHeartbeat.query.filter(WorkerHeartbeat.last_seen_at < now - timedelta(seconds=retention)).delete()
    db.session.commit()


def recover_stale_jobs():
    now = datetime.now(timezone.utc)
    stale = UploadJob.query.filter(
        UploadJob.status.in_(["uploading", "verifying"]),
        UploadJob.lease_expires_at.is_not(None),
        UploadJob.lease_expires_at < now,
    ).all()
    for job in stale:
        draft = db.session.get(VideoDraft, job.draft_id)
        if not draft:
            job.status = "failed"
            job.last_error = "Draft no longer exists"
        elif draft.youtube_video_id or job.youtube_video_id:
            job.status = draft.status = "processing"
            job.run_at = now
            log(job, "lease_recovered", "Recovered interrupted verification", "warning")
        else:
            job.status = draft.status = "retry_pending"
            job.run_at = now
            log(job, "lease_recovered", "Recovered interrupted resumable upload", "warning")
        job.worker_id = None
        job.lease_expires_at = None
    if stale:
        db.session.commit()
    return len(stale)


def claim_next_job(worker_id=None):
    worker_id = worker_id or str(uuid4())
    available = ["queued", "scheduled", "retry_pending", "processing"]
    job = None
    for _attempt in range(5):
        now = datetime.now(timezone.utc)
        candidate = (
            db.session.query(UploadJob.id, UploadJob.status)
            .filter(UploadJob.status.in_(available), UploadJob.run_at <= now)
            .order_by(UploadJob.run_at, UploadJob.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if not candidate:
            db.session.rollback()
            return None
        claimed_status = "verifying" if candidate.status == "processing" else "uploading"
        claimed = UploadJob.query.filter(
            UploadJob.id == candidate.id,
            UploadJob.status == candidate.status,
            UploadJob.run_at <= now,
        ).update({
            UploadJob.status: claimed_status,
            UploadJob.locked_at: now,
            UploadJob.lease_expires_at: now + timedelta(seconds=current_app.config["JOB_LEASE_SECONDS"]),
            UploadJob.worker_id: worker_id,
        }, synchronize_session=False)
        db.session.commit()
        if claimed:
            job = db.session.get(UploadJob, candidate.id)
            break
    if job is None:
        return None
    draft = db.session.get(VideoDraft, job.draft_id)
    if not draft:
        job.status = "failed"
        job.last_error = "Draft no longer exists"
        db.session.commit()
        return None
    draft.status = job.status
    log(job, "claimed", f"Job claimed by worker {worker_id}")
    db.session.commit()
    return job


def _extend_lease(job):
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=current_app.config["JOB_LEASE_SECONDS"])


def _update_batch(job):
    if not job.batch_id:
        return
    batch = db.session.get(BatchJob, job.batch_id)
    if not batch:
        return
    statuses = [status for (status,) in db.session.query(UploadJob.status).filter_by(batch_id=batch.id).all()]
    if statuses and all(value == "uploaded" for value in statuses):
        batch.status = "completed"
    elif all(value in {"uploaded", "failed", "cancelled"} for value in statuses):
        batch.status = "completed_with_errors"
    elif any(value in {"uploading", "processing", "verifying"} for value in statuses):
        batch.status = "running"


def _schedule_retry(job, draft, error):
    job.retry_count += 1
    job.last_error = str(error)[:1000]
    if error.recoverable and job.retry_count <= job.max_retries:
        job.status = draft.status = "retry_pending" if not draft.youtube_video_id else "processing"
        job.run_at = datetime.now(timezone.utc) + timedelta(minutes=min(30, 2 ** job.retry_count))
        log(job, "retry_scheduled", str(error), "warning", {"code": error.code})
    else:
        job.status = draft.status = "failed"
        log(job, "failed", str(error), "error", {"code": error.code})


def _verify(job, draft):
    state, error = video_processing_state(draft.youtube_video_id, user_id=draft.user_id)
    now = datetime.now(timezone.utc)
    job.processing_status = state
    job.processing_checked_at = now
    job.verification_attempts += 1
    if state == "succeeded":
        job.status = draft.status = "uploaded"
        job.progress = 100
        job.completed_at = now
        job.last_error = None
        log(job, "verified", "YouTube confirmed video processing succeeded", details={"video_id": draft.youtube_video_id})
        record_audit("upload_job.verified", "upload_job", job.id, actor="worker", details={"video_id": draft.youtube_video_id})
    elif state == "failed":
        job.status = draft.status = "failed"
        job.last_error = error
        log(job, "processing_failed", error, "error")
    else:
        job.status = draft.status = "processing"
        job.run_at = now + timedelta(seconds=current_app.config["JOB_VERIFY_SECONDS"])
        log(job, "processing", "YouTube is still processing the uploaded video")


def process_job(job):
    draft = db.session.get(VideoDraft, job.draft_id)
    if not draft:
        job.status, job.last_error = "failed", "Draft no longer exists"
        db.session.commit()
        return

    def progress(value):
        job.progress = value
        _extend_lease(job)
        db.session.commit()

    def save_session(uri):
        if not job.upload_session_uri:
            job.upload_session_uri = encrypt_token(uri).decode("ascii")
            _extend_lease(job)
            db.session.commit()

    def save_postprocess(state):
        job.postprocess_json = json.dumps(state, separators=(",", ":"), sort_keys=True)
        _extend_lease(job)
        db.session.commit()

    try:
        if not draft.youtube_video_id:
            response = upload_video(
                draft,
                progress_callback=progress,
                session_callback=save_session,
                resumable_uri=decrypt_token(job.upload_session_uri.encode("ascii")) if job.upload_session_uri else None,
            )
            draft.youtube_video_id = response["id"]
            draft.youtube_url = f"https://www.youtube.com/watch?v={response['id']}"
            draft.upload_response_json = json.dumps(response, separators=(",", ":"))
            job.youtube_video_id = response["id"]
            job.upload_session_uri = None
            job.processing_status = "processing"
            job.status = draft.status = "processing"
            job.progress = 99
            log(job, "uploaded_bytes", "YouTube accepted the video bytes", details={"video_id": response["id"]})
            db.session.commit()

        state = json.loads(job.postprocess_json or "{}")
        state, warnings = postprocess_video(draft, state, save_postprocess)
        job.postprocess_json = json.dumps(state, separators=(",", ":"), sort_keys=True)
        for warning in warnings:
            log(job, "post_upload_warning", warning, "warning")
        _verify(job, draft)
        job.worker_id = None
        job.lease_expires_at = None
        _update_batch(job)
        db.session.commit()
    except YouTubeError as exc:
        _schedule_retry(job, draft, exc)
        job.worker_id = None
        job.lease_expires_at = None
        _update_batch(job)
        db.session.commit()
    except Exception as exc:
        current_app.logger.exception("Unexpected worker failure for job %s", job.id)
        db.session.rollback()
        job = db.session.get(UploadJob, job.id)
        draft = db.session.get(VideoDraft, job.draft_id)
        error = YouTubeError(
            "Unexpected worker failure",
            recoverable=bool(job.upload_session_uri or draft.youtube_video_id),
            code=type(exc).__name__,
        )
        _schedule_retry(job, draft, error)
        job.worker_id = None
        job.lease_expires_at = None
        _update_batch(job)
        db.session.commit()
