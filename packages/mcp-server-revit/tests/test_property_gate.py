"""Property tests of the approval gate (issue #296).

A Hypothesis state machine drives a real ApprovalProvider and ApprovalGate through random
sequences of drafting, approving (right and wrong hash, right and wrong channel), rejecting,
executing, direct tool calls, mode switches (configured mode, signed Dev mode, timed Auto),
clock movement (plan and approval expiry), live-document changes and on-disk edits of plan
content. A small model predicts, for every step, whether an approval is accepted and exactly
which writes reach the fake Revit store. The test fails on any difference.

Plan state fields are not forged here: plan files sit in a folder the model's file tools may not
write (security/workspace.py RESERVED_DIRS), and the hash only detects edits of reviewed content.
Replay through edited action states is covered by test_reopened_actions_never_run_twice.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from hypothesis import event, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    invariant,
    multiple,
    rule,
    run_state_machine_as_test,
)

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.base import AECProvider, ProviderTool
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security import approval as approval_module
from revit_mcp_server.security import approval_override as auto
from revit_mcp_server.security import dev_mode as dev
from revit_mcp_server.security.approval import canonical_arguments, plan_hash, write_rule
from revit_mcp_server.security.dispatch import run_gated_tool
from revit_mcp_server.security.workspace import WorkspaceMonitor

TOKEN = "A" * 43
SET = "revit_set_parameter_value"
TTL = 1100  # approval_ttl and pending_ttl, seconds; clock steps of 250 s never land on it
DOCS = {"A": "guid-a", "B": "guid-b"}

json_scalars = st.one_of(
    st.none(), st.booleans(), st.integers(-10**6, 10**6),
    st.floats(allow_nan=False, allow_infinity=False, width=32), st.text(max_size=8),
)
action_args = st.fixed_dictionaries({
    "element_id": st.integers(1, 3),
    "parameter_name": st.sampled_from(["Mark", "Comments"]),
    "value": json_scalars,
})


class FakeStore(AECProvider):
    """Stand-in for the Revit parameter tools; records every write it receives."""

    def __init__(self) -> None:
        self.writes: List[Dict[str, Any]] = []

    def get_identity(self) -> str:
        return "fake_revit"

    def get_capabilities(self) -> List[ProviderTool]:
        return [
            ProviderTool(name="revit_get_parameter_value", description="t", inputSchema={"type": "object"}),
            ProviderTool(name=SET, description="t", inputSchema={"type": "object"}, is_mutating=True),
        ]

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy"}

    async def shutdown(self) -> None:
        pass

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == SET:
            self.writes.append(dict(arguments))
            return {"status": "success"}
        return {"value": "old", "storage_type": "String"}


class _ShiftedClock(datetime):
    """approval.py reads the time through its module-level ``datetime``; this moves it forward."""

    offset = 0.0

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return datetime.now(tz) + timedelta(seconds=cls.offset)


class ModelPlan:
    def __init__(self, plan: Dict[str, Any], clock: float, doc: Optional[str]) -> None:
        self.plan_id: str = plan["plan_id"]
        self.shown_hash: str = plan["plan_hash"]
        self.actions = [(a["action_id"], canonical_arguments(a["arguments"]), a["arguments"]) for a in plan["actions"]]
        self.state = "pending"  # pending | approved | rejected | done
        self.created = clock
        self.approved_at: Optional[float] = None
        self.tampered = False
        self.doc = doc  # None: unbound plan (no live document when drafted)
        self.consumed: set = set()


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class GateMachine(RuleBasedStateMachine):
    plans = Bundle("plans")

    def __init__(self) -> None:
        super().__init__()
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-prop-"))
        self.ws = self.tmp / "ws"
        self.registry = ProviderRegistry()
        self.provider = ApprovalProvider(WorkspaceMonitor([self.ws]), self.registry, approval_mode="ask_first")
        self.registry.register(self.provider)
        self.store = FakeStore()
        self.registry.register(self.store)
        self.gate = self.provider.gate
        self.gate.override_token = TOKEN
        self.gate.approval_ttl = TTL
        self.gate.pending_ttl = TTL
        self.gate.binding_probe = self._probe
        self.saved_datetime = approval_module.datetime
        _ShiftedClock.offset = 0.0
        approval_module.datetime = _ShiftedClock
        # model
        self.baseline = "ask_first"
        self.dev_on = False
        self.auto_on = False
        self.doc: Optional[str] = "A"
        self.clock = 0.0
        self.model: Dict[str, ModelPlan] = {}
        self.expected_writes = 0

    def teardown(self) -> None:
        approval_module.datetime = self.saved_datetime
        _ShiftedClock.offset = 0.0
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------------------
    def _probe(self) -> Dict[str, Any]:
        if self.doc is None:
            return {"mock": True}
        return {"document": {"guid": DOCS[self.doc], "title": self.doc}, "revit": {"version": "2024"}}

    @property
    def dev_active(self) -> bool:
        return self.dev_on and self.baseline != "look_only"

    @property
    def effective(self) -> str:
        if self.dev_active:
            return "auto"
        if self.baseline == "ask_first" and self.auto_on:
            return "auto"
        return self.baseline

    def _executable(self, p: ModelPlan) -> bool:
        return (p.state == "approved" and not p.tampered and p.approved_at is not None
                and self.clock - p.approved_at <= TTL
                and (p.doc is None or p.doc == self.doc)
                and len(p.consumed) < len(p.actions))

    def _claimable(self, p: Optional[ModelPlan], wanted: str) -> Optional[str]:
        """The action id a strict claim would consume, or None when it must be refused."""
        if p is None or not self._executable(p):
            return None
        for action_id, canon, _ in p.actions:
            if action_id not in p.consumed and canon == wanted:
                return action_id
        return None

    def _consume(self, p: ModelPlan, action_id: str) -> None:
        p.consumed.add(action_id)
        if len(p.consumed) == len(p.actions):
            p.state = "done"

    def _plan_file(self, plan_id: str) -> Path:
        return self.gate.plans_dir / f"{plan_id}.json"

    def _check_writes(self, before: int, expected: List[Dict[str, Any]]) -> None:
        got = [canonical_arguments(w) for w in self.store.writes[before:]]
        want = [canonical_arguments(w) for w in expected]
        assert sorted(got) == sorted(want), (got, want)
        self.expected_writes += len(expected)

    # -- drafting and decisions --------------------------------------------------------
    @rule(target=plans, actions=st.lists(action_args, min_size=1, max_size=3))
    def draft(self, actions: List[Dict[str, Any]]) -> Any:
        files_before = len(list(self.gate.plans_dir.glob("plan_*.json")))
        result = _run(self.provider.execute_tool("plan_actions", {
            "actions": [{"tool": SET, "arguments": a} for a in actions]}))
        if self.dev_active:
            # Dev mode drafts nothing: writes run directly, so no plan file appears.
            assert result["status"] == "not_needed"
            assert len(list(self.gate.plans_dir.glob("plan_*.json"))) == files_before
            return multiple()
        assert result["state"] == "pending"
        self.model[result["plan_id"]] = ModelPlan(result, self.clock, self.doc)
        return result["plan_id"]

    @rule(target=plans, actions=st.lists(action_args, min_size=1, max_size=3), via=st.sampled_from(["panel", "cli"]))
    def draft_and_approve(self, actions: List[Dict[str, Any]], via: str) -> Any:
        """The usual flow: a plan is drafted and a person approves it straight away."""
        pid = self.draft(actions)
        if isinstance(pid, str):
            self._approve(pid, via, "shown")
        return pid

    @rule(pid=plans, via=st.sampled_from(["panel", "cli"]))
    def approve(self, pid: str, via: str) -> None:
        """A person approves the plan they were shown."""
        self._approve(pid, via, "shown")

    @rule(pid=plans, via=st.sampled_from(["panel", "cli", "mcp", "chat", ""]),
          which_hash=st.sampled_from(["current", "wrong", "missing"]))
    def approve_otherwise(self, pid: str, via: str, which_hash: str) -> None:
        """Approval through another channel, or with the hash of the plan as it is now, a wrong one or none."""
        self._approve(pid, via, which_hash)

    def _approve(self, pid: str, via: str, which_hash: str) -> None:
        p = self.model[pid]
        on_disk = json.loads(self._plan_file(pid).read_text())
        expected_hash = {"shown": p.shown_hash, "wrong": "sha256:" + "0" * 64}.get(which_hash)
        if which_hash == "current":
            try:
                expected_hash = plan_hash(on_disk)
            except Exception:
                expected_hash = "unhashable"
        should = (via in ("panel", "cli") and which_hash in ("shown", "current") and p.state == "pending"
                  and not p.tampered and self.clock - p.created <= TTL)
        try:
            _run(self.provider.execute_human_tool("approve_plan", {"plan_id": pid, "expected_hash": expected_hash}, via))
            ok = True
        except (BridgeError, ValueError):
            ok = False
        assert ok == should, (pid, via, which_hash, p.state, p.tampered)
        event(f"approve: {'accepted' if ok else 'refused'}")
        if ok:
            p.state, p.approved_at = "approved", self.clock

    @rule(pid=plans)
    def reject(self, pid: str) -> None:
        p = self.model[pid]
        try:
            _run(self.provider.execute_human_tool("reject_plan", {"plan_id": pid}, "panel"))
            ok = True
        except (BridgeError, ValueError):
            ok = False
        if p.state == "pending":
            assert ok
        elif p.state in ("rejected", "done"):
            assert not ok
        if ok:
            p.state = "rejected"

    # -- execution ----------------------------------------------------------------------
    @rule(pid=plans)
    def execute(self, pid: str) -> None:
        p = self.model[pid]
        before = len(self.store.writes)
        allowed = self.effective != "look_only" and self._executable(p)
        expected = [args for action_id, _, args in p.actions if action_id not in p.consumed] if allowed else []
        try:
            _run(self.provider.execute_tool("execute_plan", {"plan_id": pid}))
            raised = False
        except (BridgeError, ValueError):
            raised = True
        event(f"execute_plan: {'ran' if allowed else 'refused'} in {self.effective}")
        if not allowed:
            assert raised, "execute_plan ran a plan the model says must be refused"
        self._check_writes(before, expected)
        if allowed:
            for action_id, _, _ in p.actions:
                if action_id not in p.consumed:
                    self._consume(p, action_id)

    @rule(pid=st.one_of(st.none(), plans), index=st.integers(0, 2),
          variant=st.sampled_from(["exact", "altered", "no_plan_id", "bogus_plan_id"]), fresh=action_args)
    def direct_call(self, pid: Optional[str], index: int, variant: str, fresh: Dict[str, Any]) -> None:
        p = self.model.get(pid) if pid else None
        if p is not None:
            args = dict(p.actions[index % len(p.actions)][2])
        else:
            args = dict(fresh)
        if variant == "altered":
            args["value"] = {"altered": args.get("value")}
        if variant == "bogus_plan_id":
            args["plan_id"] = "plan_" + "f" * 12
        elif variant != "no_plan_id" and p is not None:
            args["plan_id"] = p.plan_id
        target = p if (p is not None and variant in ("exact", "altered")) else None
        claim = self._claimable(target, canonical_arguments(args)) if "plan_id" in args else None
        mode = self.effective
        rule_now = write_rule(mode, self.dev_active)
        if mode == "look_only":
            should_write = False
        elif "plan_id" not in args:
            # Unplanned writes: exactly what write_rule tells the client.
            should_write = rule_now["writes_allowed"] and not rule_now["plans_required"]
        elif mode == "auto" and not self.dev_active:
            should_write = True  # gate off: bookkeeping only, never blocks
        else:
            should_write = claim is not None  # ask_first and Dev: strict
        before = len(self.store.writes)
        try:
            _run(run_gated_tool(self.registry, self.gate, SET, args))
            ok = True
        except (BridgeError, ValueError):
            ok = False
        assert ok == should_write, (mode, variant, self.dev_active, claim)
        event(f"direct call: {variant} in {'dev' if self.dev_active else mode} -> {'write' if ok else 'refused'}")
        self._check_writes(before, [args] if should_write else [])
        if should_write and claim is not None and target is not None:
            self._consume(target, claim)

    # -- environment changes -------------------------------------------------------------
    @rule(mode=st.sampled_from(["look_only", "ask_first", "auto", "required", "bogus", ""]))
    def set_configured_mode(self, mode: str) -> None:
        self.gate.approval_mode = mode
        self.baseline = {"required": "ask_first", "look_only": "look_only", "auto": "auto"}.get(mode, "ask_first")

    @rule(on=st.booleans())
    def toggle_dev(self, on: bool) -> None:
        if on:
            dev.enable_dev(self.gate.workspace_dir, token=TOKEN)
        else:
            dev.disable_dev(self.gate.workspace_dir)
        self.dev_on = on

    @rule(on=st.booleans())
    def toggle_timed_auto(self, on: bool) -> None:
        if on:
            auto.enable_auto(self.gate.workspace_dir, 30, token=TOKEN)
        else:
            auto.disable_auto(self.gate.workspace_dir)
        self.auto_on = on

    @rule(doc=st.sampled_from(["A", "B", None]))
    def switch_document(self, doc: Optional[str]) -> None:
        self.doc = doc

    @rule(seconds=st.sampled_from([250, 500]))
    def advance_clock(self, seconds: int) -> None:
        # Steps of 250 s keep every age well away from the TTL.
        self.clock += seconds
        _ShiftedClock.offset = self.clock

    @rule(pid=plans, how=st.sampled_from(["value", "add_key", "tool", "created_at", "binding", "drop_action"]))
    def tamper(self, pid: str, how: str) -> None:
        """Edit reviewed content on disk; every such edit changes the hash."""
        path = self._plan_file(pid)
        plan = json.loads(path.read_text())
        first = plan["actions"][0]
        if how == "value":
            first["arguments"]["value"] = {"tampered": first["arguments"].get("value")}
        elif how == "add_key":
            first["arguments"]["extra"] = 1
        elif how == "tool":
            first["tool"] = "revit_delete_elements"
        elif how == "created_at":
            plan["created_at"] = "2000-01-01T00:00:00+00:00"
        elif how == "binding":
            plan["binding"] = {"doc_guid": "guid-other"}
        elif how == "drop_action" and len(plan["actions"]) > 1:
            plan["actions"].pop()
        else:
            first["arguments"]["value"] = {"tampered": True}
        path.write_text(json.dumps(plan))
        self.model[pid].tampered = True

    # -- invariants --------------------------------------------------------------------
    @invariant()
    def mode_matches_write_rule(self) -> None:
        state = self.gate.approval_state()
        assert state["mode"] == self.effective
        assert state["dev_mode"] == self.dev_active
        rule_now = write_rule(self.effective, self.dev_active)
        assert {k: state[k] for k in rule_now} == rule_now
        assert state["writes_allowed"] == (self.effective != "look_only")
        assert state["plans_required"] == (self.effective == "ask_first")

    @invariant()
    def no_unexpected_writes(self) -> None:
        assert len(self.store.writes) == self.expected_writes

    @invariant()
    def actions_run_at_most_once(self) -> None:
        for p in self.model.values():
            assert len(p.consumed) <= len(p.actions)


def test_gate_state_machine():
    run_state_machine_as_test(GateMachine, settings=settings(stateful_step_count=25, deadline=None))


# -- single properties ---------------------------------------------------------------------

def _gate(tmp: Path) -> approval_module.ApprovalGate:
    gate = approval_module.ApprovalGate(tmp, "ask_first")
    gate.override_token = TOKEN
    return gate


json_values = st.recursive(
    json_scalars, lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=4), inner, max_size=3),
    max_leaves=8,
)
argument_keys = st.text(max_size=6).filter(lambda k: k != "plan_id")


def _paths(value: Any, prefix: tuple = ()) -> List[tuple]:
    out = [prefix]
    if isinstance(value, dict):
        for k, v in value.items():
            out += _paths(v, prefix + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out += _paths(v, prefix + (i,))
    return out


def _replace(value: Any, path: tuple, new: Any) -> Any:
    if not path:
        return new
    head, rest = path[0], path[1:]
    copy = dict(value) if isinstance(value, dict) else list(value)
    copy[head] = _replace(copy[head], rest, new)
    return copy


@given(args=st.dictionaries(argument_keys, json_values, min_size=1, max_size=4), data=st.data())
def test_plan_hash_changes_when_any_argument_changes(args: Dict[str, Any], data: Any) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        plan = _gate(Path(tmp)).create_plan([{"tool": SET, "arguments": args}], [{}])
    original = plan_hash(plan)
    paths = [p for p in _paths(args) if p]
    path = data.draw(st.sampled_from(paths))
    old_leaf = args
    for step in path:
        old_leaf = old_leaf[step]
    new_leaf = data.draw(json_values.filter(lambda v: json.dumps(v, sort_keys=True) != json.dumps(old_leaf, sort_keys=True)))
    edited = json.loads(json.dumps(plan))
    edited["actions"][0]["arguments"] = _replace(args, path, new_leaf)
    assert plan_hash(edited) != original
    # Adding or removing a key changes it too.
    added = json.loads(json.dumps(plan))
    added["actions"][0]["arguments"]["__new__"] = None
    assert plan_hash(added) != original
    removed = json.loads(json.dumps(plan))
    removed["actions"][0]["arguments"].pop(path[0])
    assert plan_hash(removed) != original


@given(a=json_values, b=json_values)
def test_matching_never_looser_than_numeric_equality(a: Any, b: Any) -> None:
    """Two calls match an approved action only when their arguments are equal (5 == 5.0 aside)."""
    def norm(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return v

    same = canonical_arguments({"v": a}) == canonical_arguments({"v": b})
    assert same == (json.dumps(norm(a), sort_keys=True) == json.dumps(norm(b), sort_keys=True))


@settings(deadline=None)
@given(actions=st.lists(action_args, min_size=1, max_size=3), rounds=st.integers(1, 3),
       dev_on=st.booleans())
def test_reopened_actions_never_run_twice(actions: List[Dict[str, Any]], rounds: int, dev_on: bool) -> None:
    """Resetting action states on disk does not let execute_plan run an action again (claim markers)."""
    tmp = Path(tempfile.mkdtemp(prefix="gate-replay-"))
    try:
        registry = ProviderRegistry()
        provider = ApprovalProvider(WorkspaceMonitor([tmp]), registry, approval_mode="ask_first")
        registry.register(provider)
        store = FakeStore()
        registry.register(store)
        gate = provider.gate
        gate.override_token = TOKEN
        plan = _run(provider.execute_tool("plan_actions", {"actions": [{"tool": SET, "arguments": a} for a in actions]}))
        _run(provider.execute_human_tool("approve_plan", {"plan_id": plan["plan_id"],
                                                          "expected_hash": plan["plan_hash"]}, "panel"))
        if dev_on:
            dev.enable_dev(gate.workspace_dir, token=TOKEN)
        _run(provider.execute_tool("execute_plan", {"plan_id": plan["plan_id"]}))
        assert len(store.writes) == len(actions)
        path = gate.plans_dir / f"{plan['plan_id']}.json"
        for _ in range(rounds):
            on_disk = json.loads(path.read_text())
            on_disk["state"] = "approved"
            for a in on_disk["actions"]:
                a["state"] = "pending"
            path.write_text(json.dumps(on_disk))
            try:
                _run(provider.execute_tool("execute_plan", {"plan_id": plan["plan_id"]}))
            except (BridgeError, ValueError):
                pass
            for a in actions:
                try:
                    _run(run_gated_tool(registry, gate, SET, {**a, "plan_id": plan["plan_id"]}))
                except (BridgeError, ValueError):
                    pass
        assert len(store.writes) == len(actions)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@settings(deadline=None)
@given(actions=st.lists(action_args, min_size=1, max_size=2), dev_on=st.booleans(), timed=st.booleans())
def test_look_only_refuses_every_write(actions: List[Dict[str, Any]], dev_on: bool, timed: bool) -> None:
    """Configured look_only refuses direct, planned and execute_plan writes, whatever the panel set."""
    tmp = Path(tempfile.mkdtemp(prefix="gate-look-"))
    try:
        registry = ProviderRegistry()
        provider = ApprovalProvider(WorkspaceMonitor([tmp]), registry, approval_mode="ask_first")
        registry.register(provider)
        store = FakeStore()
        registry.register(store)
        gate = provider.gate
        gate.override_token = TOKEN
        plan = _run(provider.execute_tool("plan_actions", {"actions": [{"tool": SET, "arguments": a} for a in actions]}))
        _run(provider.execute_human_tool("approve_plan", {"plan_id": plan["plan_id"],
                                                          "expected_hash": plan["plan_hash"]}, "cli"))
        gate.approval_mode = "look_only"
        if dev_on:
            dev.enable_dev(gate.workspace_dir, token=TOKEN)
        if timed:
            auto.enable_auto(gate.workspace_dir, 30, token=TOKEN)
        calls = [lambda: provider.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})]
        for a in actions:
            calls.append(lambda a=a: run_gated_tool(registry, gate, SET, dict(a)))
            calls.append(lambda a=a: run_gated_tool(registry, gate, SET, {**a, "plan_id": plan["plan_id"]}))
        for call in calls:
            try:
                _run(call())
                raise AssertionError("look_only allowed a write")
            except BridgeError:
                pass
        assert store.writes == []
        assert gate.approval_state()["writes_allowed"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
