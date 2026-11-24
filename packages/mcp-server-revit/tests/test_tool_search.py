"""search_tools: read-only search over the whole registry, in every profile."""
from __future__ import annotations

import asyncio

import pytest

from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import enrich_tool
from revit_mcp_server.tool_profiles import load_tool_profile


def build(tmp_path, profile="full"):
    registry, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": profile}))
    return registry


def run(registry, **arguments):
    provider = registry.lookup_tool_provider("search_tools")
    return asyncio.run(provider.execute_tool("search_tools", arguments))


@pytest.mark.parametrize("profile", ["full", "daily", "core"])
def test_search_tools_is_visible_and_read_only_in_every_profile(tmp_path, profile):
    registry = build(tmp_path, profile)
    tool = registry.lookup_tool("search_tools")
    assert tool is not None and not tool.is_mutating
    provider = registry.lookup_tool_provider("search_tools")
    assert enrich_tool(provider.get_identity(), tool).annotations.readOnlyHint is True


def test_core_finds_hidden_tool_and_names_the_profile(tmp_path):
    registry = build(tmp_path, "core")
    result = run(registry, query="revit_create_wall", limit=3)
    assert result["current_profile"] == "core"
    top = result["tools"][0]
    assert top["name"] == "revit_create_wall"
    assert top["visible_in_current_profile"] is False
    assert top["profiles"][0] == "full"
    assert "MCP_REVIT_TOOL_PROFILE=" in top["note"]
    assert top["input_schema"]["type"] == "object"


def test_visible_tool_has_no_note_and_lists_profiles(tmp_path):
    registry = build(tmp_path, "core")
    top = run(registry, query="revit_get_context")["tools"][0]
    assert top["name"] == "revit_get_context"
    assert top["visible_in_current_profile"] is True and "note" not in top
    assert top["profiles"] == ["full", "daily", "core"]


def test_search_does_not_leak_human_only_tools(tmp_path):
    registry = build(tmp_path)
    names = {t["name"] for t in run(registry, query="approve reject rollback plan", limit=25)["tools"]}
    assert not names & {"approve_plan", "reject_plan", "rollback_plan"}


def test_ranking_is_deterministic_and_exact_name_wins(tmp_path):
    registry = build(tmp_path)
    first = run(registry, query="wall", limit=25, include_schema=False)
    second = run(registry, query="wall", limit=25, include_schema=False)
    assert first == second
    assert all("input_schema" not in t for t in first["tools"])
    assert run(registry, query="revit_list_levels")["tools"][0]["name"] == "revit_list_levels"
    assert "wall" in first["tools"][0]["name"]


def test_annotations_are_searchable(tmp_path):
    registry = build(tmp_path)
    tools = run(registry, query="destructive delete", limit=10)["tools"]
    assert tools and tools[0]["destructive"] is True


def test_limit_and_bad_input_are_refused(tmp_path):
    registry = build(tmp_path)
    assert len(run(registry, query="revit", limit=2)["tools"]) == 2
    for bad in ({"query": ""}, {"query": "  !! "}, {"query": 5}, {"query": "a", "limit": 0},
                {"query": "a", "limit": 99}, {"query": "a", "limit": True},
                {"query": "a", "include_schema": "yes"}):
        with pytest.raises(ValueError):
            run(registry, **bad)


def test_no_match_returns_empty_list(tmp_path):
    result = run(build(tmp_path), query="zzzqqqxxx")
    assert result["tools"] == [] and result["matched"] == 0 and result["searched"] > 100
