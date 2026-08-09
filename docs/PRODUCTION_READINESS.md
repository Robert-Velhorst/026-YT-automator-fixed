# Production readiness

## Implemented controls

- Same-origin built frontend and typed API client.
- Operator session authentication required for public/production operation.
- Exact-origin mutation checks, secure cookies, security headers, CSP, and no-store API responses.
- Encrypted OAuth credentials and resumable upload sessions.
- Streaming bounded uploads and thumbnail validation.
- Durable idempotent jobs, leases, stale-work recovery, heartbeats, retry backoff, post-upload state, and audit events.
- YouTube processing verification before success.
- Approval-bound, token-isolated HAI connector.
- SQLite WAL for one-host operation and PostgreSQL support for concurrent deployment.
- Windows Waitress launcher and non-root multi-stage container.

## Release gates

Run before release:

```powershell
.\.venv\Scripts\python -m pytest backend\tests -q
cd backend
..\.venv\Scripts\python -m flask --app app db upgrade
cd ..\frontend
npm ci
npm run typecheck
npm run lint
npm run build
```

Then run `scripts\windows\doctor.ps1`, start the app, and test desktop and mobile browser paths: login, draft upload, metadata editing, custom thumbnail, schedule, cancellation, HAI reads, and explicit error states.

## External acceptance gates

These cannot be proven by repository tests alone:

- Google consent-screen and YouTube scope approval.
- Exact local or stable ngrok OAuth callback registration.
- Live channel authorization and available YouTube quota.
- A real video upload plus YouTube processing completion.
- Optional OpenAI billing/access and local FFmpeg installation.
- HAI registration in the target HAI deployment.

Do not call the app provider-ready until those checks pass with owner credentials. No test or local template represents a live provider success.
