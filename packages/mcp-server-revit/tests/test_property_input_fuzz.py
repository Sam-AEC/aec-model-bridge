"""Fuzz of the gate's input validation (issue #296).

Random JSON for plan_actions, execute_plan and direct mutating calls must be refused with the
documented error types only: BridgeError (PolicyError is a subclass) or ValueError, which the MCP
layer turns into approval_blocked, bridge_error or execution_error. A TypeError, KeyError or
AttributeError here would mean a validator assumed a shape it never checked.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from hypothesis import event, given, settings
from hypothesis import strategies as st

from revit_mcp_server.config import APPROVAL_MODES, normalize_approval_mode
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.result_presentation import split_response_options
from revit_mcp_server.security import binding as binding_mod
from revit_mcp_server.security import proof as proof_mod
from revit_mcp_server.security.approval import ApprovalGate, canonical_arguments
from revit_mcp_server.security.read_mode import is_read_mode_call
from revit_mcp_server.security.recipe_store import RECIPE_RUN_TOOL, standing_authorizes
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_property_gate import SET, FakeStore

DOCUMENTED = (BridgeError, ValueError)

json_scalars = st.one_of(
    st.none(), st.booleans(), st.integers(), st.floats(), st.text(max_size=20),
)
json_values = st.recursive(
    json_scalars,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)
# Mostly well-shaped actions with hostile parts, so validation gets past the first check.
actions = st.one_of(
    json_values,
    st.lists(st.one_of(
        json_values,
        st.fixed_dictionaries(
            {"tool": st.one_of(st.just(SET), st.sampled_from(["approve_plan", "rollback_plan", "", "nope"]), json_values)},
            optional={"arguments": json_values},
        ),
    ), max_size=4),
)
plan_actions_args = st.fixed_dictionaries(
    {},
    optional={"actions": actions, "snapshot_id": json_values, "skipped": json_values, "review": json_values,
              "plan_id": json_values, "response_options": json_values},
)


def _provider(tmp: Path, mode: str = "ask_first") -> ApprovalProvider:
    registry = ProviderRegistry()
    provider = ApprovalProvider(WorkspaceMonitor([tmp]), registry, approval_mode=mode)
    registry.register(provider)
    registry.register(FakeStore())
    return provider


def _refused_or_ok(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except DOCUMENTED as e:
        return e


@settings(deadline=None)
@given(args=plan_actions_args)
def test_plan_actions_raises_only_documented_errors(args: Dict[str, Any]) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="fuzz-plan-"))
    try:
        result = _refused_or_ok(_provider(tmp).execute_tool("plan_actions", args))
        event("drafted" if isinstance(result, dict) else f"refused: {type(result).__name__}")
        if isinstance(result, dict):
            # Anything that drafted is a valid, hashable plan that only names registered tools.
            assert result["state"] == "pending" and result["plan_hash"].startswith("sha256:")
            assert all(a["tool"] == SET for a in result["actions"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@settings(deadline=None)
@given(plan_id=json_values, mode=st.sampled_from(["ask_first", "look_only", "auto"]))
def test_execute_plan_raises_only_documented_errors(plan_id: Any, mode: str) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="fuzz-exec-"))
    try:
        result = _refused_or_ok(_provider(tmp, mode).execute_tool("execute_plan", {"plan_id": plan_id}))
        assert isinstance(result, Exception), "execute_plan ran a plan that does not exist"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@settings(deadline=None)
@given(arguments=json_values, tool=st.sampled_from([SET, RECIPE_RUN_TOOL, "approve_plan", "x"]))
def test_claim_action_refuses_random_calls_in_ask_first(arguments: Any, tool: str) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="fuzz-claim-"))
    try:
        gate = ApprovalGate(tmp, "ask_first")
        try:
            gate.claim_action(tool, arguments)
        except BridgeError:
            return
        raise AssertionError("ask_first allowed a write with no approved plan")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@given(arguments=json_values)
def test_standing_approval_never_matches_random_arguments(arguments: Any) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        assert standing_authorizes(Path(tmp), RECIPE_RUN_TOOL, arguments) is None


@given(value=json_values)
def test_validate_actions_raises_only_bridge_error(value: Any) -> None:
    try:
        ApprovalGate.validate_actions(value)
    except BridgeError:
        return
    assert isinstance(value, list)


@given(review=json_values)
def test_normalize_review_raises_only_value_error(review: Any) -> None:
    try:
        out = proof_mod.normalize_review(review)
    except ValueError:
        return
    assert proof_mod.normalize_review(out) == out  # canonical form is a fixed point


@given(value=json_values)
def test_binding_validators_never_raise_unexpected(value: Any) -> None:
    try:
        binding_mod.validate_binding(value)
    except ValueError:
        pass
    live = binding_mod.live_binding(value)
    assert live is None or set(live) <= set(binding_mod.BINDING_KEYS)


@given(arguments=json_values)
def test_read_mode_check_fails_closed(arguments: Any) -> None:
    try:
        is_read = is_read_mode_call(arguments)
    except ValueError:  # ReadModeViolation
        return
    if is_read:
        assert arguments.get("mode", "").strip().lower() == "read"


@given(value=json_values)
def test_approval_mode_normalises_to_a_known_mode(value: Any) -> None:
    mode = normalize_approval_mode(value)
    assert mode in APPROVAL_MODES
    if mode == "auto":
        assert isinstance(value, str) and value.strip().lower() == "auto"


@given(name=st.sampled_from(["plan_actions", "execute_plan", "revit_list_views", SET]), arguments=json_values,
       read_only=st.booleans())
def test_response_options_split_raises_only_value_error(name: str, arguments: Any, read_only: bool) -> None:
    try:
        split_response_options(name, arguments, read_only)
    except ValueError:
        pass


@given(value=json_values)
def test_canonical_arguments_is_total(value: Any) -> None:
    text = canonical_arguments(value)
    assert isinstance(text, str)
    if not isinstance(value, dict):
        assert text != canonical_arguments({})
