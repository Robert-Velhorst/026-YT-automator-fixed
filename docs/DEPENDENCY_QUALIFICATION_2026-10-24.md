# Python and runtime qualification — 24 October 2026

This draft retains the Node security changes and updates SQLAlchemy 2.1.6,
Alembic 1.20.1, OpenAI 3.37.0, python-dateutil 3.0.0 and pytest-mock 3.17.0.
The default branch and provider/deployment state are unchanged by preparation.

## Dateutil major upgrade

The application imports `isoparse` in the core and HAI routes. Dateutil 3 rewrites
time-zone file behavior, uses the system/`tzdata` time-zone database and changes
offset selection for nonexistent local times. These are material integration
boundaries; current-head route/scheduling checks must pass. No live calendar or
scheduled publication is exercised or claimed by metadata resolution.

Primary source: [dateutil 3.0.0 release](https://github.com/dateutil/dateutil/releases/tag/3.0.0).

## Hash-locked installations

uv 0.13.5 generates universal, hash-enforced graphs with source builds disabled
during resolution:

- `backend/requirements-py313.lock`: Python 3.13 compatibility, 71 package pins.
- `backend/requirements-py314.lock`: Python 3.14 compatibility, 70 package pins.
- `backend/requirements-py315.lock`: Python 3.15.1 production target, 70 package pins.

The existing Linux matrix retains its Python 3.13 and 3.15 coverage at current
patches 3.13.17 and 3.15.1; Windows uses 3.15.1. Python 3.14 is supported by its
lock and setup policy, but has no hosted application matrix result in this PR.
No application test cases are added, removed or relaxed.

Installation in CI, the production Dockerfile and Windows setup requires both
hashes and wheels and checks dependency consistency. Windows setup rejects
prerelease Python, outdated supported Python patches and outdated Node patches,
and no longer accepts unqualified future Node majors. Setup was not invoked
locally, so no operator environment, credentials or database was changed.

All packages in each lock were audited locally with pip-audit 2.10.1 without
installation or dependency resolution: zero known vulnerabilities. Only the audit
input removes environment markers, so inactive platform-specific pins are also
queried; installation locks retain their markers and hashes. CI repeats this
check without advisory exclusions.

## Installed image and outstanding evidence

The backend base is pinned to official Python 3.15.1 slim manifest digest
`sha256:08275f764e022331c6d3e3ca55d8cce01fa4684b02111adf0445d71806fe7941`.
OS packages are refreshed through that distribution's repositories. This does
not imply all upstream native major versions are current.

CI builds the actual production image, records Python/SSL/SQLite/libpq and
installed package versions without starting the application or a database,
and scans all installed OS/Python packages at every severity. Reports remain
bound to the image ID; a metadata-only lock audit cannot qualify that image.
Current-head hosted installation, route, migration, browser/build and image
results are required before merging. CI SQLite migrations use disposable data.

SDK OpenSSL, Psycopg's bundled libpq/crypto, SQLite, OS libraries, FFmpeg,
Windows GUI behavior, real databases/backup recovery and live provider use
remain separate verification or upgrade boundaries. No live migration,
publication, merge, provider login or Hetzner deployment is claimed.

Actions are pinned to verified stable release commits: checkout 7.0.1,
setup-python 7.1.0, setup-node 7.1.0 and upload-artifact 7.0.2.

Interpreter release source: [Python downloads](https://www.python.org/downloads/).
