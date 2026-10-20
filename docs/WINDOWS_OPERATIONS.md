# Windows local operations

StudioPilot's Windows launcher runs the API and worker on loopback only. It does not start a public tunnel. Public production traffic belongs on the approved Hetzner deployment behind its configured HTTPS proxy.

## Set up

Run the setup script from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup.ps1
```

Setup accepts Python 3.13 through 3.15 and Node.js 24.22 LTS or 26.12 Current. It prepares the backend environment, builds the interface, and applies database migrations.

## Start, inspect, and stop

```powershell
.\scripts\windows\start.ps1 -OpenBrowser
.\scripts\windows\doctor.ps1
.\scripts\windows\stop.ps1
```

The local application is available at `http://127.0.0.1:5000` by default. Set `-Port` to use another local port. Do not bind the desktop launcher to a public interface.

## OAuth

For local development, register `http://127.0.0.1:5000/api/auth/callback`. For production, register the exact HTTPS callback on the Hetzner domain and keep `PUBLIC_BASE_URL`, `FRONTEND_URL`, and `CORS_ORIGINS` aligned with that origin.
