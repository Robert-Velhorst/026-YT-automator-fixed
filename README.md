# StudioPilot — YouTube Automator

StudioPilot is a full-stack dashboard for preparing and publishing YouTube videos. It stores every video as a durable draft, supports optional AI metadata and transcription, creates thumbnail candidates, manages playlists, and sends immediate or scheduled uploads through a database-backed worker. A video is marked `uploaded` only after the official YouTube Data API returns a video ID.

## Architecture

- `frontend/`: React 18, TypeScript, Vite dashboard and typed API client.
- `backend/`: Flask API, SQLAlchemy models, Flask-Migrate migrations, Google OAuth, OpenAI services, and durable worker.
- SQLite is the local default. Set a PostgreSQL `DATABASE_URL` in production.
- Uploaded video and generated thumbnail files use local disk by default. Production deployments with more than one host must mount shared durable storage or replace this storage adapter.
- The worker claims due jobs from the database. SQLite is appropriate for one worker; PostgreSQL is required for reliable multi-worker row locking.

## Local setup

Prerequisites: Python 3.11–3.13 with `venv`, Node.js 20+, npm, and optionally FFmpeg for preparing audio outside the app.

```bash
git clone https://github.com/Noodzakelijk-Online/026-YT-automator-fixed.git
cd 026-YT-automator-fixed
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
cd backend
flask --app app db upgrade
flask --app app run --debug
```

In a second terminal:

```bash
cd frontend
cp .env.example .env
npm ci
npm run dev
```

Vite runs at `http://localhost:8080`; Flask runs at `http://localhost:5000`.

## Worker and scheduling

The API only queues work. Run the worker separately:

```bash
cd backend
../.venv/bin/python worker.py
```

For a one-shot scheduler invocation use `WORKER_ONCE=1 python worker.py`. Immediate jobs use the current UTC time; scheduled jobs persist their UTC `run_at` and become eligible when due. Cancelling is only safe before a worker claims the job. Recoverable YouTube 429/5xx failures use exponential backoff and the configured retry limit.

YouTube's native scheduled-publication behavior is not used: StudioPilot waits locally and then starts the API upload. Large videos therefore begin uploading at the requested time and publish when the upload completes. Keep the worker online and use `private` if editorial review on YouTube is required.

## Environment variables

See [`.env.example`](.env.example) and [`backend/.env.example`](backend/.env.example).

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Long random Flask session secret |
| `DATABASE_URL` | SQLAlchemy URL; SQLite locally, PostgreSQL in production |
| `GOOGLE_CLIENT_SECRETS_FILE` | Absolute path to an uncommitted OAuth web-client JSON |
| `TOKEN_ENCRYPTION_KEY` | Fernet key used to encrypt OAuth credentials at rest |
| `OPENAI_API_KEY` | Optional metadata and Whisper credential |
| `OPENAI_MODEL` | Metadata model, default `gpt-4o-mini` |
| `UPLOAD_FOLDER` / `GENERATED_FOLDER` | Durable media locations |
| `MAX_CONTENT_LENGTH` | Maximum incoming video bytes |
| `FRONTEND_URL` | OAuth success destination |
| `CORS_ORIGINS` | Comma-separated exact browser origins |
| `JOB_MAX_RETRIES` | Recoverable upload retry ceiling |
| `VITE_API_URL` | Required browser-visible API base URL, including `/api` |

Generate a token-encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Changing that key makes stored Google credentials unreadable; keep it in a production secret manager and back it up securely.

## Google OAuth and YouTube Data API

1. Create a Google Cloud project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen. Add test users while the app is in testing mode.
3. Create an OAuth 2.0 **Web application** client.
4. Add `http://localhost:5000/api/auth/callback` as a local authorized redirect URI. Production must use the exact HTTPS API origin plus `/api/auth/callback`.
5. Download the client JSON outside the repository and set `GOOGLE_CLIENT_SECRETS_FILE`.
6. Set `TOKEN_ENCRYPTION_KEY`, start the API, then use Settings → Connect with Google.

Scopes requested:

- `youtube.upload` — upload videos.
- `youtube.readonly` — read channel, playlists, and categories.
- `youtube.force-ssl` — create playlists, set thumbnails, and add playlist items.

Google may require app verification before external production users can grant these sensitive scopes. YouTube quota is finite; uploads have a substantial quota cost. The UI shows quota and authorization failures as real job failures.

## AI metadata and transcription

AI is optional. Without `OPENAI_API_KEY`, metadata generation returns a deterministic editable fallback and clearly marks its source as `fallback`. With a key, the provider returns title alternatives, description, summary, tags, hashtags, SEO keywords, category and playlist suggestions, chapters, a pinned comment, and social copy. YouTube field limits are checked again when a draft is saved.

Transcription uses OpenAI Whisper when configured. The hosted transcription request has a 25 MB file limit; large videos should have audio extracted and compressed before integrating a production chunking adapter. A failed or unavailable transcript never blocks manual metadata editing or upload. Users can paste and edit transcripts directly.

## Thumbnails and playlists

Generated thumbnails use Pillow templates; custom JPG/PNG upload and selection are supported by the API. The selected thumbnail is uploaded after the video. A YouTube thumbnail permission/error is logged as a warning and does not falsify or roll back a successful video upload.

Playlists and assignable categories come from the connected channel through the official API. Playlist assignment runs after upload. Its failure is recorded separately because the YouTube video already exists at that point.

## Batch workflow

Upload each file to create an independently editable draft. Review metadata, transcript and thumbnail for every item. The `POST /api/batch-jobs` contract accepts `draft_ids`, creates one job per video, and tracks each outcome separately. Failed jobs can be retried individually; exact file checksums and active-job checks prevent accidental duplicates.

## Tests and quality gates

```bash
cd backend
../.venv/bin/pytest -q
flask --app app db upgrade

cd ../frontend
npm ci
npm run build       # includes TypeScript project build
npm run lint
```

GitHub Actions executes these gates on pushes and pull requests. Tests cover health/readiness, auth truthfulness, validation/error contracts, drafts, no-key metadata fallback, job states, and mocked playlist/YouTube services.

## Production deployment

Use HTTPS for both sites, a strong `SECRET_KEY`, a stable `TOKEN_ENCRYPTION_KEY`, PostgreSQL, shared durable media storage, exact CORS origins, and a secret manager. Run API and worker as separate long-lived processes:

```bash
gunicorn --chdir backend --workers 2 --bind 0.0.0.0:5000 app:app
python backend/worker.py
```

Run `flask --app backend/app.py db upgrade` once during release. Build the frontend with `npm --prefix frontend ci && npm --prefix frontend run build`, then serve `frontend/dist` through a CDN/static host. The included Compose file is a single-host starting point, not a high-availability design.

### Hetzner production target

Hetzner is the production target. The included Compose file is a single-host starting point, not a completed or accepted Hetzner deployment. Follow `DEPLOYMENT_TARGET.md` and the deployment guide before any production cutover. Inventory and preserve the database and uploaded files, provision secrets outside Git, configure Google OAuth callbacks and exact HTTPS origins, and document backups, health monitoring, and rollback.

Set `VITE_API_URL=https://YOUR_API_HOST/api` in the frontend build environment; Vite embeds it at build time. Do not use `localhost` in a production build or the old Create React App name `REACT_APP_API_URL`. Set backend `CORS_ORIGINS` to the exact public frontend origin, and verify `https://YOUR_API_HOST/api/health` after staging.

## API overview

- Health/config: `GET /api/health`, `/api/readiness`, `/api/settings`
- OAuth: `GET /api/auth/status`, `/login`, `/callback`, `/channel`; `POST /refresh`, `/logout`
- Drafts: `POST/GET /api/drafts`, `GET/PATCH /api/drafts/:id`
- Preparation: metadata, transcript, and thumbnail subroutes under `/api/drafts/:id`
- YouTube data: `/api/playlists`, `/api/playlists/categories`
- Jobs: create under a draft, list/get, retry/cancel, and `POST /api/batch-jobs`
- History: `GET /api/history`

Errors consistently return `{ "error": { "code", "message", "details", "request_id" } }`.

## Security notes and limitations

- OAuth client files, encrypted tokens, databases, uploads, generated media, logs, and local environment files are ignored by Git.
- This is a single-operator/local-user application today; production multi-tenant use requires an external identity provider and per-request ownership checks.
- OAuth tokens are encrypted in the database, but uploaded media is not encrypted at rest by the application. Use encrypted disks/object storage.
- Thumbnail generation currently uses graphic templates rather than decoded video-frame extraction.
- Hosted Whisper's request-size limit means long-form transcription needs a chunking/audio pipeline.
- Upload progress is worker-to-database polling, not push/WebSocket delivery.
- Resumable uploads survive transient HTTP retries inside a worker process, but a worker process restart starts a new YouTube upload session.

## Troubleshooting

- **OAuth not configured:** verify the JSON path, redirect URI, Fernet key, and consent-screen test user.
- **CORS blocked:** set the exact frontend origin, including port, in `CORS_ORIGINS`.
- **Job stays queued:** run `worker.py` with the same database and media volumes as the API.
- **Quota exceeded:** wait for quota reset or request quota; retry only after quota is available.
- **Token cannot be decrypted:** restore the original `TOKEN_ENCRYPTION_KEY`, then reconnect if necessary.
- **SQLite locked:** stop extra workers or move to PostgreSQL.

## Roadmap

Multi-user authorization, object-storage adapters, chunked transcription, extracted video-frame thumbnails, worker heartbeats/stale-lock recovery, and WebSocket job events are the next production scaling steps.
