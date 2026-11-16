"""Do not restore the compromised emSign trust root during dependency updates."""
import ssl
import tomllib
from pathlib import Path

import certifi
from packaging.requirements import Requirement
from packaging.version import Version


def test_runtime_and_lock_require_a_patched_certifi():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirement = next(Requirement(dep) for dep in project["project"]["dependencies"] if dep.startswith("certifi"))
    assert Version("2026.10.19") in requirement.specifier
    assert Version("2026.5.20") not in requirement.specifier
    locked = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    versions = [Version(p["version"]) for p in locked["package"] if p["name"] == "certifi"]
    assert versions and all(v >= Version("2026.10.19") for v in versions)


def test_certifi_bundle_excludes_the_affected_emsign_root():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    common_names = {
        value
        for certificate in context.get_ca_certs()
        for relative_name in certificate["subject"]
        for key, value in relative_name
        if key == "commonName"
    }
    assert common_names
    assert "emSign ECC Root CA - G3" not in common_names
