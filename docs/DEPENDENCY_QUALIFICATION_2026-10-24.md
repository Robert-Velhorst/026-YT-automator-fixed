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

### SQLite 3.54.1 source build

The qualified Alpine image at 72dbed3 reported SQLite 3.53.4. This follow-up
builds public stable SQLite 3.54.1 from the official SHA3-256-pinned source
archive. Downloads reject redirects and oversized archives; compilation occurs
only in a separate Alpine builder stage. The source profile is recorded in
`sqlite-runtime.json`.

The library retains Alpine's column metadata, secure deletion, unlock notify,
R-tree/geopoly, FTS3/4/5, session/preupdate hook, URI, DBSTAT, soundex and 250000
variable-count settings. A fresh CPython child must load the built engine at the
expected version before packaging. Its APK records the real upstream version,
source origin, binary hash and build provenance. A build-only signing key is
removed before its builder RUN completes; installation uses the public key
offline without changing global trusted keys.

Only the registered library and provenance enter the application image. CI checks
the actual CPython SQLite version, library hash and APK inventory and reuses the
same complete backend suite. No compiler, source archive, signing key, alternate
application code or dependency installation workaround enters the runtime.
Source preparation is not current-head installed-image qualification.

Sources: [SQLite downloads and checksums](https://www.sqlite.org/download.html),
[Alpine distribution features](https://raw.githubusercontent.com/alpinelinux/aports/3.24-stable/main/sqlite/APKBUILD).

The initial slim-image candidate at 410662d built and installed successfully,
but its raw scan returned 171 findings, including 48 high. The Debian package
inventory and bundled package-manager libraries were not qualified by the clean
application lock audit. Actual metadata also reported SQLite 3.46.1, Python SSL
3.5.7 and cryptography SSL 4.0.3. Those results are retained as failed evidence.

The follow-up backend base pins official Python 3.15.1 on Alpine 3.24, manifest
digest `sha256:54448f67d7c31c39e5cdd3ea2d6382395ce142806c284425f8e897d78a0465b3`.
OS packages are refreshed through that stable distribution. Pip and its bundled
ensurepip reinstaller are removed after the complete application graph is
installed and checked; runtime upgrades use rebuilt images. No scanner metadata
is edited separately and no advisory is excluded. This does not imply every
upstream native major version is current.

CI builds the actual production image, records Python/SSL/SQLite/libpq and
installed package versions without starting the application or a database,
and reuses the full existing backend suite against the exact image. The fixture
has no network or host mounts, uses a read-only root and bounded temporary
filesystems, and runs as UID 10001 with capabilities dropped. CI also scans all
installed OS/Python packages at every severity. Reports remain
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
