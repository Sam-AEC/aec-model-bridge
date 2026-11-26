"""Every tool name carries a documented prefix, or is a documented full name.

docs/run-beside-autodesk-revit-mcp.md lists the prefixes so that this server can run next to
another Revit MCP server without tool name clashes. A new tool with an unlisted name fails here:
use a listed prefix, or add the prefix to the test and to the docs page together.
"""

from __future__ import annotations

from pathlib import Path

from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs" / "run-beside-autodesk-revit-mcp.md"

PROVIDER_PREFIXES = (
    "revit_", "aec_", "exporter_", "graph_", "ifc_", "navisworks_", "rhino_",
    "snapshot_", "speckle_", "autodesk_data_", "proxy_",
)
MODULE_PREFIXES = (
    "bcf_exchange_", "clash_triage_", "familytype_mapper_", "hello_world_", "ids_validator_",
    "links_worksets_audit_", "mark_renumber_plan_", "model_bloat_", "model_changes_", "model_health_", "model_inspector_",
    "naming_checker_", "param_completeness_", "parameter_manager_", "pyrevit_bridge_",
    "qa_handover_", "qaqc_checker_", "recipe_runner_", "report_generator_",
    "schedule_consistency_", "schedule_diff_", "selection_tools_", "sheet_set_qa_", "sheet_view_audit_",
    "warnings_triage_",
)
FULL_NAMES = (
    "plan_actions", "plan_revert", "execute_plan", "list_pending_plans", "get_proof_bundle",
    "policy_show", "approve_plan", "reject_plan", "rollback_plan", "job_status", "job_cancel",
    "search_tools", "context_report", "module_list_commands",
)


def _registered_names(tmp_path) -> list[str]:
    registry, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    return sorted({t.name for p in registry.get_all_providers() for t in p.get_capabilities()})


def test_every_tool_name_has_a_documented_prefix(tmp_path):
    names = _registered_names(tmp_path)
    assert len(names) > 100
    prefixes = PROVIDER_PREFIXES + MODULE_PREFIXES
    unlisted = [n for n in names if n not in FULL_NAMES and not n.startswith(prefixes)]
    assert not unlisted, (
        f"Tool names without a documented prefix: {unlisted}. Use a listed prefix, or add one to "
        "this test and to docs/run-beside-autodesk-revit-mcp.md."
    )


def test_documented_full_names_exist(tmp_path):
    names = set(_registered_names(tmp_path))
    assert not [n for n in FULL_NAMES if n not in names]


def test_docs_page_lists_every_provider_prefix_and_full_name():
    text = DOC.read_text(encoding="utf-8")
    missing = [p for p in PROVIDER_PREFIXES + FULL_NAMES if f"`{p}" not in text]
    assert not missing, f"docs/run-beside-autodesk-revit-mcp.md does not mention: {missing}"


def test_docs_page_marks_autodesk_behaviour_unverified():
    assert "UNVERIFIED" in DOC.read_text(encoding="utf-8")
