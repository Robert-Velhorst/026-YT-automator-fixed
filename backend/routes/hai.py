import hmac
import json
from datetime import datetime, timedelta, timezone

from dateutil.parser import isoparse
from flask import Blueprint, current_app, jsonify, request

from audit import record_audit
from errors import ApiError
from extensions import db
from models import ConnectorAction, UploadJob, VideoDraft, WorkerHeartbeat
from services.job_service import enqueue_job


hai_bp = Blueprint("hai", __name__)
hai_public_bp = Blueprint("hai_public", __name__)


def manifest_payload():
    return {
        "schema_version": "1.0",
        "connector": "studiopilot-youtube",
        "name": "StudioPilot YouTube Automator",
        "description": "Bounded YouTube draft and upload-job connector for HAI.",
        "base_path": "/api/integrations/hai",
        "authentication": {"type": "bearer", "environment": "HAI_CONNECTOR_TOKEN"},
        "capabilities": [
            {"id": "status.read", "method": "GET", "path": "/status", "effect": "read"},
            {"id": "drafts.read", "method": "GET", "path": "/drafts", "effect": "read"},
            {"id": "jobs.read", "method": "GET", "path": "/jobs", "effect": "read"},
            {"id": "upload.queue", "method": "POST", "path": "/jobs", "effect": "external", "approval_required": True},
        ],
        "required_mutation_headers": [
            "Idempotency-Key",
            "X-HAI-Task-ID",
            "X-HAI-Approval-Source",
            "X-HAI-Approval-Binding-Digest",
        ],
        "authority": "HAI may inspect bounded state and queue an operator-approved job. StudioPilot and its worker remain authoritative for provider execution and verification.",
    }


@hai_public_bp.get("/.well-known/hai-connector.json")
def well_known_manifest():
    return jsonify(manifest_payload())


@hai_bp.get("/manifest")
def manifest():
    return jsonify(manifest_payload())


def require_hai_token():
    if not current_app.config.get("HAI_CONNECTOR_ENABLED"):
        raise ApiError("HAI connector is disabled", 404, "connector_disabled")
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    expected = current_app.config.get("HAI_CONNECTOR_TOKEN", "")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise ApiError("Valid HAI connector authorization is required", 401, "connector_authentication_required")


@hai_bp.before_request
def protect_hai_routes():
    if request.endpoint != "hai.manifest":
        require_hai_token()


@hai_bp.get("/status")
def status():
    active_worker_cutoff = datetime.now(timezone.utc) - timedelta(seconds=current_app.config["STALE_WORKER_SECONDS"])
    counts = {
        "drafts": VideoDraft.query.count(),
        "active_jobs": UploadJob.query.filter(UploadJob.status.in_(["queued", "scheduled", "uploading", "retry_pending", "processing", "verifying"])).count(),
        "failed_jobs": UploadJob.query.filter_by(status="failed").count(),
        "workers": WorkerHeartbeat.query.filter(WorkerHeartbeat.last_seen_at >= active_worker_cutoff).count(),
    }
    return jsonify({"status": "ready", "counts": counts, "server_time": datetime.now(timezone.utc).isoformat()})


@hai_bp.get("/drafts")
def drafts():
    limit = min(max(request.args.get("limit", type=int) or 50, 1), 100)
    values = VideoDraft.query.order_by(VideoDraft.updated_at.desc()).limit(limit).all()
    return jsonify({"drafts": [{
        "id": value.id,
        "status": value.status,
        "title": value.title,
        "filename": value.filename,
        "privacy_status": value.privacy_status,
        "scheduled_at": value.scheduled_at.isoformat() if value.scheduled_at else None,
        "youtube_video_id": value.youtube_video_id,
        "updated_at": value.updated_at.isoformat(),
    } for value in values]})


@hai_bp.get("/jobs")
def jobs():
    limit = min(max(request.args.get("limit", type=int) or 50, 1), 100)
    values = UploadJob.query.order_by(UploadJob.updated_at.desc()).limit(limit).all()
    return jsonify({"jobs": [value.to_dict() for value in values]})


def _approval_headers():
    values = {
        "idempotency_key": request.headers.get("Idempotency-Key", "").strip(),
        "task_id": request.headers.get("X-HAI-Task-ID", "").strip(),
        "approval_source": request.headers.get("X-HAI-Approval-Source", "").strip(),
        "approval_digest": request.headers.get("X-HAI-Approval-Binding-Digest", "").strip(),
    }
    if not 8 <= len(values["idempotency_key"]) <= 100:
        raise ApiError("Idempotency-Key must contain 8 to 100 characters", 422, "approval_evidence_required")
    if not values["task_id"] or not values["approval_source"] or len(values["approval_digest"]) < 32:
        raise ApiError("HAI task and approval binding headers are required", 422, "approval_evidence_required")
    return values


@hai_bp.post("/jobs")
def queue_job():
    evidence = _approval_headers()
    action_key = "hai:" + evidence["idempotency_key"]
    existing = ConnectorAction.query.filter_by(idempotency_key=action_key).first()
    if existing:
        if existing.status == "completed" and existing.response_json:
            payload = json.loads(existing.response_json)
            payload["replayed"] = True
            return jsonify(payload)
        raise ApiError("The HAI action already exists and is not complete", 409, "connector_action_conflict")

    data = request.get_json(silent=True) or {}
    draft = db.session.get(VideoDraft, str(data.get("draft_id", "")))
    if not draft:
        raise ApiError("Draft not found", 404, "not_found")
    run_at = datetime.now(timezone.utc)
    if data.get("run_at"):
        try:
            run_at = isoparse(data["run_at"])
            if run_at.tzinfo is None:
                raise ValueError("timezone required")
            run_at = run_at.astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise ApiError("run_at must be an ISO 8601 timestamp with timezone", 422, "validation_error") from exc

    action = ConnectorAction(
        connector="hai",
        idempotency_key=action_key,
        action="upload.queue",
        task_id=evidence["task_id"],
        approval_source=evidence["approval_source"],
        approval_digest=evidence["approval_digest"],
        request_json=json.dumps(data, separators=(",", ":"), sort_keys=True),
    )
    db.session.add(action)
    db.session.flush()
    try:
        job, replayed = enqueue_job(draft, run_at, idempotency_key=action_key, actor="hai", commit=False)
        payload = {"job": job.to_dict(), "connector_action_id": action.id, "replayed": replayed}
        action.status = "completed"
        action.response_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        record_audit("hai.upload_job.created", "upload_job", job.id, actor="hai", details={
            "task_id": evidence["task_id"], "approval_source": evidence["approval_source"],
        })
        db.session.commit()
        return jsonify(payload), 201
    except Exception as exc:
        db.session.rollback()
        action = ConnectorAction.query.filter_by(idempotency_key=action_key).first()
        if not action:
            action = ConnectorAction(
                connector="hai",
                idempotency_key=action_key,
                action="upload.queue",
                status="failed",
                task_id=evidence["task_id"],
                approval_source=evidence["approval_source"],
                approval_digest=evidence["approval_digest"],
                request_json=json.dumps(data, separators=(",", ":"), sort_keys=True),
            )
            db.session.add(action)
        action.status = "failed"
        action.error = type(exc).__name__
        db.session.commit()
        raise
