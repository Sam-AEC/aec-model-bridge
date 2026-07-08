from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "revit" / "generate_canonical_test_model.py"
MANIFEST_PATH = REPO_ROOT / "fixtures" / "canonical-model" / "manifest.json"
SEEDED_DEFECTS_PATH = REPO_ROOT / "fixtures" / "canonical-model" / "seeded-defects.json"
SNAPSHOT_GOLDEN_PATH = REPO_ROOT / "fixtures" / "canonical-model" / "goldens" / "snapshot-summary.json"
QAQC_GOLDEN_PATH = REPO_ROOT / "fixtures" / "canonical-model" / "goldens" / "qaqc-findings-summary.json"
RULES_PATH = (
    REPO_ROOT
    / "packages"
    / "mcp-server-revit"
    / "src"
    / "revit_mcp_server"
    / "modules"
    / "qaqc_checker"
    / "rules"
    / "core.yaml"
)


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
    rules = RULES_PATH.read_text(encoding="utf-8")

    for rule_id in generator.SUPPORTED_SEEDED_RULES:
        assert f"id: {rule_id}" in rules


def test_seeded_defect_register_matches_manifest_and_core_rules():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    register = json.loads(SEEDED_DEFECTS_PATH.read_text(encoding="utf-8"))
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))["rules"]
    rules_by_id = {rule["id"]: rule for rule in rules}

    assert register["fixture"] == manifest["name"]
    assert register["source_manifest"] == "fixtures/canonical-model/manifest.json"
    assert manifest["seeded_defects"] == "fixtures/canonical-model/seeded-defects.json"
    expected = {entry["rule_id"]: entry["expected_count"] for entry in register["expected_findings"]}
    assert expected == manifest["supported_seeded_rules"]
    assert register["expected_total_findings"] == sum(expected.values())

    for entry in register["expected_findings"]:
        rule = rules_by_id[entry["rule_id"]]
        assert entry["severity"] == rule["severity"]
        assert entry["category"] == rule["category"]


def test_seeded_defect_register_tracks_known_manifest_gaps():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    register = json.loads(SEEDED_DEFECTS_PATH.read_text(encoding="utf-8"))
    gaps = {entry["rule_id"]: entry["reason"] for entry in register["known_gaps"]}

    assert gaps == manifest["known_gaps"]
    assert {entry["status"] for entry in register["known_gaps"]} == {"bridge_gap"}


def test_canonical_goldens_match_manifest_and_seed_register():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    register = json.loads(SEEDED_DEFECTS_PATH.read_text(encoding="utf-8"))
    snapshot_golden = json.loads(SNAPSHOT_GOLDEN_PATH.read_text(encoding="utf-8"))
    qaqc_golden = json.loads(QAQC_GOLDEN_PATH.read_text(encoding="utf-8"))

    assert manifest["goldens"] == {
        "snapshot_summary": "fixtures/canonical-model/goldens/snapshot-summary.json",
        "qaqc_findings_summary": "fixtures/canonical-model/goldens/qaqc-findings-summary.json",
    }
    assert snapshot_golden["fixture"] == manifest["name"]
    assert qaqc_golden["fixture"] == manifest["name"]
    assert snapshot_golden["required_category_counts"] == {
        "OST_Levels": manifest["expected_counts"]["levels"],
        "OST_Walls": manifest["expected_counts"]["walls"],
        "OST_Doors": manifest["expected_counts"]["doors"],
        "OST_Windows": manifest["expected_counts"]["windows"],
        "OST_Rooms": manifest["expected_counts"]["rooms"],
        "OST_Sheets": manifest["expected_counts"]["sheets"],
    }
    assert qaqc_golden["seeded_rule_counts"] == {
        entry["rule_id"]: entry["expected_count"] for entry in register["expected_findings"]
    }


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
