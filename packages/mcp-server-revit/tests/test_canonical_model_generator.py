from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "revit" / "generate_canonical_test_model.py"
MANIFEST_PATH = REPO_ROOT / "fixtures" / "canonical-model" / "manifest.json"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_canonical_test_model", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_planned_counts_match_manifest():
    generator = load_generator()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert generator.EXPECTED_COUNTS == manifest["expected_counts"]
    assert generator.manifest()["output_path"] == manifest["output_path"]
    counts = generator.planned_call_counts()
    assert counts["revit.create_level"] == 5
    assert counts["revit.create_wall"] == 200
    assert counts["revit.place_door"] == 60
    assert counts["revit.place_window"] == 40
    assert counts["revit.create_room"] == 25
    assert counts["revit.create_floor_plan_view"] == 30
    assert counts["revit.create_sheet"] == 10
    assert counts["revit.create_group"] == 4


def test_supported_seed_rules_exist_in_core_pack():
    generator = load_generator()
    rules = (
        REPO_ROOT
        / "packages"
        / "mcp-server-revit"
        / "src"
        / "revit_mcp_server"
        / "modules"
        / "qaqc_checker"
        / "rules"
        / "core.yaml"
    ).read_text(encoding="utf-8")

    for rule_id in generator.SUPPORTED_SEEDED_RULES:
        assert f"id: {rule_id}" in rules


def test_registry_discovery_uses_newest_switch(tmp_path, monkeypatch):
    generator = load_generator()
    registry = tmp_path / "AECModelBridge" / "registry"
    registry.mkdir(parents=True)
    old = registry / "revit-1.json"
    new = registry / "revit-2.json"
    old.write_text(json.dumps({"endpoint": "http://127.0.0.1:3000"}), encoding="utf-8")
    new.write_text(
        json.dumps({"endpoint": "http://127.0.0.1:4567", "session_token": "tok"}),
        encoding="utf-8",
    )
    old.touch()
    new.touch()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    switch = generator.discover_switch()

    assert switch.endpoint == "http://127.0.0.1:4567"
    assert switch.token == "tok"


def test_generated_model_directory_is_ignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "fixtures/canonical-model/generated/" in gitignore


def test_custom_output_path_can_live_outside_repo(tmp_path):
    generator = load_generator()
    outside = tmp_path / "canonical.rvt"

    assert generator.manifest(outside)["output_path"] == str(outside)
