"""Opt-in presentation must leave execution, redaction and approval data intact."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.providers.base import ProviderTool
from revit_mcp_server.result_presentation import result_json, split_response_options
from revit_mcp_server.tool_metadata import enrich_tool


def test_default_json_is_identical_and_compact_preserves_all_data():
    result = {"modules": [{"id": "revit", "commands": [{"id": "x", "schema": {"x": 1}}]}]}
    assert result_json(result, {}) == json.dumps(result, indent=2)
    compact = result_json(result, {"compact": True})
    assert len(compact) < len(result_json(result, {}))
    assert json.loads(compact) == result


def test_dotted_projection_traverses_arrays_and_never_mutates_source():
    result = {"modules": [{"id": "revit", "title": "Revit", "commands": [{"id": "x", "schema": {"x": 1}}]}]}
    before = copy.deepcopy(result)
    projected = json.loads(result_json(result, {"fields": ["modules.id", "modules.commands.id"]}))
    assert projected == {"modules": [{"id": "revit", "commands": [{"id": "x"}]}]}
    assert result == before
    assert json.loads(result_json(result, {"fields": ["modules", "modules.id"]})) == result


@pytest.mark.parametrize("options", [None, [], {"compact": "true"}, {"fields": []},
                                   {"fields": "id"}, {"fields": ["a..b"]}, {"fields": [42]}, {"unknown": 1}])
def test_invalid_options_are_rejected(options):
    with pytest.raises(ValueError):
        split_response_options("module_list_commands", {"response_options": options})


def test_plan_projection_and_async_options_are_rejected():
    with pytest.raises(ValueError):
        split_response_options("plan_actions", {"response_options": {"fields": ["id"]}})
    with pytest.raises(ValueError):
        split_response_options("module_list_commands", {"run_async": True, "response_options": {}})
    _, options = split_response_options("module_list_commands", {"run_async": "false", "response_options": {}})
    assert options == {}


def test_only_measured_tools_advertise_options_and_writes_retain_plan_schema():
    def tool(name, mutating=False):
        return ProviderTool(name=name, description="A useful tool description.", inputSchema={}, is_mutating=mutating)
    read = enrich_tool("revit", tool("revit_list_elements"))
    assert "response_options" in read.inputSchema["properties"]
    plan = enrich_tool("approval", tool("plan_actions"))
    assert set(plan.inputSchema["properties"]["response_options"]["properties"]) == {"compact", "omit_action_arguments"}
    write = enrich_tool("revit", tool("revit_create_wall", True))
    assert "response_options" not in write.inputSchema["properties"]
    assert "plan_id" in write.inputSchema["properties"]
    assert "Write operation:" not in write.description
    assert "person" in mcp_server.SERVER_INSTRUCTIONS


@pytest.fixture
def execution(monkeypatch):
    state = SimpleNamespace(calls=[], result={"elements": [{"id": 1, "name": "Wall", "extra": "detail"}]})

    class Provider:
        async def execute_tool(self, name, arguments):
            state.calls.append((name, copy.deepcopy(arguments)))
            return state.result

    class Registry:
        def lookup_tool_provider(self, name):
            return Provider()

        def lookup_tool(self, name):
            return SimpleNamespace(is_mutating=False)

    monkeypatch.setattr(mcp_server, "registry", Registry())
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=None))
    return state


def test_call_strips_options_before_provider_and_projects_only_response(execution):
    args = {"category": "Walls", "response_options": {"compact": True, "fields": ["elements.id"]}}
    answer = asyncio.run(mcp_server.call_tool("revit_list_elements", args))
    assert json.loads(answer[0].text.split("Result:\n")[1]) == {"elements": [{"id": 1}]}
    assert execution.calls == [("revit_list_elements", {"category": "Walls"})]
    assert execution.result["elements"][0]["extra"] == "detail"
    assert "response_options" in args


def test_invalid_plan_formatting_cannot_create_a_plan(execution):
    answer = asyncio.run(mcp_server.call_tool("plan_actions", {"actions": [], "response_options": {"fields": ["id"]}}))
    assert answer.isError
    assert answer.structuredContent["error"]["kind"] == "invalid_response_options"
    assert execution.calls == []


def test_projection_still_redacts_secrets(execution):
    execution.result = {"elements": [{"id": 1, "password": "private-value"}]}
    answer = asyncio.run(mcp_server.call_tool("revit_list_elements", {
        "response_options": {"compact": True, "fields": ["elements.id", "elements.password"]},
    }))
    assert "private-value" not in answer[0].text
    assert json.loads(answer[0].text.split("Result:\n")[1])["elements"][0]["id"] == 1


def test_compact_plan_keeps_stored_review_and_action_arguments(tmp_path, monkeypatch):
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    registry, approval, jobs, _, _ = build_registry(WorkspaceMonitor([tmp_path]))
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    action = {"tool": "revit_create_level", "arguments": {"name": "Test", "elevation": 10}}
    answer = asyncio.run(mcp_server.call_tool("plan_actions", {
        "actions": [action], "response_options": {"compact": True},
    }))
    plan = json.loads(answer[0].text.split("Result:\n")[1])
    stored = approval.gate.load_plan(plan["plan_id"])
    assert plan == stored
    assert stored["actions"][0]["arguments"] == action["arguments"]
    assert stored["state"] == "pending"
    asyncio.run(jobs.shutdown(cancel_running=True))


@pytest.mark.parametrize("invalid", [None, 0, "true", [], {}])
def test_plan_argument_omission_requires_a_boolean(invalid):
    with pytest.raises(ValueError, match="must be a boolean"):
        split_response_options("plan_actions", {"response_options": {"omit_action_arguments": invalid}})


def test_argument_omission_is_not_available_for_readers():
    with pytest.raises(ValueError, match="supports only"):
        split_response_options("module_list_commands", {"response_options": {"omit_action_arguments": True}})


def test_summary_preserves_review_evidence_and_distinct_after_state():
    plan = {"plan_id": "plan_test", "plan_hash": "full-plan-hash", "review": {"summary": "Review me"},
            "actions": [{"tool": "set", "arguments": {"value": 1},
                         "diff": {"before": {"value": 0}, "after": {"value": 2}}}]}
    original = copy.deepcopy(plan)
    summary = json.loads(result_json(plan, {"omit_action_arguments": True}))
    assert plan == original
    assert summary["plan_hash"] == plan["plan_hash"]
    assert summary["review"] == plan["review"]
    assert summary["actions"][0]["diff"] == plan["actions"][0]["diff"]
    assert summary["actions"][0]["arguments_omitted"] is True
    assert "arguments" not in summary["actions"][0]
    assert "full stored plan" in summary["response_note"]
    assert json.loads(result_json(plan, {"omit_action_arguments": False})) == plan
    assert json.loads(result_json(plan, {"omit_action_arguments": True}, project=False)) == plan


@pytest.mark.parametrize("compact", [False, True])
def test_plan_summary_leaves_full_arguments_hash_review_and_gate_intact(tmp_path, monkeypatch, compact):
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.approval import plan_hash
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    registry, approval, jobs, _, _ = build_registry(WorkspaceMonitor([tmp_path]))
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    arguments = {"script": "#" + "x" * 16383, "mode": "write"}
    review = {"summary": "Test script plan", "warnings": ["A person must review the complete script"]}
    answer = asyncio.run(mcp_server.call_tool("plan_actions", {
        "actions": [{"tool": "revit_execute_python", "arguments": arguments}], "review": review,
        "response_options": {"compact": compact, "omit_action_arguments": True},
    }))
    summary = json.loads(answer[0].text.split("Result:\n")[1])
    stored = approval.gate.load_plan(summary["plan_id"])
    assert stored["plan_hash"] == summary["plan_hash"] == plan_hash(stored)
    assert summary["review"] == stored["review"]
    assert all(summary["review"][key] == value for key, value in review.items())
    assert summary["hash_version"] == stored["hash_version"]
    assert stored["actions"][0]["arguments"] == arguments
    assert stored["actions"][0]["diff"]["after"] == arguments
    assert "response_note" not in stored
    assert summary["actions"][0]["action_id"] == stored["actions"][0]["action_id"]
    assert summary["actions"][0]["arguments_omitted"] is True
    assert summary["actions"][0]["diff"]["after_omitted"] is True
    assert "arguments" not in summary["actions"][0]
    assert "after" not in summary["actions"][0]["diff"]
    assert arguments["script"] not in answer[0].text
    blocked = asyncio.run(mcp_server.call_tool("revit_execute_python", {**arguments, "plan_id": stored["plan_id"]}))
    assert blocked.isError and blocked.structuredContent["error"]["kind"] == "approval_blocked"
    assert approval.gate.load_plan(stored["plan_id"]) == stored
    assert stored["state"] == "pending"
    asyncio.run(jobs.shutdown(cancel_running=True))


@pytest.mark.parametrize("outcome", [
    {"ok": False, "error": {"message": "Review unavailable"}},
    {"status": "running", "request_id": "req-plan"},
])
def test_plan_argument_omission_cannot_hide_errors_or_progress(execution, outcome):
    payload = {**outcome, "actions": [{"arguments": {"script": "full diagnostic evidence"}}]}
    execution.result = payload
    answer = asyncio.run(mcp_server.call_tool("plan_actions", {
        "response_options": {"compact": True, "omit_action_arguments": True},
    }))
    content = answer.content if hasattr(answer, "content") else answer
    assert json.loads(content[0].text.split("Result:\n")[1]) == payload


@pytest.mark.parametrize("payload", [
    {"ok": False, "error": {"message": "Failure details"}},
    {"status": "running", "request_id": "req-1", "detail": "Still working"},
])
def test_errors_and_progress_are_never_projected(execution, payload):
    execution.result = payload
    answer = asyncio.run(mcp_server.call_tool("revit_list_elements", {"response_options": {"fields": ["absent"]}}))
    content = answer.content if hasattr(answer, "content") else answer
    assert json.loads(content[0].text.split("Result:\n")[1]) == payload
    if payload.get("ok") is False:
        assert answer.isError and answer.structuredContent == payload
