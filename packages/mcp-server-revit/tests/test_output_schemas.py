"""Structured tool output: the read tools in OUTPUT_SCHEMAS advertise an outputSchema and return
structuredContent that validates against it, next to the unchanged text result (mock mode)."""
import asyncio
import json

import jsonschema
import pytest
from mcp import types
from mcp.types import CallToolResult

from revit_mcp_server import mcp_server
from revit_mcp_server.output_schemas import OUTPUT_SCHEMAS, structured_for
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import enrich_tool, is_read_only_tool
from revit_mcp_server.tool_profiles import CORE_TOOLS

SNAP = "$SNAP"
# Mock-mode arguments for every tool with an output schema. "$SNAP" is replaced by a snapshot id.
CALLS = {
    "revit_get_context": {},
    "snapshot_take": {},
    "snapshot_query": {"snapshot_id": SNAP, "filter": {"category": "OST_Walls"}},
    "snapshot_compute": {"snapshot_id": SNAP, "steps": [
        {"name": "by_cat", "from": "elements", "group_by": ["category"], "aggregate": {"n": "count"}}]},
    "snapshot_diff": {"snapshot_a_id": SNAP, "snapshot_b_id": SNAP},
    "search_tools": {"query": "wall"},
    "model_inspector_summarize_model": {},
    "model_bloat_audit": {},
    "revit_api_lookup": {"query": "Wall"},
    "qaqc_checker_list_rules": {},
    "qaqc_checker_list_issues": {},
    "qaqc_checker_list_rule_packs": {},
    "list_pending_plans": {},
    "policy_show": {},
    "module_list_commands": {},
    "revit_review": {},
    "revit_check_levels_grids": {},
    "revit_system_report": {"tag": "mock"},
    "revit_list_views_sheets_schedules": {},
    "revit_cleanup_audit": {},
}


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    ws = tmp_path_factory.mktemp("structured-ws")
    saved = (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager,
             mcp_server.workspace_monitor)
    registry, approval, jobs, _modules, monitor = build_registry(WorkspaceMonitor([ws]))
    mcp_server.registry, mcp_server.approval_provider = registry, approval
    mcp_server.job_manager, mcp_server.workspace_monitor = jobs, monitor
    try:
        yield registry
    finally:
        (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager,
         mcp_server.workspace_monitor) = saved


@pytest.fixture(scope="module")
def snapshot_id(server):
    result = asyncio.run(mcp_server.call_tool("snapshot_take", {}))
    return result.structuredContent["snapshot_id"]


def _args(name, snapshot_id):
    return json.loads(json.dumps(CALLS[name]).replace(SNAP, snapshot_id))


def test_twenty_read_tools_have_schemas_and_test_calls():
    assert len(OUTPUT_SCHEMAS) == 20
    assert set(CALLS) == set(OUTPUT_SCHEMAS)


@pytest.mark.parametrize("name", sorted(OUTPUT_SCHEMAS))
def test_schema_is_valid_json_schema(name):
    schema = OUTPUT_SCHEMAS[name]
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object"


def test_schema_tools_are_reads_and_mostly_core(server):
    for name in OUTPUT_SCHEMAS:
        tool = server.lookup_tool(name)
        assert tool is not None, name
        assert not tool.is_mutating, name
    # Most come from the core profile; the rest are approval, search and listing reads.
    assert len(set(OUTPUT_SCHEMAS) & set(CORE_TOOLS)) >= 13


def test_list_tools_advertises_output_schema_only_for_listed_tools(server):
    tools = asyncio.run(mcp_server.list_tools())
    with_schema = {t.name: t.outputSchema for t in tools if t.outputSchema is not None}
    assert with_schema == OUTPUT_SCHEMAS


@pytest.mark.parametrize("name", sorted(OUTPUT_SCHEMAS))
def test_mock_call_returns_valid_structured_content_and_same_text(server, snapshot_id, name):
    result = asyncio.run(mcp_server.call_tool(name, _args(name, snapshot_id)))
    assert isinstance(result, CallToolResult), name
    assert not result.isError, result.content[0].text
    assert result.structuredContent is not None, name
    jsonschema.validate(instance=result.structuredContent, schema=OUTPUT_SCHEMAS[name])
    text = result.content[0].text
    prefix = f"✓ {name} executed successfully\n\nResult:\n"
    assert text.startswith(prefix)
    body = text[len(prefix):]
    # The structured value is the JSON the text shows, and the text keeps its usual formatting.
    assert json.loads(body) == result.structuredContent
    read_only = is_read_only_tool(name, server.lookup_tool(name))
    if read_only:
        assert body == json.dumps(json.loads(body), separators=(",", ":")) or "truncated" in body
    else:
        assert body == json.dumps(json.loads(body), indent=2)


@pytest.mark.parametrize("name", ["revit_get_context", "snapshot_compute", "search_tools", "revit_review"])
def test_sdk_handler_accepts_structured_output(server, snapshot_id, name):
    """Through the real SDK request handler (tool cache, input validation, result handling) the
    result is still a success with schema-valid structuredContent."""
    handler = mcp_server.app.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=_args(name, snapshot_id)),
    )
    result = asyncio.run(handler(request)).root
    assert not result.isError, result.content[0].text
    jsonschema.validate(instance=result.structuredContent, schema=OUTPUT_SCHEMAS[name])


def test_queued_job_for_schema_tool_is_not_an_sdk_error(server):
    handler = mcp_server.app.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="revit_get_context", arguments={"run_async": True}),
    )
    result = asyncio.run(handler(request)).root
    assert not result.isError, result.content[0].text
    assert "queued successfully" in result.content[0].text
    jsonschema.validate(instance=result.structuredContent, schema=OUTPUT_SCHEMAS["revit_get_context"])
    assert "queued" in result.structuredContent["structured_fallback"]["reason"]


def test_tools_without_schema_keep_plain_text_results(server):
    result = asyncio.run(mcp_server.call_tool("revit_list_views", {}))
    assert isinstance(result, list)
    assert result[0].text.startswith("✓ revit_list_views executed successfully")


def test_value_that_does_not_match_gets_a_valid_fallback():
    bad = structured_for("snapshot_query", {"snapshot_id": 5, "extra": "kept"})
    jsonschema.validate(instance=bad, schema=OUTPUT_SCHEMAS["snapshot_query"])
    assert bad["extra"] == "kept" and bad["snapshot_id"] == ""
    assert bad["structured_fallback"]["filled"] == ["snapshot_id", "matches_count", "elements"]
    listed = structured_for("snapshot_query", ["not", "an", "object"])
    jsonschema.validate(instance=listed, schema=OUTPUT_SCHEMAS["snapshot_query"])
    assert listed["result"] == ["not", "an", "object"]
    assert structured_for("revit_list_views", {"views": []}) is None
    good = {"snapshot_id": "s", "matches_count": 0, "elements": []}
    assert structured_for("snapshot_query", good) == good


def test_fallback_keeps_valid_keys_and_fills_nested_required():
    value = {"ok": True, "tool": "revit_get_context", "server": {"dev_mode": "yes"}, "warnings": "no"}
    out = structured_for("revit_get_context", value)
    jsonschema.validate(instance=out, schema=OUTPUT_SCHEMAS["revit_get_context"])
    assert out["ok"] is True and out["tool"] == "revit_get_context"
    assert out["server"] == {"approval_mode": "", "plans_required": False}
    assert set(out["structured_fallback"]["filled"]) == {"server.approval_mode", "server.plans_required"}
    assert set(out["structured_fallback"]["dropped"]) == {"server.dev_mode", "warnings"}


@pytest.mark.parametrize("name", sorted(OUTPUT_SCHEMAS))
def test_every_schema_allows_extra_keys_and_has_a_valid_empty_fallback(name):
    schema = OUTPUT_SCHEMAS[name]
    assert schema.get("additionalProperties") is True
    for value in ({}, None, [], "text", {"unexpected": {"shape": 1}}):
        jsonschema.validate(instance=structured_for(name, value), schema=schema)


def test_sdk_client_accepts_a_result_that_does_not_match_the_schema(server, monkeypatch):
    """Through the SDK's in-memory client session, which validates structuredContent against the
    advertised outputSchema: an unexpected result shape, a queued job and a cursor-less reply do not
    raise in the client."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    provider = server.lookup_tool_provider("search_tools")
    real = provider.execute_tool

    async def odd(name, arguments):
        if name == "search_tools":
            return {"matched": "many", "surprise": [1, 2]}
        return await real(name, arguments)

    monkeypatch.setattr(provider, "execute_tool", odd)
    # A JobManager binds to the first event loop that uses it; this test runs its own loop.
    from revit_mcp_server.jobs import JobManager

    monkeypatch.setattr(mcp_server, "job_manager", JobManager())

    async def run():
        async with create_connected_server_and_client_session(mcp_server.app) as client:
            odd_reply = await client.call_tool("search_tools", {"query": "wall"})
            queued = await client.call_tool("revit_get_context", {"run_async": True})
            normal = await client.call_tool("snapshot_take", {})
            return odd_reply, queued, normal

    odd_reply, queued, normal = anyio.run(run)
    assert not odd_reply.isError
    assert odd_reply.structuredContent["surprise"] == [1, 2]
    assert odd_reply.structuredContent["structured_fallback"]["filled"] == ["matched", "tools"]
    assert '"matched": "many"' in odd_reply.content[0].text or '"matched":"many"' in odd_reply.content[0].text
    assert not queued.isError and "structured_fallback" in queued.structuredContent
    assert not normal.isError and "structured_fallback" not in normal.structuredContent


def test_failed_call_keeps_error_result(server):
    result = asyncio.run(mcp_server.call_tool("snapshot_query", {"snapshot_id": "missing", "filter": {}}))
    assert result.isError


def test_enrich_tool_copies_the_schema(server):
    provider = server.lookup_tool_provider("search_tools")
    tool = enrich_tool(provider.get_identity(), server.lookup_tool("search_tools"))
    tool.outputSchema["properties"].clear()
    assert OUTPUT_SCHEMAS["search_tools"]["properties"]
