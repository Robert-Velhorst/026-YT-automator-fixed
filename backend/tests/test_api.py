import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from PIL import Image
from werkzeug.security import generate_password_hash


def create_draft(client, name="lesson.mp4", content=b"video-content"):
    response = client.post("/api/drafts", data={"video": (io.BytesIO(content), name)}, content_type="multipart/form-data")
    assert response.status_code == 201
    return response.get_json()["draft"]


def test_health_and_readiness(client):
    assert client.get("/api/health").get_json()["status"] == "healthy"
    response = client.get("/api/readiness")
    assert response.status_code == 200
    assert response.get_json()["checks"]["database"] is True


def test_cors_allows_configured_origin_only(client):
    allowed = client.get("/api/health", headers={"Origin": "http://localhost"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost"

    blocked = client.get("/api/health", headers={"Origin": "https://untrusted.example"})
    assert "Access-Control-Allow-Origin" not in blocked.headers


def test_auth_status_is_truthful(client):
    assert client.get("/api/auth/status").get_json() == {"authenticated": False, "channel": None}


def test_video_validation_and_error_contract(client):
    response = client.post("/api/videos/validate", data={"video": (io.BytesIO(b"bad"), "bad.txt")}, content_type="multipart/form-data")
    assert response.status_code == 415
    assert response.get_json()["error"]["code"] == "unsupported_media_type"


def test_draft_create_update_and_duplicate_prevention(client):
    draft = create_draft(client)
    response = client.patch(f"/api/drafts/{draft['id']}", json={"title": "A useful lesson", "privacy_status": "unlisted", "tags": ["lesson"]})
    assert response.get_json()["draft"]["manually_edited"] is True
    duplicate = client.post("/api/drafts", data={"video": (io.BytesIO(b"video-content"), "copy.mp4")}, content_type="multipart/form-data")
    assert duplicate.status_code == 409
    assert duplicate.get_json()["error"]["code"] == "duplicate_video"


def test_draft_rejects_non_array_tags(client):
    draft = create_draft(client)
    response = client.patch(f"/api/drafts/{draft['id']}", json={"tags": "not-an-array"})
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"


def test_custom_thumbnail_is_bounded_and_validated(client):
    draft = create_draft(client)
    small = io.BytesIO()
    Image.new("RGB", (100, 100), "red").save(small, "JPEG")
    small.seek(0)
    response = client.post(
        f"/api/drafts/{draft['id']}/thumbnails",
        data={"thumbnail": (small, "small.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert list(Path(client.application.config["GENERATED_FOLDER"]).iterdir()) == []

    valid = io.BytesIO()
    Image.new("RGB", (640, 360), "blue").save(valid, "JPEG")
    valid.seek(0)
    response = client.post(
        f"/api/drafts/{draft['id']}/thumbnails",
        data={"thumbnail": (valid, "valid.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201


def test_metadata_local_template_without_ai_key(client):
    draft = create_draft(client)
    response = client.post(f"/api/drafts/{draft['id']}/metadata/generate", json={"context": "Practical Flask deployment tutorial"})
    assert response.status_code == 200
    assert response.get_json()["draft"]["metadata_source"] == "local_template"


def test_job_create_status_cancel_and_retry_rules(client):
    draft = create_draft(client)
    response = client.post(f"/api/drafts/{draft['id']}/jobs", json={})
    assert response.status_code == 201
    job = response.get_json()["job"]
    assert client.get(f"/api/jobs/{job['id']}").get_json()["job"]["status"] == "queued"
    assert client.post(f"/api/jobs/{job['id']}/cancel").get_json()["job"]["status"] == "cancelled"
    retry = client.post(f"/api/jobs/{job['id']}/retry")
    assert retry.status_code == 409


def test_youtube_upload_service_with_mock(app, mocker):
    from models import VideoDraft, User
    from extensions import db
    from services import youtube_service
    with app.app_context():
        user = User(display_name="test"); db.session.add(user); db.session.flush()
        draft = VideoDraft(user_id=user.id, filename="a.mp4", file_path=__file__, file_size=1, checksum="x", title="Title")
        db.session.add(draft); db.session.commit()
        request = mocker.Mock(); request.next_chunk.return_value = (None, {"id": "real-id"})
        videos = mocker.Mock(); videos.insert.return_value = request
        youtube = mocker.Mock(); youtube.videos.return_value = videos
        service = mocker.patch.object(youtube_service, "service_for", return_value=youtube)
        response = youtube_service.upload_video(draft)
        assert response["id"] == "real-id"
        service.assert_called_once_with(user_id=draft.user_id)


def test_playlist_service_with_mock(client, mocker):
    fake = mocker.Mock()
    fake.playlists.return_value.list.return_value.execute.return_value = {"items": [{"id": "p1", "snippet": {"title": "Uploads"}, "status": {"privacyStatus": "private"}, "contentDetails": {"itemCount": 2}}]}
    mocker.patch("routes.playlists.service_for", return_value=fake)
    response = client.get("/api/playlists")
    assert response.status_code == 200
    assert response.get_json()["playlists"][0]["id"] == "p1"


def test_dashboard_combines_runtime_state(client):
    draft = create_draft(client)
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.get_json()
    assert body["drafts"][0]["id"] == draft["id"]
    assert body["jobs"] == []
    assert body["checks"]["database"] is True
    assert body["auth"]["authenticated"] is False


def test_job_idempotency_key_replays_same_job(client):
    draft = create_draft(client)
    headers = {"Idempotency-Key": "operator-job-123"}
    first = client.post(f"/api/drafts/{draft['id']}/jobs", json={}, headers=headers)
    second = client.post(f"/api/drafts/{draft['id']}/jobs", json={}, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["replayed"] is True
    assert first.get_json()["job"]["id"] == second.get_json()["job"]["id"]


def test_hai_connector_requires_token_approval_and_is_idempotent(client, app):
    app.config.update(HAI_CONNECTOR_ENABLED=True, HAI_CONNECTOR_TOKEN="h" * 32)
    draft = create_draft(client)
    assert client.get("/api/integrations/hai/status").status_code == 401
    auth = {"Authorization": "Bearer " + "h" * 32}
    assert client.get("/api/integrations/hai/status", headers=auth).status_code == 200
    denied = client.post("/api/integrations/hai/jobs", json={"draft_id": draft["id"]}, headers=auth)
    assert denied.status_code == 422
    headers = {
        **auth,
        "Idempotency-Key": "hai-action-123",
        "X-HAI-Task-ID": "task-123",
        "X-HAI-Approval-Source": "approval-123",
        "X-HAI-Approval-Binding-Digest": "d" * 64,
    }
    first = client.post("/api/integrations/hai/jobs", json={"draft_id": draft["id"]}, headers=headers)
    replay = client.post("/api/integrations/hai/jobs", json={"draft_id": draft["id"]}, headers=headers)
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.get_json()["replayed"] is True
    assert replay.get_json()["job"]["id"] == first.get_json()["job"]["id"]


def test_stale_upload_lease_is_recovered(app):
    from extensions import db
    from models import UploadJob, User, VideoDraft
    from services.job_service import recover_stale_jobs

    with app.app_context():
        owner = User(display_name="test")
        db.session.add(owner)
        db.session.flush()
        draft = VideoDraft(user_id=owner.id, filename="a.mp4", file_path=__file__, file_size=1, checksum="lease", title="Title", status="uploading")
        db.session.add(draft)
        db.session.flush()
        job = UploadJob(draft_id=draft.id, status="uploading", run_at=datetime.now(timezone.utc),
                        lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1), idempotency_key="lease-job")
        db.session.add(job)
        db.session.commit()
        assert recover_stale_jobs() == 1
        assert db.session.get(UploadJob, job.id).status == "retry_pending"


def test_worker_claim_is_exclusive(app):
    from extensions import db
    from models import UploadJob, User, VideoDraft
    from services.job_service import claim_next_job

    with app.app_context():
        owner = User(display_name="test")
        db.session.add(owner)
        db.session.flush()
        draft = VideoDraft(user_id=owner.id, filename="a.mp4", file_path=__file__, file_size=1,
                           checksum="exclusive", title="Title")
        db.session.add(draft)
        db.session.flush()
        job = UploadJob(draft_id=draft.id, status="queued", run_at=datetime.now(timezone.utc),
                        idempotency_key="exclusive-job")
        db.session.add(job)
        db.session.commit()
        claimed = claim_next_job("worker-one")
        assert claimed.id == job.id
        assert claimed.worker_id == "worker-one"
        assert claim_next_job("worker-two") is None


def test_worker_waits_for_youtube_processing_before_success(app, mocker):
    from extensions import db
    from models import UploadJob, User, VideoDraft
    from services import job_service

    with app.app_context():
        owner = User(display_name="test")
        db.session.add(owner)
        db.session.flush()
        draft = VideoDraft(user_id=owner.id, filename="a.mp4", file_path=__file__, file_size=1, checksum="verify", title="Title")
        db.session.add(draft)
        db.session.flush()
        job = UploadJob(draft_id=draft.id, status="uploading", run_at=datetime.now(timezone.utc), idempotency_key="verify-job")
        db.session.add(job)
        db.session.commit()
        mocker.patch.object(job_service, "upload_video", return_value={"id": "youtube-id"})
        mocker.patch.object(job_service, "postprocess_video", return_value=({}, []))
        state = mocker.patch.object(job_service, "video_processing_state", side_effect=[("processing", None), ("succeeded", None)])
        job_service.process_job(job)
        assert job.status == "processing"
        assert draft.status == "processing"
        job.status = "verifying"
        job_service.process_job(job)
        assert state.call_count == 2
        assert job.status == "uploaded"
        assert draft.youtube_video_id == "youtube-id"


def test_post_upload_exception_retries_verification_without_reupload(app, mocker):
    from extensions import db
    from models import UploadJob, User, VideoDraft
    from services import job_service

    with app.app_context():
        owner = User(display_name="test")
        db.session.add(owner)
        db.session.flush()
        draft = VideoDraft(user_id=owner.id, filename="a.mp4", file_path=__file__, file_size=1,
                           checksum="post-upload-retry", title="Title")
        db.session.add(draft)
        db.session.flush()
        job = UploadJob(draft_id=draft.id, status="uploading", run_at=datetime.now(timezone.utc),
                        idempotency_key="post-upload-retry-job")
        db.session.add(job)
        db.session.commit()
        upload = mocker.patch.object(job_service, "upload_video", return_value={"id": "accepted-id"})
        mocker.patch.object(job_service, "postprocess_video", side_effect=RuntimeError("temporary local failure"))
        job_service.process_job(job)
        assert upload.call_count == 1
        assert draft.youtube_video_id == "accepted-id"
        assert job.status == "processing"
        assert job.retry_count == 1


def test_resumable_upload_session_is_encrypted_at_rest(app, mocker):
    from extensions import db
    from models import UploadJob, User, VideoDraft
    from security import decrypt_token
    from services import job_service

    with app.app_context():
        app.config["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        owner = User(display_name="test")
        db.session.add(owner)
        db.session.flush()
        draft = VideoDraft(user_id=owner.id, filename="a.mp4", file_path=__file__, file_size=1,
                           checksum="encrypted-session", title="Title")
        db.session.add(draft)
        db.session.flush()
        job = UploadJob(draft_id=draft.id, status="uploading", run_at=datetime.now(timezone.utc),
                        idempotency_key="encrypted-session-job")
        db.session.add(job)
        db.session.commit()
        session_uri = "https://upload.youtube.example/resumable/secret"

        def upload(_draft, progress_callback, session_callback, resumable_uri):
            assert resumable_uri is None
            session_callback(session_uri)
            assert job.upload_session_uri != session_uri
            assert decrypt_token(job.upload_session_uri.encode("ascii")) == session_uri
            progress_callback(50)
            return {"id": "youtube-encrypted-id"}

        mocker.patch.object(job_service, "upload_video", side_effect=upload)
        mocker.patch.object(job_service, "postprocess_video", return_value=({}, []))
        mocker.patch.object(job_service, "video_processing_state", return_value=("processing", None))
        job_service.process_job(job)
        assert job.upload_session_uri is None


def test_public_mode_requires_operator_login(tmp_path):
    from app import create_app
    from extensions import db

    class PublicConfig:
        TESTING = True
        APP_ENV = "production"
        SECRET_KEY = "s" * 48
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        GENERATED_FOLDER = str(tmp_path / "generated")
        PUBLIC_BASE_URL = "https://studio.example"
        FRONTEND_URL = "https://studio.example"
        CORS_ORIGINS = ["https://studio.example"]
        LOCAL_AUTH_BYPASS = False
        OPERATOR_PASSWORD_HASH = generate_password_hash("correct horse battery staple")
        GOOGLE_CLIENT_SECRETS_FILE = ""
        TOKEN_ENCRYPTION_KEY = ""
        HAI_CONNECTOR_ENABLED = False
        JOB_LEASE_SECONDS = 300

    public_app = create_app(PublicConfig)
    with public_app.app_context():
        db.create_all()
        public_client = public_app.test_client()
        assert public_client.get("/api/dashboard").status_code == 401
        blocked = public_client.post(
            "/api/operator/login",
            json={"password": "correct horse battery staple"},
            headers={"Origin": "https://evil.example"},
        )
        assert blocked.status_code == 403
        bad = public_client.post(
            "/api/operator/login",
            json={"password": "incorrect"},
            headers={"Origin": "https://studio.example"},
        )
        assert bad.status_code == 401
        good = public_client.post(
            "/api/operator/login",
            json={"password": "correct horse battery staple"},
            headers={"Origin": "https://studio.example"},
        )
        assert good.status_code == 200
        assert public_client.get("/api/dashboard").status_code == 200
        assert public_client.post(
            "/api/auth/logout", headers={"Origin": "https://studio.example"}
        ).status_code == 200
        assert public_client.get("/api/dashboard").status_code == 200
        db.session.remove()
        db.drop_all()
