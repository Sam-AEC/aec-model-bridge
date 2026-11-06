"""Regression checks for the content of release dependency inventories."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notice_preserves_complete_long_licence():
    notices = _script("generate_third_party_notices")
    full_text = "licence terms " * 4000 + "FINAL REQUIRED NOTICE"

    class LicenceFile:
        def as_posix(self):
            return "example-1.0.dist-info/licenses/LICENSE.txt"

        def read_text(self, **kwargs):
            return full_text

    assert notices.python_licence_texts(SimpleNamespace(files=[LicenceFile()])) == [("LICENSE.txt", full_text)]


def test_notice_does_not_attribute_installed_text_to_another_version(monkeypatch):
    notices = _script("generate_third_party_notices")
    monkeypatch.setattr(notices, "lock_runtime_closure", lambda: {"example": "1.0"})
    monkeypatch.setattr(notices.metadata, "distribution", lambda name: SimpleNamespace(version="2.0"))
    monkeypatch.setattr(notices, "python_licence", lambda dist: "MIT")
    monkeypatch.setattr(notices, "python_home", lambda dist: "https://example.com")
    monkeypatch.setattr(notices, "python_licence_texts", lambda dist: [("LICENSE", "WRONG VERSION TEXT")])
    result = "\n".join(notices.python_section())
    assert "installed 2.0, lock 1.0" in result
    assert "WRONG VERSION TEXT" not in result


def test_notice_nuget_inventory_ignores_local_cache(tmp_path, monkeypatch):
    notices = _script("generate_third_party_notices")
    project = tmp_path / "packages" / "addin"
    project.mkdir(parents=True)
    (project / "addin.csproj").write_text('<Project><PackageReference Include="Example" Version="1.0" /></Project>')
    monkeypatch.setattr(notices, "ROOT", tmp_path)
    empty = notices.nuget_section()
    cache = tmp_path / "nuget" / "example" / "1.0"
    cache.mkdir(parents=True)
    (cache / "example.nuspec").write_text('<package><metadata><license>MIT</license></metadata></package>')
    monkeypatch.setenv("NUGET_PACKAGES", str(cache.parents[1]))
    assert notices.nuget_section() == empty
    assert "see package" in "\n".join(empty)


def _bom(components):
    return {"metadata": {"component": {"name": "aec-model-bridge", "version": "1.5.0"}},
            "components": components}


def test_release_sbom_matches_installed_distributions():
    sbom = _script("validate_release_sbom")
    installed = [{"name": "aec-model-bridge", "version": "1.5.0"},
                 {"name": "typing_extensions", "version": "4.0"}]
    sbom.validate(_bom(installed), installed, "1.5.0")


@pytest.mark.parametrize("fault", ["missing", "wrong_dependency_version", "extra", "stale_project", "duplicate"])
def test_release_sbom_rejects_misreported_or_stale_bundle(fault):
    sbom = _script("validate_release_sbom")
    installed = [{"name": "aec-model-bridge", "version": "1.5.0"},
                 {"name": "example", "version": "1.0"}]
    components = [dict(dist) for dist in installed]
    if fault == "missing":
        components.pop()
    elif fault == "wrong_dependency_version":
        components[-1]["version"] = "2.0"
    elif fault == "extra":
        components.append({"name": "not-shipped", "version": "1.0"})
    elif fault == "stale_project":
        installed[0]["version"] = "1.4.0"
    else:
        installed.append({"name": "aec-model-bridge", "version": "1.4.0"})
    with pytest.raises(ValueError):
        sbom.validate(_bom(components), installed, "1.5.0")


def test_release_sbom_accepts_normalized_prerelease_version():
    sbom = _script("validate_release_sbom")
    installed = [{"name": "aec-model-bridge", "version": "1.5.0rc1"}]
    bom = _bom(installed)
    bom["metadata"]["component"]["version"] = "1.5.0-rc.1"
    sbom.validate(bom, installed, "1.5.0-rc.1")
