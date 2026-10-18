# StudioPilot

StudioPilot is a single-operator YouTube preparation and publishing workspace. It keeps videos as durable drafts, supports optional AI metadata and transcription, creates thumbnail candidates, queues immediate or scheduled uploads, resumes interrupted uploads, and waits for YouTube processing confirmation before reporting success.

## What runs

- `frontend/`: React 18 and TypeScript operator interface.
- `backend/`: Flask API, SQLAlchemy database, Google OAuth, and media services.
- `backend/worker.py`: one durable SQLite upload worker with leases, retries, heartbeats, resumable sessions, post-processing, and provider verification.
- `scripts/windows/`: guarded Windows 11 setup, start, stop, and diagnostics.
- `GET /.well-known/hai-connector.json`: HAI connector discovery contract.

The production frontend is built once and served by Flask. Browser calls use same-origin `/api`, so a single local or ngrok URL serves the complete application.

## Windows 11

Prerequisites: Python 3.11-3.13, Node.js 20.19+/22/24 LTS, and npm. FFmpeg is required only for long-video transcription. ngrok is required only for public access.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup.ps1
.\studiopilot.cmd
```

Open `http://127.0.0.1:5000`. Local loopback requests can use the configured bypass; access over ngrok always requires the operator password chosen during setup.

```powershell
.\studiopilot.cmd doctor
.\studiopilot.cmd stop
```

See [Windows and ngrok operations](docs/WINDOWS_NGROK.md).

## YouTube connection

1. Create a Google Cloud project and enable YouTube Data API v3.
2. Configure an OAuth consent screen and an OAuth Web application client.
3. Put the downloaded client JSON outside this repository and set its absolute path as `GOOGLE_CLIENT_SECRETS_FILE` in `backend/.env`.
4. Keep the generated `TOKEN_ENCRYPTION_KEY`; it encrypts OAuth credentials and resumable-upload session URLs at rest.
5. For local use, authorize `http://127.0.0.1:5000/api/auth/callback` in Google Cloud.
6. For ngrok, authorize the stable HTTPS ngrok URL plus `/api/auth/callback`, then start with that domain.

StudioPilot requests YouTube upload, read, and force-SSL scopes. Google may require consent-screen verification for external users. YouTube quota and provider authorization are external acceptance gates; the application reports them as failures rather than simulating success.

## Runtime behavior

- Video uploads stream to disk in 1 MB chunks while hashing; duplicate content is rejected.
- UI polling pauses in hidden tabs and adapts from 30 seconds idle to 3 seconds during provider work.
- One dashboard request returns drafts, jobs, account state, readiness, and worker status.
- SQLite uses WAL, foreign keys, and a busy timeout. Run one worker with SQLite. Use PostgreSQL and shared media storage before running multiple workers or hosts.
- Upload session URLs are encrypted. A stale lease recovers into upload retry or provider verification depending on whether YouTube already returned an ID.
- Thumbnail and playlist failures remain visible post-upload warnings and never erase a real provider video ID.
- A job becomes `uploaded` only after YouTube reports processing success.

## HAI connector

HAI can read bounded draft/job status and queue an already-approved upload. It cannot bypass operator review: mutations require a bearer token, idempotency key, HAI task ID, approval source, and approval-binding digest. StudioPilot remains authoritative for execution and YouTube verification.

See [HAI connector](docs/HAI_CONNECTOR.md).

## Development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
cd backend
..\.venv\Scripts\python -m flask --app app db upgrade
..\.venv\Scripts\python -m pytest -q

cd ..\frontend
npm ci
npm run typecheck
npm run lint
npm run build
```

For separate development servers, run Flask on port 5000 and Vite on port 8080. Production and Windows launch scripts use the built same-origin interface.

## Configuration

Copy [`.env.example`](.env.example) to `backend/.env`, or let the Windows setup script create it. Important controls:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Session integrity; 32+ random characters in public/production mode |
| `TOKEN_ENCRYPTION_KEY` | Stable Fernet key for OAuth and resumable sessions |
| `OPERATOR_PASSWORD_HASH` | Werkzeug password hash required for public/production mode |
| `PUBLIC_BASE_URL` | Exact stable HTTPS external origin |
| `LOCAL_AUTH_BYPASS` | Loopback-only convenience; must be `false` publicly |
| `DATABASE_URL` | SQLite locally; PostgreSQL for concurrent workers |
| `GOOGLE_CLIENT_SECRETS_FILE` | Absolute uncommitted OAuth client JSON path |
| `OPENAI_API_KEY` | Optional metadata and transcription provider key |
| `FFMPEG_PATH` | FFmpeg executable used to chunk long audio locally |
| `HAI_CONNECTOR_ENABLED` / `HAI_CONNECTOR_TOKEN` | Optional isolated HAI access |

Public and production startup fails closed when authentication, HTTPS, or secrets are unsafe.

## Containers

`Dockerfile.backend` builds the frontend and backend into one non-root image. Compose binds the app to loopback by default and runs one separate worker:

```bash
# On Windows, run scripts/windows/setup.ps1 first so backend/.env contains real secrets.
docker compose up --build
```

If you create `backend/.env` manually on another platform, replace every secret placeholder with a real random value and generate a Werkzeug operator password hash before starting Compose. Do not expose the Compose port directly. Use HTTPS and set `PUBLIC_BASE_URL`, `OPERATOR_PASSWORD_HASH`, and `LOCAL_AUTH_BYPASS=false` first.

## Verification

GitHub Actions run backend tests, a fresh migration, frontend lint, and production build. Local release checks are documented in [production readiness](docs/PRODUCTION_READINESS.md).
