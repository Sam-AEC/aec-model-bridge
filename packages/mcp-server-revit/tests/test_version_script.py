"""Exercise release version synchronization in an isolated repository copy."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def version_script(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("version_script", repo / "scripts/version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for relative in {target[0] for target in module.TARGETS} | {"VERSION", "CHANGELOG.md"}:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / relative, destination)
    module.ROOT = tmp_path
    module.VERSION_FILE = tmp_path / "VERSION"
    module.CHANGELOG = tmp_path / "CHANGELOG.md"
    return module


def test_extension_version_updates_preserve_dependency_lock(version_script):
    script = version_script
    lock_path = script.ROOT / "extensions/vscode/package-lock.json"
    before = json.loads(lock_path.read_text(encoding="utf-8"))
    script.apply("1.4.0-rc.1")
    assert script.current() == "1.4.0-rc.1"
    assert script.scan(script.current()) == []
    after = json.loads(lock_path.read_text(encoding="utf-8"))
    assert after["version"] == after["packages"][""]["version"] == "1.4.0-rc.1"
    before["version"] = "1.4.0-rc.1"
    before["packages"][""]["version"] = "1.4.0-rc.1"
    assert after == before


@pytest.mark.parametrize("root_package", [False, True])
def test_extension_lock_version_drift_is_reported(version_script, root_package):
    script = version_script
    lock_path = script.ROOT / "extensions/vscode/package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    target = lock["packages"][""] if root_package else lock
    target["version"] = "0.0.0"
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    assert any("package-lock.json: found 0.0.0" in problem for problem in script.scan(script.current()))
