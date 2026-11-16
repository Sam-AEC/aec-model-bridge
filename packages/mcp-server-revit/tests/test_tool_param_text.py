"""Shared parameter text stays short and keeps its rules (rollback, approval, defaults)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    workspace_dir = Path(tmp_path_factory.mktemp("param-ws"))
    registry, approval, job_manager, _m, _w = build_registry(WorkspaceMonitor([workspace_dir]))
    previous = (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager)
    mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = registry, approval, job_manager
    try:
        listed = asyncio.run(mcp_server.list_tools())
    finally:
        mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = previous
    return {t.name: t for t in listed}


def _props(tools, key):
    return [
        (t.name, t.inputSchema["properties"][key])
        for t in tools.values()
        if key in t.inputSchema.get("properties", {})
    ]


def test_rollback_dry_run_text_is_one_short_variant(tools):
    rollback = [(n, p["description"]) for n, p in _props(tools, "dry_run") if "roll" in p["description"]]
    assert len(rollback) >= 15
    assert len({d for _, d in rollback}) == 1
    text = rollback[0][1]
    assert len(text) <= 230
    for phrase in ("Default false", "roll everything back", "nothing is written", "would_change", "approved plan"):
        assert phrase in text


def test_on_error_text_keeps_abort_default_and_skip(tools):
    texts = {p["description"] for _, p in _props(tools, "on_error")}
    shared = [t for t in texts if t.startswith("abort (default): first failure rolls everything back.")]
    assert len(shared) == 1
    assert "skip: keep what worked" in shared[0] and len(shared[0]) <= 110


def test_default_limit_text_keeps_default_and_maximum(tools):
    texts = {p["description"] for _, p in _props(tools, "limit") if "default 50" in p["description"]}
    assert len(texts) == 1
    only = texts.pop()
    assert "max 500" in only and "detail file" in only and len(only) <= 100


def test_status_labels_text_is_collapsed_but_names_every_key(tools):
    for name, prop in _props(tools, "status_labels"):
        text = prop["description"]
        for key in ("proposed", "requested", "approved", "rejected", "built"):
            assert key in text, name
        assert "Goedgekeurd" in text
        assert len(str(prop)) < 450, name
        assert set(prop["properties"]) == {"proposed", "requested", "approved", "rejected", "built"}


def test_plan_id_text_is_untouched(tools):
    for t in tools.values():
        plan_id = t.inputSchema.get("properties", {}).get("plan_id")
        if plan_id and "Approved plan ID" in plan_id.get("description", ""):
            assert plan_id["description"] == "Approved plan ID; see the server approval instructions."


def test_tag_text_keeps_the_rerun_and_prefix_rules(tools):
    texts = {p["description"] for _, p in _props(tools, "tag")}
    assert any(t.startswith("Comments prefix of one build phase") for t in texts)
    assert any("Re-running with the same tag and id replaces only what this tool made" in t for t in texts)


def test_sibling_hints_are_short_and_name_real_tools(tools):
    import re

    from revit_mcp_server.tool_metadata import SIBLING_HINTS

    assert len(SIBLING_HINTS) >= 25
    for name, hint in SIBLING_HINTS.items():
        assert name in tools, name
        assert hint.startswith("Use ") and hint.endswith("."), name
        assert len(hint) <= 120, (name, len(hint))
        assert tools[name].description.endswith(hint), name
        for ref in re.findall(r"\brevit_\w+", hint):
            assert ref in tools, (name, ref)


def test_sibling_hints_keep_existing_approval_text(tools):
    # Appending a hint must leave the original description (and its approval wording) intact.
    assert "needs an approved plan" in tools["revit_set_view_templates"].description
    for name in ("revit_make_sheet", "revit_make_schedule"):
        assert "under an approved action" in tools[name].description
