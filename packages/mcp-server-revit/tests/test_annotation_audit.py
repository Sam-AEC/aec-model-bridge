"""Audit of MCP behaviour annotations across the whole tool registry.

"Mutating" comes from the registry itself (``tool.is_mutating``, the flag the approval gate
uses), not from a list kept here; the gate tests below run the real ``gate_before`` on every
tool. Tools that write files (exports, saved queries, rule packs, reports) are not
model-mutating but still are not read-only: they sit in ``NOT_READ_ONLY`` or
``REPORT_FILE_WRITERS``. The registry is built with a placeholder APS client id so the optional
Autodesk cloud provider is audited too.
"""
import os
import re

import pytest

from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS, ApprovalGate
from revit_mcp_server.security.dispatch import gate_before
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import (
    ADDITIVE_NAME_PARTS, ADDITIVE_NAMES, NOT_READ_ONLY, OPEN_WORLD_PROVIDERS, REPORT_FILE_WRITERS,
    enrich_tool,
)
from revit_mcp_server.tool_profiles import CORE_TOOLS, DAILY_EXCLUDE, ToolProfile

# Name parts that say a tool writes something. A tool with one of these that is flagged
# read-only must be on the reviewed list below (each was checked to only read or compute).
WRITE_WORDS = {
    "create", "set", "delete", "place", "modify", "move", "import", "export", "save", "write", "apply",
    "remove", "update", "add", "copy", "rename", "purge", "execute", "publish", "send", "push", "resolve",
    "run", "rotate", "mirror", "align", "tag", "pin", "unpin", "load", "reload", "register", "compile",
}
REVIEWED_READ_ONLY = {
    "sheet_view_audit_run_audit",          # audits a saved snapshot
    "model_inspector_run_saved_query",     # reads a saved query and runs it on a snapshot
    "recipe_runner_get_run_status",        # status read
    "parameter_manager_plan_set_params",   # computes a plan proposal; the write goes through plan_actions
    "pyrevit_bridge_plan_run_pyrevit_script",
    "bcf_exchange_import_bcf",             # parses a BCF file and returns the issues
    "clash_triage_import_clash_report",    # parses a clash report and returns matched groups
    "parameter_manager_import_params_csv", # reads a CSV and returns a change proposal
    "parameter_manager_import_params_xlsx", # reads a workbook and returns a change proposal
}


# Input parameters that name a file the tool writes. A tool with one is not read-only and may
# replace an existing file of that name (destructive).
OUTPUT_FILE_PARAMS = {
    "output_path", "output_filename", "output_name", "output_dir", "csv_filename", "html_filename",
    "json_filename", "db_path", "save_as", "destination",
}
# Reviewed: these take one of the names above as an input file they only read.
READS_NAMED_FILE = {"parameter_manager_import_params_csv"}


@pytest.fixture(scope="module")
def registry(tmp_path_factory):
    saved = os.environ.get("APS_CLIENT_ID")
    os.environ["APS_CLIENT_ID"] = "annotation-audit-placeholder"
    try:
        reg, *_ = build_registry(WorkspaceMonitor([tmp_path_factory.mktemp("ws")]))
    finally:
        if saved is None:
            os.environ.pop("APS_CLIENT_ID", None)
        else:
            os.environ["APS_CLIENT_ID"] = saved
    return reg


@pytest.fixture(scope="module")
def tools(registry):
    return [(p.get_identity(), t) for p, t in registry.get_tools_with_providers()]


def _ann(provider_id, tool):
    return enrich_tool(provider_id, tool).annotations


def _gate_consulted(registry, gate, name):
    """True when the approval gate treats a plain call to ``name`` as a write that needs a plan."""
    try:
        return gate_before(registry, gate, name, {}) is not None
    except Exception:
        return True


def _is_additive(tool):
    parts = set(tool.name.split("_"))
    return tool.name in ADDITIVE_NAMES or bool(parts & ADDITIVE_NAME_PARTS)


def test_registry_is_not_empty(tools):
    assert len(tools) > 250


def test_every_tool_has_complete_annotations(tools):
    for provider_id, tool in tools:
        ann = enrich_tool(provider_id, tool).annotations
        assert ann is not None, tool.name
        for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert getattr(ann, hint) is not None, (tool.name, hint)


def test_mutating_tools_are_not_read_only_and_destructive_unless_additive(tools):
    for provider_id, tool in tools:
        if not tool.is_mutating:
            continue
        ann = enrich_tool(provider_id, tool).annotations
        assert ann.readOnlyHint is False, tool.name
        if tool.destructive:
            assert ann.destructiveHint is True, tool.name
        elif not _is_additive(tool) and tool.name not in NOT_READ_ONLY:
            assert ann.destructiveHint is True, tool.name


def test_tools_that_can_write_files_or_state_are_not_read_only(tools):
    for provider_id, tool in tools:
        ann = enrich_tool(provider_id, tool).annotations
        if tool.name in NOT_READ_ONLY or tool.name in REPORT_FILE_WRITERS or tool.name in HUMAN_ONLY_TOOLS:
            assert ann.readOnlyHint is False, tool.name


def test_read_tools_are_read_only(tools):
    for provider_id, tool in tools:
        if tool.is_mutating or tool.name in NOT_READ_ONLY or tool.name in REPORT_FILE_WRITERS:
            continue
        ann = enrich_tool(provider_id, tool).annotations
        assert ann.readOnlyHint is True, tool.name
        assert ann.destructiveHint is False, tool.name


def test_write_sounding_tools_marked_read_only_are_reviewed(tools):
    unreviewed = []
    for provider_id, tool in tools:
        ann = enrich_tool(provider_id, tool).annotations
        if ann.readOnlyHint and set(tool.name.split("_")) & WRITE_WORDS and tool.name not in REVIEWED_READ_ONLY:
            unreviewed.append(tool.name)
    assert not unreviewed, (
        "These tools sound like writes but are annotated read-only. Mark them mutating or "
        f"NOT_READ_ONLY, or review and add them to REVIEWED_READ_ONLY: {unreviewed}"
    )


@pytest.mark.parametrize("profile", ["core", "daily", "full"])
def test_profile_tools_exist_and_are_annotated(profile, tools):
    names = {t.name for _p, t in tools}
    if profile == "core":
        assert set(CORE_TOOLS) <= names
    selected = ToolProfile(name=profile, exclude=DAILY_EXCLUDE if profile == "daily" else (),
                           tools=CORE_TOOLS if profile == "core" else None)
    shown = [(p, t) for p, t in tools if selected.allows(p, None, t.name)]
    assert shown
    for provider_id, tool in shown:
        assert enrich_tool(provider_id, tool).annotations is not None, tool.name
        assert re.fullmatch(r"[a-z0-9_]+", tool.name)


def test_optional_cloud_provider_is_audited(tools):
    providers = {p for p, _t in tools}
    assert {"speckle", "autodesk_data"} <= providers


def test_gate_and_read_only_hint_agree(registry, tools, tmp_path):
    """The approval gate and readOnlyHint never disagree: a tool the gate holds for a plan is not
    read-only, and a read-only tool passes the gate without a plan."""
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")
    wrong = []
    gated_count = 0
    for provider_id, tool in tools:
        gated = _gate_consulted(registry, gate, tool.name)
        gated_count += gated
        if gated and _ann(provider_id, tool).readOnlyHint:
            wrong.append(f"{tool.name}: gated but readOnlyHint=true")
        if not gated and tool.is_mutating:
            wrong.append(f"{tool.name}: is_mutating but the gate let a plain call through")
    assert not wrong, wrong
    assert 100 < gated_count < len(tools) - 100  # both kinds exist; the probe is not one-sided


def test_tools_that_write_named_files_are_not_read_only_and_destructive(tools):
    wrong = []
    for provider_id, tool in tools:
        props = set((tool.input_schema or {}).get("properties", {}))
        if not props & OUTPUT_FILE_PARAMS or tool.name in READS_NAMED_FILE:
            continue
        ann = _ann(provider_id, tool)
        if ann.readOnlyHint or not ann.destructiveHint:
            wrong.append(tool.name)
    assert not wrong, f"These write a named file but are read-only or non-destructive: {wrong}"


def test_overwrite_or_replace_flags_mean_destructive(tools):
    wrong = []
    for provider_id, tool in tools:
        props = set((tool.input_schema or {}).get("properties", {}))
        if props & {"overwrite", "replace"} and not _ann(provider_id, tool).destructiveHint:
            wrong.append(tool.name)
    assert not wrong, wrong


def test_save_tools_are_destructive(tools):
    """Saving replaces the stored copy (document, query, selection, recipe)."""
    for provider_id, tool in tools:
        if "save" in tool.name.split("_"):
            ann = _ann(provider_id, tool)
            assert ann.readOnlyHint is False and ann.destructiveHint is True, tool.name


def test_network_tools_are_open_world_and_auth_tools_are_not_read_only(tools):
    for provider_id, tool in tools:
        ann = _ann(provider_id, tool)
        if provider_id in OPEN_WORLD_PROVIDERS or provider_id.startswith("proxy"):
            assert ann.openWorldHint is True, tool.name
        else:
            assert ann.openWorldHint is False, tool.name
        parts = set(tool.name.split("_"))
        if parts & {"oauth", "checkout"}:
            assert ann.readOnlyHint is False, tool.name


@pytest.mark.parametrize("name,read_only,destructive", [
    ("autodesk_data_oauth_exchange_code", False, False),
    ("autodesk_data_checkout_version", False, False),
    ("param_completeness_heatmap", False, True),
    ("model_health_score", False, True),
    ("ids_validator_validate_ifc", False, True),
    ("sheet_set_qa_check", False, True),
    ("qa_handover_build_report", False, True),
    ("revit_render_check", False, True),
    ("revit_warnings_delta", False, False),
    ("revit_save_document", False, True),
    ("revit_export_ifc", False, True),
    ("exporter_to_sqlite", False, True),
    ("report_generator_export_excel", False, True),
    ("model_inspector_save_query", False, True),
    ("graph_compile", False, True),
    ("revit_list_views", True, False),
])
def test_corrected_annotations(tools, name, read_only, destructive):
    match = [(p, t) for p, t in tools if t.name == name]
    assert match, name
    ann = _ann(*match[0])
    assert (ann.readOnlyHint, ann.destructiveHint) == (read_only, destructive)
