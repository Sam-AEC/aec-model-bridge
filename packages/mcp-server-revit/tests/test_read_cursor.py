"""Cursors for trimmed read results (#274) and saved-result links for very large ones (#283)."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from revit_mcp_server import mcp_resources, mcp_server, read_cursor
from revit_mcp_server.read_cursor import STORE, Context, CursorError, CursorStore, binding
from revit_mcp_server.result_presentation import DEFAULT_MAX_CHARS, next_page, result_json, split_response_options


def _rows(n, width=40):
    return [{"id": i, "name": "x" * width} for i in range(n)]


@pytest.fixture(autouse=True)
def _clean_store(monkeypatch):
    monkeypatch.delenv(read_cursor.ENV_MAX_CHARS, raising=False)
    monkeypatch.delenv(read_cursor.ENV_TTL, raising=False)
    STORE.clear()
    yield
    STORE.clear()


@pytest.fixture
def server(monkeypatch, tmp_path):
    state = SimpleNamespace(result={"elements": _rows(2000), "category": "Walls"}, mutating=False, runs=0)

    class Provider:
        async def execute_tool(self, name, arguments):
            state.runs += 1
            return state.result

    class Registry:
        def lookup_tool_provider(self, name):
            return Provider()

        def lookup_tool(self, name):
            return SimpleNamespace(name=name, is_mutating=state.mutating)

    monkeypatch.setattr(mcp_server, "registry", Registry())
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=None))
    monkeypatch.setattr(mcp_server, "workspace_monitor", SimpleNamespace(allowed_directories=[tmp_path]))
    return state


def _call(name, arguments):
    return asyncio.run(mcp_server.call_tool(name, arguments))


def _content(answer):
    # Tools with an outputSchema answer with a CallToolResult; the others with a content list.
    return getattr(answer, "content", answer)


def _body(answer):
    return json.loads(_content(answer)[0].text.split("Result:\n", 1)[1])


def _raw(answer):
    return _content(answer)[0].text.split("Result:\n", 1)[1]


# ---- truncation carries a cursor, paging reaches the end ------------------------------------------
def test_trimmed_answer_carries_a_cursor_and_counts(server):
    first = _body(_call("revit_list_elements", {"category": "Walls"}))
    assert first["truncated"] is True and first["total"] == 2000
    assert first["returned"] == len(first["elements"]) < 2000
    assert first["cursor"].startswith("rc") and "response_options.cursor" in first["next"]
    assert first["category"] == "Walls"


def test_paging_to_the_end_returns_every_row_once_within_the_budget(server):
    args = {"category": "Walls"}
    answer = _call("revit_list_elements", {**args, "response_options": {"max_chars": 4000}})
    assert len(_raw(answer)) <= 4000
    page = _body(answer)
    rows, runs = list(page["elements"]), server.runs
    while page.get("cursor"):
        answer = _call("revit_list_elements", {**args, "response_options": {"max_chars": 4000, "cursor": page["cursor"]}})
        assert len(_raw(answer)) <= 4000
        assert "not run again" in _content(answer)[0].text
        page = _body(answer)
        assert page["offset"] == len(rows) and page["total"] == 2000
        rows.extend(page["elements"])
    assert page["truncated"] is False and "cursor" not in page
    assert rows == server.result["elements"]
    assert server.runs == runs  # pages came from memory, the tool ran once


def test_a_cursor_can_be_repeated_and_page_size_can_change(server):
    first = _body(_call("revit_list_elements", {}))
    again = {"response_options": {"cursor": first["cursor"], "max_chars": 2000}}
    a, b = _body(_call("revit_list_elements", again)), _body(_call("revit_list_elements", again))
    assert a == b
    whole = _body(_call("revit_list_elements", {"response_options": {"cursor": first["cursor"], "max_chars": 0}}))
    assert whole["truncated"] is False and len(whole["elements"]) == 2000 - first["returned"]


def test_short_results_carry_no_cursor(server):
    server.result = {"elements": _rows(3)}
    assert _raw(_call("revit_list_elements", {})) == json.dumps(server.result, separators=(",", ":"))
    assert not STORE._entries


def test_snapshot_compute_rows_page_end_to_end(tmp_path, monkeypatch):
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor
    from revit_mcp_server.semantic import engine

    monkeypatch.setenv("MCP_REVIT_MODE", "mock")
    snap = engine.generate_mock_snapshot()
    base = snap.elements[0]
    snap.elements = [base.model_copy(update={"uid": f"e{i}", "element_id": 1000 + i}) for i in range(600)]
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snap.snapshot_id}.json").write_text(
        json.dumps(snap.model_dump(by_alias=True, mode="json")), encoding="utf-8")
    registry, approval, jobs, _, monitor = build_registry(WorkspaceMonitor([tmp_path]))
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "workspace_monitor", monitor)
    try:
        args = {"snapshot_id": snap.snapshot_id, "max_rows": 1000,
                "steps": [{"select": ["uid", "element_id", "category"]}]}
        page = _body(_call("snapshot_compute", {**args, "response_options": {"max_chars": 3000}}))
        assert page["truncated"] is True and page["truncated_field"] == "rows" and page["row_count"] == 600
        rows = list(page["rows"])
        while page.get("cursor"):
            page = _body(_call("snapshot_compute", {**args, "response_options": {"max_chars": 3000, "cursor": page["cursor"]}}))
            rows.extend(page["rows"])
        assert [r["uid"] for r in rows] == [f"e{i}" for i in range(600)]
    finally:
        asyncio.run(jobs.shutdown(cancel_running=True))


def test_nested_and_top_level_lists_page_in_their_own_shape(server):
    server.result = {"data": {"rows": _rows(2000)}}
    first = _body(_call("revit_get_warnings", {}))
    assert first["truncated_field"] == "data.rows"
    nxt = _body(_call("revit_get_warnings", {"response_options": {"cursor": first["cursor"]}}))
    assert nxt["data"]["rows"][0] == server.result["data"]["rows"][len(first["data"]["rows"])]

    server.result = _rows(2000)
    first = _body(_call("revit_get_warnings", {}))
    nxt = _body(_call("revit_get_warnings", {"response_options": {"cursor": first["cursor"]}}))
    assert nxt["items"][0] == server.result[first["returned"]]


def test_provider_cursor_key_is_not_overwritten(server):
    server.result = {"cursor": "provider-own", "elements": _rows(2000)}
    first = _body(_call("revit_get_warnings", {}))
    assert first["cursor"] == "provider-own" and first["truncation"]["cursor"].startswith("rc")


# ---- refusals ---------------------------------------------------------------------------------------
def test_expired_cursor_is_refused_with_a_plain_error(server, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(STORE, "_clock", lambda: now[0])
    first = _body(_call("revit_list_elements", {}))
    now[0] += read_cursor.DEFAULT_TTL + 1
    answer = _call("revit_list_elements", {"response_options": {"cursor": first["cursor"]}})
    assert answer.isError and answer.structuredContent["error"]["kind"] == "invalid_cursor"
    assert "expired" in answer.content[0].text and "without a cursor" in answer.content[0].text


def test_ttl_comes_from_the_environment(server, monkeypatch):
    monkeypatch.setenv(read_cursor.ENV_TTL, "5")
    now = [0.0]
    monkeypatch.setattr(STORE, "_clock", lambda: now[0])
    first = _body(_call("revit_list_elements", {}))
    now[0] = 4.0
    assert not getattr(_call("revit_list_elements", {"response_options": {"cursor": first["cursor"]}}), "isError", False)
    now[0] = 6.0
    assert _call("revit_list_elements", {"response_options": {"cursor": first["cursor"]}}).isError


@pytest.mark.parametrize("name,arguments", [
    ("revit_list_elements", {"category": "Doors"}),
    ("revit_list_views", {"category": "Walls"}),
    ("revit_list_elements", {"category": "Walls", "response_options": {"fields": ["elements.id"]}}),
])
def test_cursor_for_another_call_is_refused(server, name, arguments):
    first = _body(_call("revit_list_elements", {"category": "Walls"}))
    options = {**arguments.get("response_options", {}), "cursor": first["cursor"]}
    answer = _call(name, {**{k: v for k, v in arguments.items() if k != "response_options"}, "response_options": options})
    assert answer.isError and "belongs to another call" in answer.content[0].text


@pytest.mark.parametrize("cursor", ["nope", "rc" + "0" * 24 + "-1", "rc" + "z" * 24 + "-1"])
def test_unknown_or_malformed_cursor_is_refused(server, cursor):
    answer = _call("revit_list_elements", {"response_options": {"cursor": cursor}})
    assert answer.isError and answer.structuredContent["error"]["kind"] == "invalid_cursor"


def test_cursor_past_the_end_is_refused(server):
    first = _body(_call("revit_list_elements", {}))
    key = first["cursor"][2:26]
    answer = _call("revit_list_elements", {"response_options": {"cursor": f"rc{key}-99999"}})
    assert answer.isError and "past the end" in answer.content[0].text


def test_cursor_option_is_validated_and_not_offered_to_plan_tools():
    for bad in (1, "", "x" * 65, None):
        with pytest.raises(ValueError):
            split_response_options("revit_list_elements", {"response_options": {"cursor": bad}})
    with pytest.raises(ValueError):
        split_response_options("plan_actions", {"response_options": {"cursor": "rc1"}})
    untouched = {"response_options": {"cursor": "rc1"}}
    assert split_response_options("revit_create_wall", untouched, read_only=False)[0] is untouched


def test_write_tools_never_get_a_cursor(server):
    server.mutating = True
    body = _raw(_call("revit_create_wall", {}))
    assert "cursor" not in body and not STORE._entries


# ---- the store ----------------------------------------------------------------------------------------
def test_store_caps_entries_and_total_size():
    store = CursorStore(max_entries=3, max_total_chars=100)
    ctx = Context("t", "b")
    keys = [store.put(ctx, ("rows",), [1], 10) for _ in range(5)]
    assert list(store._entries) == keys[-3:]
    store.put(ctx, ("rows",), [1], 95)
    assert len(store._entries) == 1  # oldest dropped until the total fits
    with pytest.raises(CursorError, match="expired"):
        store.get(read_cursor.make_cursor(keys[0], 0), "t", "b")


def test_binding_covers_tool_arguments_and_fields_only():
    assert binding("t", {"a": 1, "b": 2}, None) == binding("t", {"b": 2, "a": 1}, None)
    assert binding("t", {"a": 1}, None) != binding("t", {"a": 2}, None)
    assert binding("t", {"a": 1}, None) != binding("u", {"a": 1}, None)
    assert binding("t", {"a": 1}, ["x"]) != binding("t", {"a": 1}, None)


def test_result_json_without_context_keeps_the_old_shape():
    out = json.loads(result_json({"elements": _rows(2000)}, {}, read_only=True))
    assert out["truncated"] is True and "cursor" not in out and "resource_uri" not in out


def test_server_wide_default_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv(read_cursor.ENV_MAX_CHARS, "3000")
    assert len(result_json({"elements": _rows(2000)}, {}, read_only=True)) <= 3000
    monkeypatch.setenv(read_cursor.ENV_MAX_CHARS, "0")
    assert "truncated" not in result_json({"elements": _rows(2000)}, {}, read_only=True)
    monkeypatch.setenv(read_cursor.ENV_MAX_CHARS, "junk")
    assert len(result_json({"elements": _rows(2000)}, {}, read_only=True)) <= DEFAULT_MAX_CHARS


def test_next_page_needs_a_live_cursor():
    with pytest.raises(CursorError):
        next_page({"cursor": "rc" + "1" * 24 + "-0"}, Context("t", "b"))


# ---- very large results: saved under the workspace and linked (#283) ---------------------------------
def test_list_too_large_for_memory_is_saved_and_linked(server, tmp_path, monkeypatch):
    monkeypatch.setattr(read_cursor, "MAX_ENTRY_CHARS", 1000)
    answer = _call("revit_list_elements", {"category": "Walls"})
    body = _body(answer)
    assert body["truncated"] is True and "cursor" not in body
    uri = body["resource_uri"]
    assert uri.startswith("aec://result/r") and len(_raw(answer)) <= DEFAULT_MAX_CHARS
    assert _content(answer)[1].type == "resource_link" and str(_content(answer)[1].uri) == uri
    saved = list((tmp_path / "results").glob("*.json"))
    assert len(saved) == 1 and saved[0].parent == tmp_path / "results"
    text = mcp_resources.read_resource(uri, tmp_path, None)
    assert json.loads(text) == server.result


@pytest.mark.parametrize("bad", ["../x", "r" + "0" * 23, "R" + "0" * 24, "snap1"])
def test_saved_result_ids_are_validated(tmp_path, bad):
    with pytest.raises(mcp_resources.ResourceError):
        mcp_resources.read_resource(f"aec://result/{bad}", tmp_path, None)


def test_missing_saved_result_is_a_plain_error(tmp_path):
    with pytest.raises(mcp_resources.ResourceError, match="not found"):
        mcp_resources.read_resource("aec://result/r" + "0" * 24, tmp_path, None)


def test_saved_results_are_pruned_to_the_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(read_cursor, "MAX_SAVED_RESULTS", 2)
    uris = [read_cursor.save_result(tmp_path, {"n": i}) for i in range(4)]
    assert len(list((tmp_path / "results").glob("*.json"))) == 2
    assert json.loads(mcp_resources.read_resource(uris[-1], tmp_path, None)) == {"n": 3}


def test_without_a_workspace_a_huge_list_has_no_cursor_or_link(monkeypatch):
    monkeypatch.setattr(read_cursor, "MAX_ENTRY_CHARS", 1000)
    ctx = Context("t", "b")
    out = json.loads(result_json({"elements": _rows(2000)}, {}, read_only=True, cursor=ctx))
    assert out["truncated"] is True and "cursor" not in out and "resource_uri" not in out


def test_cursor_page_for_a_tool_with_an_output_schema_is_a_call_tool_result():
    """The SDK rejects a bare content list from a tool that declares an outputSchema."""
    from mcp.types import CallToolResult

    from revit_mcp_server.output_schemas import output_schema_for

    assert output_schema_for("snapshot_compute") is not None
    answer = mcp_server._text_only("snapshot_compute", "✓ snapshot_compute next part")
    assert isinstance(answer, CallToolResult) and answer.structuredContent is None


def test_strict_read_tools_accept_a_cursor_in_their_input_schema():
    """#274 review: the SDK validates input against the schema before response_options is split off,
    so a read-only tool with additionalProperties: false must list response_options.cursor."""
    import jsonschema
    from types import SimpleNamespace

    from revit_mcp_server import tool_metadata

    schema = {"type": "object", "additionalProperties": False,
              "properties": {"ids": {"type": "array", "items": {"type": "integer"}}}}
    read_tool = SimpleNamespace(is_mutating=False)
    tool_metadata.add_cursor_option("revit_inspect_elements", read_tool, schema)
    jsonschema.validate({"ids": [1], "response_options": {"cursor": "abc"}}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"ids": [1], "response_options": {"other": 1}}, schema)

    write_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    tool_metadata.add_cursor_option("revit_delete_elements", SimpleNamespace(is_mutating=True), write_schema)
    assert "response_options" not in write_schema["properties"], "write tools take no cursor"
