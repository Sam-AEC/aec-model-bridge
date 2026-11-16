"""Read-only results are compact by default and capped; plans, proofs and approvals are never touched."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.result_presentation import (
    DEFAULT_MAX_CHARS, result_json, split_response_options,
)
from revit_mcp_server.tool_metadata import enrich_tool, is_read_only_tool
from revit_mcp_server.providers.base import ProviderTool


def _rows(n, width=40):
    return [{"id": i, "name": "x" * width} for i in range(n)]


# ---- A: compact by default for read-only results -------------------------------------------------
def test_read_only_default_is_compact_and_opt_out_is_indented():
    result = {"views": [{"id": 1, "name": "Plan"}]}
    assert result_json(result, {}, read_only=True) == json.dumps(result, separators=(",", ":"))
    assert result_json(result, {"compact": False}, read_only=True) == json.dumps(result, indent=2)


def test_non_read_only_default_stays_indented_and_compact_stays_opt_in():
    result = {"a": [1, 2]}
    assert result_json(result, {}) == json.dumps(result, indent=2)
    assert result_json(result, {"compact": True}) == json.dumps(result, separators=(",", ":"))


def test_read_only_flag_follows_the_tool_annotations():
    def tool(name, mutating):
        return SimpleNamespace(name=name, is_mutating=mutating)
    assert is_read_only_tool("revit_list_views", tool("revit_list_views", False))
    assert not is_read_only_tool("revit_create_wall", tool("revit_create_wall", True))
    assert not is_read_only_tool("unknown", None)
    for name in ("plan_actions", "execute_plan", "list_pending_plans", "get_proof_bundle", "plan_revert",
                 "revit_get_result", "revit_job_status", "job_status", "approve_plan"):
        assert not is_read_only_tool(name, tool(name, False)), name


# ---- B: the cap -----------------------------------------------------------------------------------
def test_short_results_are_byte_identical_with_the_cap_active():
    result = {"elements": _rows(5)}
    assert result_json(result, {}, read_only=True) == json.dumps(result, separators=(",", ":"))


def test_large_list_is_trimmed_to_valid_json_with_markers():
    result = {"elements": _rows(2000), "count": 2000, "category": "Walls"}
    before = copy.deepcopy(result)
    text = result_json(result, {}, read_only=True)
    assert result == before
    assert len(text) <= DEFAULT_MAX_CHARS
    out = json.loads(text)
    assert out["truncated"] is True
    assert out["total"] == 2000
    assert out["returned"] == len(out["elements"]) < 2000
    assert out["elements"] == before["elements"][: out["returned"]]
    assert out["count"] == 2000 and out["category"] == "Walls"
    assert "limit/offset/count_only/fields" in out["hint"]


def test_max_chars_option_and_zero_disables_the_cap():
    result = {"elements": _rows(2000)}
    small = result_json(result, {"max_chars": 1000}, read_only=True)
    assert len(small) <= 1000 and json.loads(small)["truncated"] is True
    full = json.loads(result_json(result, {"max_chars": 0}, read_only=True))
    assert full == result


def test_largest_list_is_trimmed_first_and_other_lists_kept_when_they_fit():
    result = {"small": _rows(3), "big": _rows(2000)}
    out = json.loads(result_json(result, {}, read_only=True))
    assert out["small"] == result["small"]
    assert out["truncated_field"] == "big" and out["total"] == 2000


def test_several_big_lists_report_each_trim():
    result = {"a": _rows(1000), "b": _rows(1000)}
    out = json.loads(result_json(result, {"max_chars": 5000}, read_only=True))
    assert len(json.dumps(out, separators=(",", ":"))) <= 5000
    assert out["also_trimmed"]["b"]["total"] == 1000 or out["truncated_field"] == "b"


def test_nested_list_and_top_level_list_are_trimmed():
    nested = json.loads(result_json({"data": {"rows": _rows(2000)}}, {}, read_only=True))
    assert nested["truncated"] is True and nested["truncated_field"] == "data.rows"
    top = json.loads(result_json(_rows(2000), {}, read_only=True))
    assert top["truncated"] is True and top["total"] == 2000 and len(top["items"]) == top["returned"]


def test_existing_total_key_is_not_overwritten():
    out = json.loads(result_json({"total": 7, "rows": _rows(2000)}, {}, read_only=True))
    assert out["total"] == 7 and out["truncated"] is True
    assert out["truncation"]["total"] == 2000


def test_untrimmable_oversize_result_is_returned_whole():
    result = {"note": "x" * 50000}
    assert json.loads(result_json(result, {}, read_only=True)) == result


def test_errors_and_progress_are_never_trimmed():
    result = {"ok": False, "error": {"message": "x" * 50000}, "rows": _rows(2000)}
    assert result_json(result, {}, project=False, read_only=True) == json.dumps(result, indent=2)


def test_not_read_only_results_are_never_trimmed():
    result = {"elements": _rows(2000)}
    assert result_json(result, {}) == json.dumps(result, indent=2)
    assert result_json(result, {"compact": True}) == json.dumps(result, separators=(",", ":"))


@pytest.mark.parametrize("key", ["plan_hash", "plan_id"])
def test_results_carrying_plan_material_are_never_trimmed_or_compacted(key):
    result = {key: "abc", "actions": _rows(2000)}
    assert result_json(result, {}, read_only=True) == json.dumps(result, indent=2)


def test_max_chars_is_validated():
    for bad in (-1, True, "20", 1.5, None):
        with pytest.raises(ValueError):
            split_response_options("revit_list_elements", {"response_options": {"max_chars": bad}})
    _, options = split_response_options("revit_list_elements", {"response_options": {"max_chars": 0}})
    assert options == {"max_chars": 0}
    with pytest.raises(ValueError):
        split_response_options("plan_actions", {"response_options": {"max_chars": 100}})


def test_unadvertised_read_only_tools_accept_compact_and_max_chars_only():
    args, options = split_response_options(
        "revit_get_warnings", {"x": 1, "response_options": {"compact": False, "max_chars": 0}}, read_only=True)
    assert args == {"x": 1} and options == {"compact": False, "max_chars": 0}
    with pytest.raises(ValueError):
        split_response_options("revit_get_warnings", {"response_options": {"fields": ["a"]}}, read_only=True)
    untouched = {"response_options": {"anything": 1}}
    assert split_response_options("revit_create_wall", untouched, read_only=False)[0] is untouched


def test_schema_advertises_max_chars_for_readers_only_and_compact_default():
    def tool(name, mutating=False):
        return ProviderTool(name=name, description="A useful tool description.", inputSchema={}, is_mutating=mutating)
    read = enrich_tool("revit", tool("revit_list_elements")).inputSchema["properties"]["response_options"]
    assert set(read["properties"]) == {"compact", "fields", "max_chars"}
    assert "default true" in read["properties"]["compact"]["description"]
    plan = enrich_tool("approval", tool("plan_actions")).inputSchema["properties"]["response_options"]
    assert set(plan["properties"]) == {"compact", "omit_action_arguments"}
    assert "default false" in plan["properties"]["compact"]["description"]


# ---- call_tool path -------------------------------------------------------------------------------
@pytest.fixture
def execution(monkeypatch):
    state = SimpleNamespace(result={"elements": _rows(2000)}, mutating=False)

    class Provider:
        async def execute_tool(self, name, arguments):
            return state.result

    class Registry:
        def lookup_tool_provider(self, name):
            return Provider()

        def lookup_tool(self, name):
            return SimpleNamespace(name=name, is_mutating=state.mutating)

    monkeypatch.setattr(mcp_server, "registry", Registry())
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=None))
    return state


def _body(answer):
    return answer[0].text.split("Result:\n", 1)[1]


def test_call_tool_compacts_and_caps_read_only_results(execution):
    body = _body(asyncio.run(mcp_server.call_tool("revit_get_warnings", {})))
    assert len(body) <= DEFAULT_MAX_CHARS and "\n" not in body
    assert json.loads(body)["truncated"] is True


def test_call_tool_honours_opt_outs_on_unadvertised_read_tools(execution):
    body = _body(asyncio.run(mcp_server.call_tool(
        "revit_get_warnings", {"response_options": {"compact": False, "max_chars": 0}})))
    assert body == json.dumps(execution.result, indent=2)


def test_call_tool_leaves_write_tool_results_alone(execution):
    execution.mutating = True
    body = _body(asyncio.run(mcp_server.call_tool("revit_create_wall", {})))
    assert body == json.dumps(execution.result, indent=2)


@pytest.mark.parametrize("name", ["execute_plan", "list_pending_plans", "get_proof_bundle", "revit_get_result"])
def test_call_tool_leaves_approval_and_proof_tools_alone_even_if_flagged_read_only(execution, name):
    body = _body(asyncio.run(mcp_server.call_tool(name, {})))
    assert body == json.dumps(execution.result, indent=2)


def test_call_tool_never_trims_a_failure(execution):
    execution.result = {"ok": False, "error": {"message": "x" * 50000}, "rows": _rows(2000)}
    answer = asyncio.run(mcp_server.call_tool("revit_get_warnings", {}))
    assert answer.isError
    assert answer.content[0].text.split("Result:\n", 1)[1] == json.dumps(execution.result, indent=2)


# ---- plan / proof / approval payloads are byte-identical with the cap active ----------------------
def _approval_env(tmp_path, monkeypatch):
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    registry, approval, jobs, _, _ = build_registry(WorkspaceMonitor([tmp_path]))
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    return registry, approval, jobs


def test_huge_plan_and_pending_list_pass_through_byte_identical(tmp_path, monkeypatch):
    registry, approval, jobs = _approval_env(tmp_path, monkeypatch)
    try:
        actions = [{"tool": "revit_set_parameter_value",
                    "arguments": {"element_id": i, "parameter_name": "Comments", "value": "v" * 60}}
                   for i in range(400)]
        answer = asyncio.run(mcp_server.call_tool("plan_actions", {"actions": actions}))
        body = _body(answer)
        assert len(body) > DEFAULT_MAX_CHARS * 5
        plan = json.loads(body)
        stored = approval.gate.load_plan(plan["plan_id"])
        assert "truncated" not in plan and len(plan["actions"]) == 400
        assert body == json.dumps(stored, indent=2)
        assert plan == stored

        listing = _body(asyncio.run(mcp_server.call_tool("list_pending_plans", {})))
        expected = asyncio.run(approval_provider_result(approval, "list_pending_plans"))
        assert listing == json.dumps(expected, indent=2)
        assert "truncated" not in listing and plan["plan_id"] in listing
    finally:
        asyncio.run(jobs.shutdown(cancel_running=True))


async def approval_provider_result(approval, name):
    return await approval.execute_tool(name, {})


def test_proof_bundle_and_review_material_are_never_reshaped(tmp_path, monkeypatch):
    registry, approval, jobs = _approval_env(tmp_path, monkeypatch)
    try:
        calls = []
        real = approval.execute_tool

        async def fake(name, arguments):
            if name == "get_proof_bundle":
                calls.append(name)
                return {"plan_hash": "h", "proof": {"entries": _rows(3000)}, "review": {"summary": "s" * 30000}}
            return await real(name, arguments)

        monkeypatch.setattr(approval, "execute_tool", fake)
        from revit_mcp_server.security.audit import redact_data

        body = _body(asyncio.run(mcp_server.call_tool("get_proof_bundle", {"plan_id": "plan_x"})))
        payload = {"plan_hash": "h", "proof": {"entries": _rows(3000)}, "review": {"summary": "s" * 30000}}
        assert calls and body == json.dumps(redact_data(payload), indent=2)  # redaction is the only change
        assert len(json.loads(body)["proof"]["entries"]) == 3000
    finally:
        asyncio.run(jobs.shutdown(cancel_running=True))


# ---- C: limit / offset / count_only on the six unpaginated list tools -----------------------------
PAGED = {
    "revit_list_elements": ("elements", {"category": "Walls"}),
    "revit_list_views": ("views", {}),
    "revit_list_families": ("families", {}),
    "revit_get_categories": ("categories", {}),
    "revit_get_warnings": ("warnings", {}),
    "revit_get_schedule_data": ("fields", {"schedule_id": 1}),
}


@pytest.fixture
def revit_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_MODE", "mock")
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    registry, _approval, jobs, _, _ = build_registry(WorkspaceMonitor([tmp_path]))
    yield registry
    asyncio.run(jobs.shutdown(cancel_running=True))


def _serve(registry, monkeypatch, name, key, sent):
    provider = registry.lookup_tool_provider(name)
    rows = [{"n": i} for i in range(120)]

    def send_tool(bridge_tool, payload):
        sent.append(payload)
        return {key: list(rows), "count": len(rows), "keep": "me"}

    class Bridge:
        pass

    Bridge.send_tool = staticmethod(send_tool)
    monkeypatch.setattr(provider, "mode", __import__("revit_mcp_server.providers.revit", fromlist=["x"]).BridgeMode.bridge)
    monkeypatch.setattr(provider, "_active_bridge", lambda: Bridge())
    monkeypatch.setattr("revit_mcp_server.providers.revit.TOOL_HANDLERS", {})
    return provider, rows


@pytest.mark.parametrize("name", sorted(PAGED))
def test_list_tools_page_in_the_provider(revit_provider, monkeypatch, name):
    key, base = PAGED[name]
    sent = []
    provider, rows = _serve(revit_provider, monkeypatch, name, key, sent)

    whole = asyncio.run(provider.execute_tool(name, dict(base)))
    assert whole[key] == rows and "total" not in whole  # no paging arguments: unchanged

    page = asyncio.run(provider.execute_tool(name, {**base, "limit": 10, "offset": 5}))
    assert page[key] == rows[5:15]
    assert (page["total"], page["returned"], page["offset"], page["has_more"]) == (120, 10, 5, True)
    assert page["count"] == 120 and page["keep"] == "me"

    last = asyncio.run(provider.execute_tool(name, {**base, "limit": 50, "offset": 100}))
    assert last[key] == rows[100:] and last["has_more"] is False

    counted = asyncio.run(provider.execute_tool(name, {**base, "count_only": True}))
    assert key not in counted and counted["total"] == 120 and counted["count_only"] is True
    assert counted["returned"] == 0

    assert all(not ({"limit", "offset", "count_only"} & p.keys()) for p in sent)


def test_paging_leaves_errors_and_unexpected_shapes_alone(revit_provider, monkeypatch):
    provider, _ = _serve(revit_provider, monkeypatch, "revit_list_views", "views", [])
    monkeypatch.setattr(provider, "_active_bridge", lambda: SimpleNamespace(
        send_tool=lambda tool, payload: {"ok": False, "error": {"message": "no document"}}))
    out = asyncio.run(provider.execute_tool("revit_list_views", {"limit": 5}))
    assert out == {"ok": False, "error": {"message": "no document"}}
    monkeypatch.setattr(provider, "_active_bridge", lambda: SimpleNamespace(
        send_tool=lambda tool, payload: {"views": "not a list"}))
    assert asyncio.run(provider.execute_tool("revit_list_views", {"limit": 5})) == {"views": "not a list"}


def test_paged_tools_advertise_short_limit_offset_count_only(revit_provider):
    provider = revit_provider.lookup_tool_provider("revit_list_views")
    tools = {t.name: t for t in provider.get_capabilities()}
    for name in PAGED:
        enriched = enrich_tool("revit", tools[name])
        props = enriched.inputSchema["properties"]
        assert {"limit", "offset", "count_only"} <= set(props), name
        assert props["limit"]["type"] == "integer" and props["count_only"]["type"] == "boolean"
        assert not {"limit", "offset", "count_only"} & set(enriched.inputSchema.get("required", [])), name
