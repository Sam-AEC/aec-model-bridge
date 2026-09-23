"""Tests for agent_native.py's Anthropic tool-calling chat loop.

None of these call the real Anthropic API: `anthropic.Anthropic` is
monkeypatched to a fake client whose `.messages.create` is a Mock, following
the same monkeypatch convention as test_agent_bridge.py (which mocks
subprocess.run/shutil.which instead, since it shells out to a CLI). A small
in-file fake provider (mirroring test_approval_provider.py's FakeParamStore
pattern) stands in for a real Revit provider, with one mutating and one
non-mutating tool so the approval-gate behavior can be exercised precisely.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import Mock

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from revit_mcp_server import agent_native
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.base import AECProvider, ProviderTool
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security.workspace import WorkspaceMonitor


class _FakeToolProvider(AECProvider):
    """One mutating tool, one non-mutating tool, recording every execute_tool
    call so tests can assert on exactly what ran (and with what arguments)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Dict[str, Any]]] = []

    def get_identity(self) -> str:
        return "fake_native"

    def get_capabilities(self):
        return [
            ProviderTool(
                name="revit_set_parameter_value",
                description="Set a parameter value (mutating).",
                inputSchema={"type": "object", "properties": {}},
                is_mutating=True,
            ),
            ProviderTool(
                name="revit_get_parameter_value",
                description="Read a parameter value (non-mutating).",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy"}

    async def shutdown(self) -> None:
        pass

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "revit_set_parameter_value":
            return {"status": "success"}
        if name == "revit_get_parameter_value":
            return {"value": "60"}
        raise ValueError(f"unknown tool {name}")


@pytest.fixture(autouse=True)
def _clean_sessions():
    agent_native._sessions.clear()
    yield
    agent_native._sessions.clear()


@pytest.fixture
def registry():
    reg = ProviderRegistry()
    reg.register(_FakeToolProvider())
    return reg


@pytest.fixture
def approval_provider():
    return SimpleNamespace(gate=Mock())


def _text_response(text: str):
    return SimpleNamespace(content=[TextBlock(type="text", text=text)])


def _tool_use_response(tool_name: str, tool_input: Dict[str, Any], tool_use_id: str = "tu_1"):
    return SimpleNamespace(content=[ToolUseBlock(type="tool_use", id=tool_use_id, name=tool_name, input=tool_input)])


def _install_fake_client(monkeypatch, create_fn):
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=create_fn))
    monkeypatch.setattr(agent_native.anthropic, "Anthropic", lambda **kwargs: fake_client)
    return fake_client


def test_missing_api_key_returns_error_without_calling_api(monkeypatch, registry, approval_provider):
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", None)
    client_ctor = Mock()
    monkeypatch.setattr(agent_native.anthropic, "Anthropic", client_ctor)

    result = agent_native.run_native_turn("hello", None, registry, approval_provider)

    assert result == {
        "ok": False,
        "error": "No Anthropic API key configured. Set the MCP_REVIT_ANTHROPIC_API_KEY "
                 "environment variable and restart Revit.",
    }
    client_ctor.assert_not_called()


def test_build_tools_never_offers_plan_approval_tools_to_the_model(tmp_path):
    """Load-bearing regression test for the self-approval bypass: with a real
    ApprovalProvider registered, the model must never be handed approve_plan,
    reject_plan or rollback_plan (otherwise it could plan_actions ->
    approve_plan -> execute_plan with no human involved), while the tools it
    legitimately needs to propose and run approved plans stay available."""
    reg = ProviderRegistry()
    reg.register(ApprovalProvider(workspace=WorkspaceMonitor([tmp_path]), registry=reg, approval_mode="required"))
    reg.register(_FakeToolProvider())

    registered = {t.name for t in reg.get_all_tools()}
    # Guard against a vacuous pass: the excluded tools really are in the registry.
    assert {"approve_plan", "reject_plan", "rollback_plan"} <= registered

    offered = {t["name"] for t in agent_native._build_tools(reg)}

    assert "approve_plan" not in offered
    assert "reject_plan" not in offered
    assert "rollback_plan" not in offered
    assert {"plan_actions", "list_pending_plans", "execute_plan"} <= offered
    assert {"revit_set_parameter_value", "revit_get_parameter_value"} <= offered


def test_model_emitted_approve_plan_is_refused_and_never_executes(monkeypatch, tmp_path):
    """Defense in depth: even if the model emits a tool_use for approve_plan
    (a name it was never offered), the loop refuses it and the plan's state
    is untouched."""
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")
    reg = ProviderRegistry()
    approval = ApprovalProvider(workspace=WorkspaceMonitor([tmp_path]), registry=reg, approval_mode="required")
    reg.register(approval)
    reg.register(_FakeToolProvider())
    plan = approval.gate.create_plan(
        [{"tool": "revit_set_parameter_value", "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "X"}}],
        [{}],
    )

    create = Mock(side_effect=[
        _tool_use_response("approve_plan", {"plan_id": plan["plan_id"]}),
        _text_response("I can't approve plans myself."),
    ])
    _install_fake_client(monkeypatch, create)

    result = agent_native.run_native_turn("approve it", None, reg, approval)

    assert result["ok"] is True
    assert approval.gate.load_plan(plan["plan_id"])["state"] != "approved"
    tool_result = agent_native._sessions[result["session_id"]][2]["content"][0]
    assert tool_result["is_error"] is True
    assert "not available to the chat assistant" in tool_result["content"]


def test_tools_carry_a_single_cache_breakpoint_on_the_last_tool(registry):
    tools = agent_native._build_tools(registry)
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in t for t in tools[:-1])


def test_successful_single_turn_returns_text_and_session_id(monkeypatch, registry, approval_provider):
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")
    create = Mock(return_value=_text_response("3 doors on Level 1"))
    _install_fake_client(monkeypatch, create)

    result = agent_native.run_native_turn("how many doors on level 1?", None, registry, approval_provider)

    assert result["ok"] is True
    assert result["response"] == "3 doors on Level 1"
    assert isinstance(result["session_id"], str) and result["session_id"]
    create.assert_called_once()


def test_mutating_tool_call_goes_through_approval_gate_before_executing(monkeypatch, registry, approval_provider):
    """The load-bearing test: a mutating tool call must be checked against
    ApprovalGate.check_tool_execution BEFORE provider.execute_tool runs -
    not just that the tool eventually executed."""
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")

    call_order: list[tuple[str, str]] = []
    approval_provider.gate.check_tool_execution.side_effect = lambda name, args: call_order.append(("gate", name))

    fake_provider = registry.lookup_tool_provider("revit_set_parameter_value")
    original_execute = fake_provider.execute_tool

    async def spying_execute(name, arguments):
        call_order.append(("execute", name))
        return await original_execute(name, arguments)

    monkeypatch.setattr(fake_provider, "execute_tool", spying_execute)

    tool_args = {"element_id": 1, "parameter_name": "Mark", "value": "D-1", "plan_id": "plan_x"}
    create = Mock(side_effect=[
        _tool_use_response("revit_set_parameter_value", tool_args),
        _text_response("Updated Mark to D-1"),
    ])
    _install_fake_client(monkeypatch, create)

    result = agent_native.run_native_turn("set the mark to D-1", None, registry, approval_provider)

    assert result["ok"] is True
    assert result["response"] == "Updated Mark to D-1"
    approval_provider.gate.check_tool_execution.assert_called_once_with("revit_set_parameter_value", tool_args)
    assert call_order == [("gate", "revit_set_parameter_value"), ("execute", "revit_set_parameter_value")]


def test_gate_rejected_tool_call_surfaces_to_model_as_error_result_without_rollback(
    monkeypatch, registry, approval_provider
):
    """A per-tool-call failure (here: the approval gate rejecting a mutating
    call) must NOT abort the turn. It comes back to the model as a
    tool_result with is_error=True, the model gets to explain it, and the
    session history keeps the whole exchange - including a sibling call in
    the same turn that already succeeded."""
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")
    approval_provider.gate.check_tool_execution.side_effect = RuntimeError(
        "Mutating tool 'revit_set_parameter_value' requires a valid 'plan_id' parameter."
    )

    read_args = {"element_id": 1, "parameter_name": "FireRating"}
    write_args = {"element_id": 1, "parameter_name": "FireRating", "value": "90"}
    two_calls = SimpleNamespace(content=[
        ToolUseBlock(type="tool_use", id="tu_read", name="revit_get_parameter_value", input=read_args),
        ToolUseBlock(type="tool_use", id="tu_write", name="revit_set_parameter_value", input=write_args),
    ])
    create = Mock(side_effect=[two_calls, _text_response("That change needs an approved plan - review it in the panel.")])
    _install_fake_client(monkeypatch, create)

    result = agent_native.run_native_turn("set fire rating to 90", None, registry, approval_provider)

    assert result["ok"] is True
    assert result["response"] == "That change needs an approved plan - review it in the panel."
    assert create.call_count == 2

    history = agent_native._sessions[result["session_id"]]
    # user, assistant(tool_use x2), user(tool_results), assistant(text) - nothing rolled back.
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    read_result, write_result = history[2]["content"]
    assert read_result["tool_use_id"] == "tu_read"
    assert "is_error" not in read_result
    assert write_result["tool_use_id"] == "tu_write"
    assert write_result["is_error"] is True
    assert "requires a valid 'plan_id'" in write_result["content"]

    # The rejected mutation never ran; the sibling read did.
    fake_provider = registry.lookup_tool_provider("revit_set_parameter_value")
    assert fake_provider.calls == [("revit_get_parameter_value", read_args)]


def test_api_failure_after_tool_calls_still_rolls_back_whole_turn(monkeypatch, registry, approval_provider):
    """The outer rollback is now reserved for transport/API-level failures:
    if messages.create itself fails mid-turn, the session is restored to its
    pre-turn state so no dangling tool_use/tool_result pair is left behind."""
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")
    create = Mock(side_effect=[
        _tool_use_response("revit_get_parameter_value", {"element_id": 1, "parameter_name": "FireRating"}),
        ConnectionError("network down"),
    ])
    _install_fake_client(monkeypatch, create)

    result = agent_native.run_native_turn("what's the fire rating?", None, registry, approval_provider)

    assert result == {"ok": False, "error": "network down"}
    assert all(len(h) == 0 for h in agent_native._sessions.values())


def test_non_mutating_tool_call_does_not_require_gate_check(monkeypatch, registry, approval_provider):
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")

    tool_args = {"element_id": 1, "parameter_name": "FireRating"}
    create = Mock(side_effect=[
        _tool_use_response("revit_get_parameter_value", tool_args),
        _text_response("FireRating is 60"),
    ])
    _install_fake_client(monkeypatch, create)

    result = agent_native.run_native_turn("what's the fire rating?", None, registry, approval_provider)

    assert result["ok"] is True
    assert result["response"] == "FireRating is 60"
    approval_provider.gate.check_tool_execution.assert_not_called()

    fake_provider = registry.lookup_tool_provider("revit_get_parameter_value")
    assert fake_provider.calls == [("revit_get_parameter_value", tool_args)]


def test_turn_cap_returns_error_after_ten_turns(monkeypatch, registry, approval_provider):
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")

    counter = {"n": 0}

    def always_tool_use(**kwargs):
        counter["n"] += 1
        return _tool_use_response(
            "revit_get_parameter_value",
            {"element_id": 1, "parameter_name": "FireRating"},
            tool_use_id=f"tu_{counter['n']}",
        )

    create = Mock(side_effect=always_tool_use)
    _install_fake_client(monkeypatch, create)

    result = agent_native.run_native_turn("loop forever", None, registry, approval_provider)

    assert result == {
        "ok": False,
        "error": "Conversation exceeded the maximum number of tool-calling turns (10) without a final response.",
    }
    assert create.call_count == 10


def test_session_id_continues_conversation_history(monkeypatch, registry, approval_provider):
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")
    create = Mock(side_effect=[_text_response("Hi there"), _text_response("Still Alice")])
    _install_fake_client(monkeypatch, create)

    first = agent_native.run_native_turn("My name is Alice", None, registry, approval_provider)
    session_id = first["session_id"]

    second = agent_native.run_native_turn("What's my name?", session_id, registry, approval_provider)

    assert second["ok"] is True
    assert second["session_id"] == session_id

    second_call_messages = create.call_args_list[1].kwargs["messages"]
    user_texts = [m["content"] for m in second_call_messages if m["role"] == "user"]
    assert "My name is Alice" in user_texts
    assert "What's my name?" in user_texts


def test_failed_turn_rolls_back_session_history(monkeypatch, registry, approval_provider):
    """Regression test for the rollback-on-exception path: a failure that
    happens AFTER the user message has already been appended to session
    history (e.g. building the tools list blows up) must not leave a
    dangling/unbalanced turn behind - the session must look exactly as it
    did before the failed call, and must still work normally afterward."""
    monkeypatch.setattr(agent_native.config, "anthropic_api_key", "test-key")

    create = Mock(return_value=_text_response("Hello!"))
    _install_fake_client(monkeypatch, create)
    first = agent_native.run_native_turn("hi", None, registry, approval_provider)
    session_id = first["session_id"]
    history_len_before_failure = len(agent_native._sessions[session_id])

    original_build_tools = agent_native._build_tools

    def boom(_registry):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(agent_native, "_build_tools", boom)

    result = agent_native.run_native_turn("this call will fail", session_id, registry, approval_provider)

    assert result == {"ok": False, "error": "registry exploded"}
    assert len(agent_native._sessions[session_id]) == history_len_before_failure

    monkeypatch.setattr(agent_native, "_build_tools", original_build_tools)
    create.return_value = _text_response("Still working")
    followup = agent_native.run_native_turn("does this still work?", session_id, registry, approval_provider)
    assert followup == {"ok": True, "response": "Still working", "session_id": session_id}
