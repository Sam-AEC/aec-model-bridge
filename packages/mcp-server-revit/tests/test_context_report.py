"""context_report (read-only tool-list cost report) and the always-loaded set for deferred loading."""
from __future__ import annotations

import asyncio
import json

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import ALWAYS_LOAD_META_KEY, enrich_tool
from revit_mcp_server.tool_profiles import ALWAYS_LOADED_TOOLS, load_tool_profile


def build(tmp_path, profile="full"):
    registry, approval, jobs, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": profile}))
    return registry, approval, jobs


def report(registry, **arguments):
    provider = registry.lookup_tool_provider("context_report")
    return asyncio.run(provider.execute_tool("context_report", arguments))


@pytest.mark.parametrize("profile", ["full", "daily", "core"])
def test_context_report_is_visible_and_read_only_in_every_profile(tmp_path, profile):
    registry, *_ = build(tmp_path, profile)
    tool = registry.lookup_tool("context_report")
    assert tool is not None and not tool.is_mutating
    ann = enrich_tool(registry.lookup_tool_provider("context_report").get_identity(), tool).annotations
    assert ann.readOnlyHint is True and ann.destructiveHint is False and ann.openWorldHint is False


@pytest.mark.parametrize("profile", ["full", "core"])
def test_context_report_matches_mcp_list_tools(tmp_path, monkeypatch, profile):
    registry, approval, jobs = build(tmp_path, profile)
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "job_manager", jobs)
    listed = asyncio.run(mcp_server.list_tools())
    sizes = {t.name: len(t.model_dump_json(by_alias=True, exclude_none=True)) for t in listed}

    out = report(registry)
    assert out["profile"] == profile
    assert out["listed_tools"] == len(listed)
    assert out["chars"] == sum(sizes.values())
    assert out["approx_tokens"] == round(out["chars"] / 4)
    top = out["largest_tools"]
    assert len(top) == 10
    assert [row["chars"] for row in top] == sorted(sizes.values(), reverse=True)[:10]
    assert all(sizes[row["name"]] == row["chars"] for row in top)
    assert out["always_loaded"]["tools"] == len(ALWAYS_LOADED_TOOLS)
    assert out["always_loaded"]["chars"] == sum(sizes[n] for n in ALWAYS_LOADED_TOOLS)
    assert out["tips"] and all(isinstance(tip, str) for tip in out["tips"])
    json.dumps(out)  # plain JSON


def test_core_is_smaller_and_tips_differ(tmp_path):
    full = report(build(tmp_path, "full")[0])
    core = report(build(tmp_path, "core")[0])
    assert core["listed_tools"] < full["listed_tools"] and core["chars"] < full["chars"]
    assert any("MCP_REVIT_TOOL_PROFILE=core" in tip for tip in full["tips"])
    assert not any("MCP_REVIT_TOOL_PROFILE=core" in tip for tip in core["tips"])


def test_context_report_refuses_arguments(tmp_path):
    registry, *_ = build(tmp_path)
    with pytest.raises(ValueError, match="no arguments"):
        report(registry, verbose=True)


def test_context_report_via_call_tool(tmp_path, monkeypatch):
    registry, approval, jobs = build(tmp_path, "core")
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "job_manager", jobs)
    out = asyncio.run(mcp_server.call_tool("context_report", {}))
    text = out[0].text if isinstance(out, list) else out.content[0].text
    assert '"profile"' in text and "core" in text


# ---- always-loaded set (docs/deferred-tool-loading.md) -------------------------------

PINNED = (
    "revit_get_context", "snapshot_take", "snapshot_compute", "search_tools",
    "context_report", "plan_actions", "execute_plan", "list_pending_plans",
)


def test_always_loaded_list_is_pinned():
    assert ALWAYS_LOADED_TOOLS == PINNED


@pytest.mark.parametrize("profile", ["full", "daily", "core"])
def test_always_loaded_tools_exist_and_are_visible_in_every_profile(tmp_path, profile):
    registry, *_ = build(tmp_path, profile)
    for name in ALWAYS_LOADED_TOOLS:
        assert registry.lookup_tool(name) is not None, name


def test_only_always_loaded_tools_carry_the_meta_flag(tmp_path, monkeypatch):
    registry, approval, jobs = build(tmp_path)
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "job_manager", jobs)
    flagged = set()
    for tool in asyncio.run(mcp_server.list_tools()):
        wire = json.loads(tool.model_dump_json(by_alias=True, exclude_none=True))
        if wire.get("_meta", {}).get(ALWAYS_LOAD_META_KEY) is True:
            flagged.add(tool.name)
    assert flagged == set(ALWAYS_LOADED_TOOLS)


def test_deferred_doc_lists_the_same_set():
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[3] / "docs" / "deferred-tool-loading.md").read_text(encoding="utf-8")
    for name in ALWAYS_LOADED_TOOLS:
        assert f"`{name}`" in doc, f"docs/deferred-tool-loading.md does not name {name}"
