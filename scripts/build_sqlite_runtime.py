"""Build and register verified SQLite in an isolated Alpine Docker builder."""

import ctypes
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("SQLite source redirects are not permitted")


def main():
    if sys.platform != "linux" or not shutil.which("apk"):
        raise RuntimeError("This builder is restricted to the isolated Alpine image")
    spec = json.loads(ROOT.joinpath("sqlite-runtime.json").read_text())
    version = spec["version"]
    if not re.fullmatch(r"3\.\d{1,2}\.\d{1,2}", version):
        raise RuntimeError("Expected a stable SQLite 3 release")
    major, minor, patch = map(int, version.split("."))
    archive_root = f"sqlite-autoconf-{major}{minor:02}{patch:02}00"
    url = urllib.parse.urlsplit(spec["source_url"])
    if (
        url.scheme,
        url.hostname,
        url.port,
        url.username,
        url.password,
        url.query,
        url.fragment,
    ) != (
        "https",
        "www.sqlite.org",
        None,
        None,
        None,
        "",
        "",
    ) or url.path != "/2026/" + archive_root + ".tar.gz":
        raise RuntimeError("Unexpected pinned SQLite source origin/path")
    if not re.fullmatch(r"[0-9a-f]{64}", spec["source_sha3_256"]):
        raise RuntimeError("Missing source checksum")
    with urllib.request.build_opener(NoRedirect).open(
        spec["source_url"], timeout=60
    ) as response:
        archive = response.read(8 * 1024 * 1024 + 1)
    if (
        len(archive) > 8 * 1024 * 1024
        or hashlib.sha3_256(archive).hexdigest() != spec["source_sha3_256"]
    ):
        raise RuntimeError("SQLite source integrity failed")

    output = ROOT / "output"
    output.mkdir()
    keys = output / "keys"
    keys.mkdir()
    architecture = subprocess.check_output(["apk", "--print-arch"], text=True).strip()
    # Retain the Alpine distribution's feature and variable-count settings.
    flags = [
        "-O2",
        "-fPIC",
        "-shared",
        "-Wl,-soname,libsqlite3.so.0",
        "-DSQLITE_THREADSAFE=1",
        "-DSQLITE_USE_URI=1",
        "-DSQLITE_ENABLE_COLUMN_METADATA",
        "-DSQLITE_SECURE_DELETE",
        "-DSQLITE_ENABLE_UNLOCK_NOTIFY",
        "-DSQLITE_ENABLE_RTREE",
        "-DSQLITE_ENABLE_GEOPOLY",
        "-DSQLITE_ENABLE_DBSTAT_VTAB",
        "-DSQLITE_SOUNDEX",
        "-DSQLITE_MAX_VARIABLE_NUMBER=250000",
        "-DSQLITE_ENABLE_FTS3",
        "-DSQLITE_ENABLE_FTS3_PARENTHESIS",
        "-DSQLITE_ENABLE_FTS4",
        "-DSQLITE_ENABLE_FTS5",
        "-DSQLITE_ENABLE_SESSION",
        "-DSQLITE_ENABLE_PREUPDATE_HOOK",
        "-DSQLITE_ENABLE_MATH_FUNCTIONS",
    ]
    with tempfile.TemporaryDirectory(prefix="studiopilot-sqlite-build-") as temporary:
        temporary = Path(temporary)
        source = temporary / "sqlite3.c"
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            total = 0
            for index, member in enumerate(bundle):
                total += member.size
                if index >= 5000 or total > 128 * 1024 * 1024:
                    raise RuntimeError("Unexpected SQLite archive inventory")
                if member.name == archive_root + "/sqlite3.c":
                    if not member.isfile() or member.size > 20 * 1024 * 1024:
                        raise RuntimeError("Unexpected SQLite amalgamation")
                    with bundle.extractfile(member) as stream:
                        content = stream.read(20 * 1024 * 1024 + 1)
                    if len(content) != member.size:
                        raise RuntimeError("Truncated SQLite source")
                    source.write_bytes(content)
                    break
            else:
                raise RuntimeError("SQLite amalgamation missing")
        library = temporary / "libsqlite3.so.0"
        subprocess.run(
            ["cc", *flags, str(source), "-lm", "-ldl", "-pthread", "-o", str(library)],
            check=True,
            timeout=300,
        )
        handle = ctypes.CDLL(str(library))
        handle.sqlite3_libversion.restype = ctypes.c_char_p
        handle.sqlite3_sourceid.restype = ctypes.c_char_p
        if handle.sqlite3_libversion().decode() != version:
            raise RuntimeError("Compiled SQLite version mismatch")
        actual = subprocess.check_output(
            [
                sys.executable,
                "-I",
                "-c",
                "import sqlite3; print(sqlite3.sqlite_version)",
            ],
            text=True,
            env={**os.environ, "LD_LIBRARY_PATH": str(temporary)},
            timeout=30,
        ).strip()
        if actual != version:
            raise RuntimeError("CPython did not load the verified SQLite engine")
        provenance = {
            "version": version,
            "source_url": spec["source_url"],
            "source_sha3_256": spec["source_sha3_256"],
            "binary_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "source_id": handle.sqlite3_sourceid().decode(),
            "arch": architecture,
            "compile_flags": flags,
            "cpython_sqlite_version": actual,
            "operator_database_opened": False,
        }
        package = temporary / "package"
        destination = package / "usr/lib/libsqlite3.so.0"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(library, destination)
        destination.chmod(0o644)
        documentation = package / "usr/share/doc/sqlite-libs"
        documentation.mkdir(parents=True)
        documentation.joinpath("studiopilot-build.json").write_text(
            json.dumps(provenance, indent=2) + "\n"
        )
        documentation.joinpath("copyright").write_text(
            "SQLite is in the public domain. https://www.sqlite.org/copyright.html\n"
        )
        key = temporary / "studiopilot-sqlite-build.rsa"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:3072",
                "-out",
                str(key),
            ],
            check=True,
            timeout=60,
        )
        key.chmod(0o600)
        subprocess.run(
            [
                "openssl",
                "rsa",
                "-in",
                str(key),
                "-pubout",
                "-out",
                str(keys / "studiopilot-sqlite-build.rsa.pub"),
            ],
            check=True,
            timeout=60,
        )
        args = ["apk", "--sign-key", str(key), "mkpkg", "--files", str(package)]
        for value in [
            "name:sqlite-libs",
            "version:" + version + "-r0",
            "arch:" + architecture,
            "origin:sqlite",
            "description:StudioPilot verified upstream SQLite",
            "license:blessing",
            "maintainer:StudioPilot",
            "url:https://www.sqlite.org/",
            "depends:musl",
            "provides:so:libsqlite3.so.0=0",
        ]:
            args.extend(["--info", value])
        apk = output / "studiopilot-sqlite.apk"
        subprocess.run([*args, "--output", str(apk)], check=True, timeout=60)
        subprocess.run(
            ["apk", "--keys-dir", str(keys), "verify", str(apk)], check=True, timeout=60
        )
        key.unlink()  # The signing key is removed within this builder RUN.
    print(json.dumps(provenance))


if __name__ == "__main__":
    main()
