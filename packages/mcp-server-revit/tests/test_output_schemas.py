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
    assert result.structuredContent is None


def test_tools_without_schema_keep_plain_text_results(server):
    result = asyncio.run(mcp_server.call_tool("revit_list_views", {}))
    assert isinstance(result, list)
    assert result[0].text.startswith("✓ revit_list_views executed successfully")


def test_value_that_does_not_match_is_left_out():
    assert structured_for("snapshot_query", {"snapshot_id": 5}) is None
    assert structured_for("snapshot_query", ["not", "an", "object"]) is None
    assert structured_for("revit_list_views", {"views": []}) is None
    good = {"snapshot_id": "s", "matches_count": 0, "elements": []}
    assert structured_for("snapshot_query", good) == good


def test_failed_call_keeps_error_result(server):
    result = asyncio.run(mcp_server.call_tool("snapshot_query", {"snapshot_id": "missing", "filter": {}}))
    assert result.isError


def test_enrich_tool_copies_the_schema(server):
    provider = server.lookup_tool_provider("search_tools")
    tool = enrich_tool(provider.get_identity(), server.lookup_tool("search_tools"))
    tool.outputSchema["properties"].clear()
    assert OUTPUT_SCHEMAS["search_tools"]["properties"]
