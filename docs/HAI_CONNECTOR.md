# HAI connector

StudioPilot exposes a narrow REST connector for a locally or remotely hosted HAI instance. Discovery is available at `GET /.well-known/hai-connector.json`.

## Enable

Set these in `backend/.env`, then restart API and worker:

```text
HAI_CONNECTOR_ENABLED=true
HAI_CONNECTOR_TOKEN=a-random-secret-containing-at-least-32-characters
```

Keep this token separate from Google and OpenAI credentials. HAI never receives provider tokens.

## Read operations

All data routes require `Authorization: Bearer <HAI_CONNECTOR_TOKEN>`:

- `GET /api/integrations/hai/status`
- `GET /api/integrations/hai/drafts?limit=50`
- `GET /api/integrations/hai/jobs?limit=50`

Responses are bounded to 100 records and omit file paths, OAuth material, transcripts, and media.

## Approved queue operation

`POST /api/integrations/hai/jobs` accepts `draft_id` and optional timezone-aware `run_at`. It requires:

```text
Authorization: Bearer ...
Idempotency-Key: unique-action-key
X-HAI-Task-ID: originating-task-id
X-HAI-Approval-Source: approval-record-reference
X-HAI-Approval-Binding-Digest: digest-binding-approval-to-this-action
```

The action and approval evidence are persisted before provider execution. Replaying a completed idempotency key returns the original job. Reusing a key for an incomplete or failed action is rejected. HAI may queue only an existing draft that passes the same readiness and duplicate-job checks as the operator UI.

Provider execution remains asynchronous. HAI should poll the job route and treat only `uploaded` as verified success. `processing`, `verifying`, `retry_pending`, and `failed` are distinct real states.
