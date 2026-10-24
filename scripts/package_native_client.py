# Shared native build procedure adapted from Robert-Velhorst/023-Secondhand-platforms-autoposter at 671c244.
"""Register exact source-built libraries in Alpine's installed inventory."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PREFIX = Path("/opt/studiopilot-native")
if sys.platform != "linux" or Path(__file__).resolve().parents[1] != Path(
    "/native-build"
):
    raise RuntimeError("Packaging is restricted to the isolated Linux SDK stage")
provenance = json.loads(
    (PREFIX / "share/build-provenance.json").read_text(encoding="utf-8")
)
for relative, digest in provenance["libraries"].items():
    if hashlib.sha256((PREFIX / relative).read_bytes()).hexdigest() != digest:
        raise RuntimeError("Native library differs from its source-build provenance")
architecture = subprocess.check_output(["apk", "--print-arch"], text=True).strip()
key = Path("/tmp/studiopilot-native-build.rsa")
keys = Path("/tmp/studiopilot-native-package-keys")
keys.mkdir()
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
        str(keys / "studiopilot-native-build.rsa.pub"),
    ],
    check=True,
    timeout=60,
)
components = [
    (
        "libcrypto4",
        "4.1.0",
        "openssl",
        "Apache-2.0",
        "libcrypto.so*",
        ["musl"],
        "https://www.openssl.org/",
        "OpenSSL.txt",
    ),
    (
        "libssl4",
        "4.1.0",
        "openssl",
        "Apache-2.0",
        "libssl.so*",
        ["musl", "libcrypto4=4.1.0-r0"],
        "https://www.openssl.org/",
        "OpenSSL.txt",
    ),
    (
        "libpq",
        "18.6",
        "postgresql18",
        "PostgreSQL",
        "libpq*.so*",
        ["musl", "libcrypto4=4.1.0-r0", "libssl4=4.1.0-r0", "krb5-libs", "libldap"],
        "https://www.postgresql.org/",
        "PostgreSQL.txt",
    ),
]
try:
    for (
        name,
        version,
        origin,
        license_id,
        pattern,
        dependencies,
        url,
        license_file,
    ) in components:
        with tempfile.TemporaryDirectory(prefix="studiopilot-native-apk-") as temporary:
            package = Path(temporary)
            package.chmod(0o755)
            library_root = package / "opt/studiopilot-native/lib"
            library_root.mkdir(parents=True)
            sources = list((PREFIX / "lib").glob(pattern))
            if not sources:
                raise RuntimeError(
                    "The native component produced no libraries: " + name
                )
            for source in sources:
                # Preserve only relative intra-directory SONAME links.
                if source.is_symlink():
                    target = source.readlink()
                    if target.is_absolute() or target.parent != Path("."):
                        raise RuntimeError(
                            "Native SONAME link is outside its library directory"
                        )
                    (library_root / source.name).symlink_to(target)
                else:
                    shutil.copy2(source, library_root / source.name)
            if name == "libcrypto4" and (PREFIX / "lib/ossl-modules").exists():
                shutil.copytree(
                    PREFIX / "lib/ossl-modules",
                    library_root / "ossl-modules",
                    symlinks=True,
                )
            documentation = package / "usr/share/doc" / name
            documentation.mkdir(parents=True)
            shutil.copyfile(
                PREFIX / "share/licenses" / license_file, documentation / "LICENSE"
            )
            (documentation / "studiopilot-build.json").write_text(
                json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
            )
            output = f"/tmp/studiopilot-{name}.apk"
            command = ["apk", "--sign-key", str(key), "mkpkg", "--files", str(package)]
            for field, value in {
                "name": name,
                "version": version + "-r0",
                "arch": architecture,
                "origin": origin,
                "description": "StudioPilot checksum-verified upstream native client library",
                "license": license_id,
                "maintainer": "StudioPilot",
                "url": url,
                "depends": " ".join(dependencies),
            }.items():
                command.extend(["--info", field + ":" + value])
            command.extend(["--output", output])
            subprocess.run(command, check=True, timeout=60)
            subprocess.run(
                ["apk", "--keys-dir", str(keys), "verify", output],
                check=True,
                timeout=60,
            )
finally:
    key.unlink(
        missing_ok=True
    )  # Never commit the ephemeral private key in an image layer.
