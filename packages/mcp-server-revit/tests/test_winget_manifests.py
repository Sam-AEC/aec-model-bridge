"""Checks for the winget manifest templates and packaging/winget/fill_manifests.py."""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WINGET = ROOT / "packaging" / "winget"
ISS = ROOT / "scripts" / "installer" / "AECModelBridge.iss"


def _fill_module():
    spec = importlib.util.spec_from_file_location("fill_manifests", WINGET / "fill_manifests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fill():
    return _fill_module()


def _iss_setting(name: str) -> str:
    match = re.search(rf"(?m)^{name}=(.+?)\s*$", ISS.read_text(encoding="utf-8"))
    assert match, name
    return match.group(1)


def test_templates_match_the_inno_installer():
    installer = (WINGET / "manifests" / "SamAEC.AECModelBridge.installer.yaml").read_text(encoding="utf-8")
    app_id = _iss_setting("AppId").replace("{{", "{")
    assert installer.count(f"'{app_id}_is1'") == 2
    assert "InstallerType: inno" in installer
    # PrivilegesRequired=lowest installs per user.
    assert _iss_setting("PrivilegesRequired") == "lowest"
    assert "Scope: user" in installer
    assert _iss_setting("OutputBaseFilename") == 'AECModelBridge-Setup-{#SetupSetting("AppVersion")}'


def test_templates_share_identifier_and_schema_version():
    for path in sorted((WINGET / "manifests").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "PackageIdentifier: SamAEC.AECModelBridge" in text, path.name
        assert "ManifestVersion: 1.10.0" in text, path.name
        assert "PackageVersion: __VERSION__" in text, path.name


def test_fill_writes_winget_pkgs_layout(fill, tmp_path):
    sha = hashlib.sha256(b"installer").hexdigest()
    target = fill.fill("1.6.0", sha, tmp_path)
    assert target == tmp_path / "manifests" / "s" / "SamAEC" / "AECModelBridge" / "1.6.0"
    files = sorted(p.name for p in target.iterdir())
    assert files == [
        "SamAEC.AECModelBridge.installer.yaml",
        "SamAEC.AECModelBridge.locale.en-US.yaml",
        "SamAEC.AECModelBridge.yaml",
    ]
    installer = (target / "SamAEC.AECModelBridge.installer.yaml").read_text(encoding="utf-8")
    assert "PackageVersion: 1.6.0" in installer
    assert "releases/download/v1.6.0/AECModelBridge-Setup-1.6.0.exe" in installer
    assert f"InstallerSha256: {sha.upper()}" in installer
    for path in target.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "__" not in text.replace("_is1", ""), path.name
        assert "# Template." not in text


@pytest.mark.parametrize("version", ["1.6", "v1.6.0", "1.6.0-rc.1", ""])
def test_fill_refuses_non_stable_versions(fill, tmp_path, version):
    with pytest.raises(fill.FillError):
        fill.fill(version, "0" * 64, tmp_path)
    assert not (tmp_path / "manifests").exists()


def test_fill_refuses_bad_hash(fill, tmp_path):
    with pytest.raises(fill.FillError):
        fill.fill("1.6.0", "abc", tmp_path)


def test_checksum_lookup(fill):
    sha = "a" * 64
    body = f"{'b' * 64}  other.zip\n{sha}  AECModelBridge-Setup-1.6.0.exe\n"
    assert fill.sum_from_checksums(body, "AECModelBridge-Setup-1.6.0.exe") == sha
    with pytest.raises(fill.FillError):
        fill.sum_from_checksums(body, "AECModelBridge-Setup-1.7.0.exe")


def test_main_offline_hashes_local_installer(fill, tmp_path):
    exe = tmp_path / "AECModelBridge-Setup-1.6.0.exe"
    exe.write_bytes(b"fake installer")
    out = tmp_path / "out"
    assert fill.main(["1.6.0", "--installer", str(exe), "--offline", "--out", str(out)]) == 0
    installer = (out / "manifests/s/SamAEC/AECModelBridge/1.6.0/SamAEC.AECModelBridge.installer.yaml").read_text(
        encoding="utf-8"
    )
    assert hashlib.sha256(b"fake installer").hexdigest().upper() in installer


def test_main_offline_without_installer_fails_closed(fill, tmp_path, capsys):
    assert fill.main(["1.6.0", "--offline", "--out", str(tmp_path)]) == 1
    assert "--offline needs --installer" in capsys.readouterr().err
    assert not (tmp_path / "manifests").exists()
