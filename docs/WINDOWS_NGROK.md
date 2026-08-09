# Windows 11 and ngrok

## First setup

Run `scripts\windows\setup.ps1` from PowerShell. It creates a private Python environment, installs pinned dependencies, asks for an operator password, generates independent session/encryption/HAI secrets, builds the interface, and upgrades the database. It never overwrites an existing `backend\.env`.

Node.js 25 is intentionally rejected because this project supports current LTS lines (20, 22, and 24). Install an LTS release before setup.

## Local operation

Run `studiopilot.cmd`. The launcher upgrades the database, starts Waitress on loopback, starts one worker, waits for health, and records only its own process tree in `.runtime`. If port 5000 is occupied, it selects the next free port and prints the resulting URL. Run `studiopilot.cmd stop` to stop those exact matching processes.

Logs are written under `.runtime` and excluded from Git. `studiopilot.cmd doctor` verifies the environment, build, runtime configuration, migration state, optional FFmpeg, and running API.

## Public ngrok operation

Use a stable ngrok domain for Google OAuth because the callback URL must match exactly.

```powershell
ngrok config add-authtoken YOUR_NGROK_TOKEN
powershell -ExecutionPolicy Bypass -File .\scripts\windows\start.ps1 -Public -NgrokDomain your-domain.ngrok.app -OpenBrowser
```

The launcher discovers ngrok's HTTPS URL, sets it as the frontend, CORS, and OAuth base URL for both child processes, switches to production validation, and disables local authentication bypass. Public startup is refused without an operator password hash.

Add this exact Google OAuth redirect URI:

```text
https://your-domain.ngrok.app/api/auth/callback
```

The app-level operator login protects drafts and provider controls. For a second perimeter, configure an ngrok Traffic Policy with an authentication action. Do not use a rotating ngrok URL for Google OAuth.

## Recovery

- A worker crash leaves a lease. The next worker recovers the job after `JOB_LEASE_SECONDS`.
- Before YouTube returns a video ID, the encrypted resumable session is reused.
- After an ID exists, recovery skips re-upload and continues post-processing/verification.
- If `.runtime\processes.json` remains after a machine restart, run `studiopilot.cmd stop`; missing PIDs are ignored and the state file is removed.
- Back up `backend\instance`, `backend\uploads`, `backend\generated`, and `backend\.env` together. Losing the encryption key requires reconnecting Google and invalidates any stored upload session.
