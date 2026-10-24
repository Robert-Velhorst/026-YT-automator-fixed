"""Inspect installed native code without starting the app or opening a database."""

import hashlib
import json
import os
import platform
import sqlite3
import ssl
import subprocess
import sysconfig
from importlib import metadata
from pathlib import Path

import psycopg.pq
from cryptography.hazmat.bindings.openssl.binding import Binding


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    native = json.loads(Path("/app/native-client-runtime.json").read_text())
    prefix = Path(native["prefix"])
    built = json.loads(
        Path("/usr/share/doc/libcrypto4/studiopilot-build.json").read_text()
    )
    assert built["sources"] == native
    libraries = {}
    for relative, expected in built["libraries"].items():
        path = prefix / relative
        assert digest(path) == expected, str(path)
        libraries[str(path.resolve())] = expected
    python_tls = json.loads(
        Path("/usr/share/doc/studiopilot-python-tls/provenance.json").read_text()
    )
    assert python_tls["source"] == native["cpython"]
    for filename, record in python_tls["modules"].items():
        assert Path(filename).name == filename
        assert (
            digest(Path(sysconfig.get_config_var("DESTSHARED")) / filename)
            == record["sha256"]
        )
    expected_ssl = "OpenSSL " + native["openssl"]["version"] + " "
    binding = Binding()
    cryptography_ssl = binding.ffi.string(binding.lib.OpenSSL_version(0)).decode()
    assert ssl.OPENSSL_VERSION.startswith(expected_ssl)
    assert cryptography_ssl.startswith(expected_ssl)
    assert platform.python_version() == native["cpython"]["version"]
    assert psycopg.pq.__impl__ == "c" and psycopg.pq.version() == 180006
    ca_roots = len(ssl.create_default_context().get_ca_certs())
    assert ca_roots > 0
    mappings = sorted(
        {
            line.split()[-1]
            for line in Path("/proc/self/maps").read_text().splitlines()
            if len(line.split()) >= 6 and line.split()[-1].startswith("/")
        }
    )
    loaded_native = [
        path
        for path in mappings
        if Path(path).name.startswith(("libssl", "libcrypto", "libpq"))
    ]
    for stem in ("libssl.so.4", "libcrypto.so.4", "libpq.so.5"):
        selected = [path for path in loaded_native if Path(path).name.startswith(stem)]
        assert selected and all(path in libraries for path in selected), (
            stem,
            selected,
        )
    assert all(
        path in libraries
        for path in loaded_native
        if Path(path).name.startswith("libpq")
    )
    profile = json.loads(Path("/app/sqlite-runtime.json").read_text())
    sqlite_build = json.loads(
        Path("/usr/share/doc/sqlite-libs/studiopilot-build.json").read_text()
    )
    sqlite_hash = digest("/usr/lib/libsqlite3.so.0")
    assert sqlite3.sqlite_version == profile["version"] == sqlite_build["version"]
    assert sqlite_hash == sqlite_build["binary_sha256"]
    assert profile["source_sha3_256"] == sqlite_build["source_sha3_256"]
    packages = (
        subprocess.check_output(
            [
                "apk",
                "--no-network",
                "list",
                "--installed",
                "sqlite-libs",
                "libcrypto4",
                "libssl4",
                "libpq",
            ],
            text=True,
        )
        .strip()
        .splitlines()
    )
    installed_apk = sorted(line.split()[0] for line in packages)
    assert installed_apk == sorted(
        [
            "sqlite-libs-" + profile["version"] + "-r0",
            "libcrypto4-4.1.0-r0",
            "libssl4-4.1.0-r0",
            "libpq-18.6-r0",
        ]
    )
    wheels = json.loads(
        Path("/usr/share/doc/studiopilot-wheels/build-wheels.json").read_text()
    )
    toolchain = json.loads(
        Path("/usr/share/doc/studiopilot-wheels/build-toolchain.json").read_text()
    )
    assert toolchain["rustc"].split()[1] == native["rust"]["version"]
    assert toolchain["cargo"].split()[1] == native["rust"]["version"]
    for row in wheels:
        assert metadata.version(row["name"]) == row["version"]
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "uid": os.getuid(),
                "python_ssl": ssl.OPENSSL_VERSION,
                "cryptography_ssl": cryptography_ssl,
                "libpq": psycopg.pq.version(),
                "psycopg_implementation": psycopg.pq.__impl__,
                "ca_roots": ca_roots,
                "loaded_native_libraries": loaded_native,
                "native_build": built,
                "python_tls_build": python_tls,
                "compiled_wheels": wheels,
                "build_toolchain": toolchain,
                "installed_native_apks": installed_apk,
                "sqlite": sqlite3.sqlite_version,
                "sqlite_build": sqlite_build,
                "sqlite_binary_sha256": sqlite_hash,
                "packages": {
                    d.metadata["Name"]: d.version for d in metadata.distributions()
                },
                "operator_database_opened": False,
                "application_started": False,
                "deployment_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
