"""Durable worker, verification, audit, and HAI connector state.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("upload_job") as batch:
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("idempotency_key", sa.String(128)))
        batch.add_column(sa.Column("upload_session_uri", sa.Text))
        batch.add_column(sa.Column("youtube_video_id", sa.String(64)))
        batch.add_column(sa.Column("processing_status", sa.String(32)))
        batch.add_column(sa.Column("processing_checked_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("verification_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("postprocess_json", sa.Text(), nullable=False, server_default="{}"))
        batch.create_index("ix_upload_job_lease_expires_at", ["lease_expires_at"])
        batch.create_index("ix_upload_job_idempotency_key", ["idempotency_key"], unique=True)
        batch.create_index("ix_upload_job_youtube_video_id", ["youtube_video_id"])

    op.execute("UPDATE upload_job SET idempotency_key = id WHERE idempotency_key IS NULL")

    op.create_table(
        "worker_heartbeat",
        sa.Column("worker_id", sa.String(128), primary_key=True),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("process_id", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_job_id", sa.String(36), sa.ForeignKey("upload_job.id")),
    )
    op.create_index("ix_worker_heartbeat_last_seen_at", "worker_heartbeat", ["last_seen_at"])
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", sa.String(128)),
        sa.Column("request_id", sa.String(36)),
        sa.Column("details_json", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("actor", "action", "target_id", "request_id", "created_at"):
        op.create_index(f"ix_audit_event_{name}", "audit_event", [name])
    op.create_table(
        "connector_action",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connector", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(128)),
        sa.Column("approval_source", sa.String(255)),
        sa.Column("approval_digest", sa.String(128)),
        sa.Column("request_json", sa.Text, nullable=False),
        sa.Column("response_json", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_connector_action_connector", "connector_action", ["connector"])
    op.create_index("ix_connector_action_idempotency_key", "connector_action", ["idempotency_key"], unique=True)


def downgrade():
    op.drop_table("connector_action")
    op.drop_table("audit_event")
    op.drop_table("worker_heartbeat")
    with op.batch_alter_table("upload_job") as batch:
        batch.drop_index("ix_upload_job_youtube_video_id")
        batch.drop_index("ix_upload_job_idempotency_key")
        batch.drop_index("ix_upload_job_lease_expires_at")
        for column in (
            "postprocess_json",
            "verification_attempts",
            "processing_checked_at",
            "processing_status",
            "youtube_video_id",
            "upload_session_uri",
            "idempotency_key",
            "lease_expires_at",
        ):
            batch.drop_column(column)
