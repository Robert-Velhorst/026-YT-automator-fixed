# Linux native runtime

The Linux backend image builds OpenSSL 4.1.0 and PostgreSQL's 18.6 client from
the upstream archives and SHA-256 values in `native-client-runtime.json`.
PostgreSQL 19 is a release candidate at this source snapshot; it is excluded.
No PostgreSQL server is built, started, migrated, or contacted by these builders.

The isolated build stage rebuilds only CPython 3.15.1's `_ssl` and `_hashlib`
extensions against that OpenSSL. It preserves the exact installed interpreter
ABI and headers, the operating system CA store, and the other CPython modules.
It also builds cryptography 50.0.2 and Psycopg's C implementation against the
same libraries. Rust 1.99.1 is confined to the disposable build stage.

`requirements-image.in` matches the backend requirements except that Linux uses
`psycopg[c]` instead of `psycopg[binary]`. Windows and host qualification retain
their existing binary implementation and lock files. Their bundled native
libraries require separate verification and are not covered by this image.

The complete image dependency graph and build tools have hash-locked inputs.
Locally compiled wheels receive a separate generated SHA-256 lock. The final
image installs only those wheels offline and runs `pip check` before removing
pip and its bundled installer. No compiler, Rust SDK, private package signing
key, or upstream source tree is copied into the final image.

The actual native libraries are registered as Alpine packages, with library
hashes, source provenance, and licenses. Public build keys are supplied only
for the offline package install; they are not added to global trusted keys.
The installed library inventory and vulnerability scan are not rewritten.

CI records the image ID, installed package versions, source and library hashes,
CPython extension hashes, CA availability, and `/proc/self/maps` library paths.
It requires CPython and cryptography to report OpenSSL 4.1.0 and Psycopg to use
the C implementation with libpq 18.6. It retains SQLite 3.54.1 qualification,
the existing backend cases, and the unsuppressed OS/Python vulnerability gate.
System compatibility libraries needed by LDAP/GSSAPI may still use OpenSSL 3;
their actual versions remain in the scan and mapped-library evidence.

This is a container qualification path. It does not establish deployment,
provider authentication, compatibility with an operator database, or that every
OS dependency is the latest upstream release. Deployment remains targeted at
Hetzner under `DEPLOYMENT_TARGET.md`.

Upstream references:

- https://openssl-library.org/source/
- https://www.postgresql.org/download/
- https://www.python.org/downloads/release/python-3151/
- https://cryptography.io/en/latest/installation/
- https://www.maturin.rs/config.html
- https://raw.githubusercontent.com/PyO3/maturin/v1.15.0/maturin/__init__.py
