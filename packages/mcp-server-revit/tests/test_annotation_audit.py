"""Audit of MCP behaviour annotations across the whole tool registry.

"Mutating" comes from the registry itself (``tool.is_mutating``, the flag the approval gate
uses), not from a list kept here. Tools that write files (exports, saved queries, rule packs)
are not model-mutating but still are not read-only: they sit in ``NOT_READ_ONLY``.
"""
import re

import pytest

from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import (
    ADDITIVE_NAME_PARTS, ADDITIVE_NAMES, NOT_READ_ONLY, enrich_tool,
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
    "parameter_manager_import_params_csv", # reads a CSV and returns a change proposal
}


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    registry, *_ = build_registry(WorkspaceMonitor([tmp_path_factory.mktemp("ws")]))
    return [(p.get_identity(), t) for p, t in registry.get_tools_with_providers()]


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
        if tool.name in NOT_READ_ONLY or tool.name in HUMAN_ONLY_TOOLS:
            assert ann.readOnlyHint is False, tool.name


def test_read_tools_are_read_only(tools):
    for provider_id, tool in tools:
        if tool.is_mutating or tool.name in NOT_READ_ONLY:
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
