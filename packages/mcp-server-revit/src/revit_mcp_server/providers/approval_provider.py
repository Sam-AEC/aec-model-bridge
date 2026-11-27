import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from ..security import binding as binding_mod
from ..security import proof as proof_mod
from ..security import rollback_preview
from ..security.approval import write_rule
from ..security.plan_review import with_review_aids
from ..security.policy import check_actions, load_policy
from ..security.workspace import WorkspaceMonitor
from ..errors import BridgeError
from ..security.approval import APPROVAL_CHANNELS, HUMAN_ONLY_TOOLS, ApprovalExpired, ApprovalGate, approver_identity
from ..security.dispatch import gate_after_result
from ..security.module_execution import authorized_module_execution
from .base import AECProvider, ProviderTool
from ..config import config

logger = logging.getLogger(__name__)

_TRUE = {"true", "yes"}
_FALSE = {"false", "no"}


def _as_number(v: Any) -> Optional[float]:
    """Return a float for numbers, bools (1/0), numeric strings and yes/no strings; else None."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip()
        if t.lower() in _TRUE:
            return 1.0
        if t.lower() in _FALSE:
            return 0.0
        try:
            f = float(t)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _values_equal(current: Any, expected: Any) -> bool:
    """Compare a live parameter value (a string) with a recorded one (any JSON type)."""
    if current is None or expected is None:
        return current is None and expected is None
    a, b = _as_number(current), _as_number(expected)
    if a is not None and b is not None:
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return str(current).strip() == str(expected).strip()


def _typed_revert_value(before: Any, storage_type: Any, new: Any) -> Tuple[Any, Optional[str]]:
    """Rebuild the JSON value for a revert from the recorded before value.

    The live read returns every value as text, but the add-in's set command needs a JSON
    number for Integer/Double/ElementId parameters. Returns (value, note); note is set when
    the type had to be guessed or the value could not be converted.
    """
    if not isinstance(before, str):
        return before, None  # already a typed JSON value
    st = storage_type.lower() if isinstance(storage_type, str) else None
    text = before.strip()
    if st == "string":
        return before, None
    if st in ("integer", "elementid"):
        f = _as_number(text)
        if f is not None and f == int(f):
            return int(f), None
        return before, f"before value {before!r} is not an integer for {storage_type} storage; drafted as text"
    if st == "double":
        f = _as_number(text)
        if f is not None:
            return f, None
        return before, f"before value {before!r} is not a number for Double storage; drafted as text"
    if st == "boolean":
        f = _as_number(text)
        if f is not None:
            return bool(f), None
    # Unknown storage type (older proof, or a reader that does not report it): only turn
    # numeric text into a number when the value the plan wrote was numeric.
    if isinstance(new, (int, float)) and not isinstance(new, bool):
        f = _as_number(text)
        if f is not None:
            value = int(f) if f == int(f) and isinstance(new, int) else f
            return value, "storage type not recorded; before value converted to a number because the plan wrote a number"
    return before, "storage type not recorded; before value kept as text"

def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _value_text(value: Any, limit: int = 60) -> str:
    """repr of a parameter value, shortened for display in a review."""
    return _clip(repr(value), limit)


def _bytes(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _capped(items: List[str], cap: int) -> List[str]:
    if len(items) <= cap:
        return items
    return items[: cap - 1] + [f"... and {len(items) - cap + 1} more not listed."]


class ApprovalProvider(AECProvider):
    def __init__(self, workspace: WorkspaceMonitor, registry: Any, approval_mode: str = config.approval_mode) -> None:
        self.workspace = workspace
        self.registry = registry
        # Use first allowed directory as workspace directory base
        workspace_base = workspace.allowed_directories[0] if workspace.allowed_directories else config.workspace_dir
        self.gate = ApprovalGate(workspace_base, approval_mode)
        self.gate.workspace_monitor = workspace

    def get_identity(self) -> str:
        return "approval"

    def get_capabilities(self) -> List[ProviderTool]:
        return self._capabilities

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy", "approval_mode": self.gate.approval_mode}

    async def shutdown(self) -> None:
        pass

    def _require_registered_tools(self, actions: List[Dict[str, Any]]) -> None:
        """A person approves what the panel lists, so every action must name a real tool."""
        for i, action in enumerate(actions):
            tool = action["tool"]
            if self.registry is None or self.registry.lookup_tool(tool) is None:
                raise BridgeError(f"Action {i + 1}: '{tool}' is not a registered tool, so it cannot be part of a plan.")

    async def _draft_binding(self, actions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Identity of the live Revit document for a new plan, or None when it cannot be read
        (mock mode, no Revit, Revit busy). A plan without a binding is not refused for that."""
        if self.gate.binding_probe is None:
            return None
        try:
            return binding_mod.binding_from_context(await asyncio.to_thread(self.gate.binding_probe), actions)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read the live document for the plan binding: %s", e)
            return None

    async def _draft_preview(self, actions: List[Dict[str, Any]],
                             before_states: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Run the draft actions in a group the add-in always rolls back (#293) and return the record that
        is stored, hashed, on the plan. None when the add-in cannot preview this plan (mock mode, an older
        add-in, an action that is not a plain model write): the plan is then drafted as before.

        This is not an approval and not an execution: no action is claimed, no proof is written and no
        plan state changes. An error or a slow Revit gives an 'unavailable' record that says why; it never
        blocks the draft and never guesses a result."""
        if self.gate.approval_mode == "look_only" or not actions or self.registry is None:
            return None
        provider = None
        for action in actions:
            found = self.registry.lookup_tool_provider(action.get("tool"))
            if found is None or (provider is not None and found is not provider):
                return None
            provider = found
        prepare = getattr(provider, "plan_preview_members", None)
        if not callable(prepare) or not callable(getattr(provider, "preview_plan_batch", None)):
            return None
        try:
            members = prepare([{**a, "action_id": f"prev_{i}"} for i, a in enumerate(actions)])
        except Exception:  # noqa: BLE001 - no preview, plan drafted as before
            logger.exception("Could not prepare a rolled-back preview")
            return None
        if not isinstance(members, list) or len(members) != len(actions):
            return None
        try:
            reply = await provider.preview_plan_batch("Preview (rolled back)", members)
        except Exception as e:  # noqa: BLE001
            logger.warning("Rolled-back preview failed: %s", e)
            return rollback_preview.unavailable(f"The preview could not be taken ({type(e).__name__}). "
                                                "Nothing was changed in the model.")
        if isinstance(reply, dict) and reply.get("status") in ("running", "queued"):
            return rollback_preview.unavailable("Revit did not finish the preview in time. The add-in rolls it "
                                                "back; nothing was kept in the model.")
        return rollback_preview.build(reply, actions, before_states)

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "plan_actions":
            actions = arguments.get("actions", [])
            self.gate.validate_actions(actions)
            self._require_registered_tools(actions)
            policy = load_policy(self.gate.workspace_dir)  # invalid file: PolicyError, nothing drafted
            check_actions(policy, actions, self.gate.workspace_dir, arguments.get("snapshot_id") or None,
                          dev_mode=self.gate.dev_mode)
            if self.gate.dev_mode:
                # Dev mode runs writes directly and audits them. Drafting a plan would be wasted
                # work that nobody approves, so say so instead of writing a plan file.
                return {
                    "status": "not_needed",
                    "dev_mode": True,
                    **write_rule("auto", True),
                    "action_count": len(actions),
                    "message": "Dev mode is on: no plan was drafted. Call the write tools directly with these "
                               "arguments and no plan_id.",
                }
            before_states = []
            before_types: List[Optional[str]] = []
            for action in actions:
                tool = action.get("tool")
                args = action.get("arguments", {})
                before_val = {}
                storage_type = None
                if tool == "revit_set_parameter_value":
                    elem_id = args.get("element_id")
                    param_name = args.get("parameter_name")
                    try:
                        read_tool = "revit_get_parameter_value"
                        provider = self.registry.lookup_tool_provider(read_tool)
                        if provider:
                            res = await provider.execute_tool(read_tool, {
                                "element_id": elem_id,
                                "parameter_name": param_name
                            })
                            val = res.get("value")
                            before_val = {str(elem_id): {param_name: val}}
                            st = res.get("storage_type")
                            storage_type = st if isinstance(st, str) else None
                    except Exception as e:
                        logger.warning("Failed to get before-state for plan: %s", e)
                before_states.append(before_val)
                before_types.append(storage_type)

            plan = self.gate.create_plan(
                actions,
                before_states,
                snapshot_id=arguments.get("snapshot_id") or None,
                skipped=arguments.get("skipped") or None,
                before_storage_types=before_types,
                review=arguments.get("review"),
                binding=await self._draft_binding(actions),
                policy_hash=policy.hash,
                rollback_preview=await self._draft_preview(actions, before_states),
            )
            plan = with_review_aids(plan, self.gate.workspace_dir)
            return plan

        elif name == "list_pending_plans":
            plans, hidden = self.gate.pending_listing(arguments.get("include_expired") is True)
            return {"plans": [with_review_aids(p, self.gate.workspace_dir) for p in plans], "expired_hidden": hidden}

        elif name == "policy_show":
            return load_policy(self.gate.workspace_dir).effective()

        elif name in HUMAN_ONLY_TOOLS:
            # Never through the generic tool path (MCP, chat, recipes, plans, modules):
            # only the panel route calls execute_human_tool, and the CLI uses the gate.
            raise BridgeError(
                f"'{name}' is run by a person in the Revit panel or with aec-model-bridge-approve, "
                "not through a tool call."
            )

        elif name == "execute_plan":
            return await self._execute_plan(arguments.get("plan_id"))

        elif name == "get_proof_bundle":
            plan_id = arguments.get("plan_id")
            bundle = self.gate.load_proof(plan_id)
            if bundle is None:
                raise ValueError(f"No proof bundle for plan {plan_id}: the plan has not finished executing.")
            return bundle

        elif name == "plan_revert":
            return await self._plan_revert(arguments.get("plan_id"), bool(arguments.get("allow_conflicts", False)))

        else:
            raise ValueError(f"Unknown approval tool '{name}'")

    async def execute_human_tool(self, name: str, arguments: Dict[str, Any], via: str) -> Dict[str, Any]:
        """Approve, reject or roll back a plan for a person.

        ``via`` is set by the calling route ('panel' or 'cli'). Caller-supplied
        ``approved_via``/``approver`` arguments are ignored; ``approved_by`` records the
        OS account running this process. Approving needs ``expected_hash``, the hash of
        the plan the person was shown (``plan_hash`` from list_pending_plans).
        """
        if via not in APPROVAL_CHANNELS:
            raise BridgeError("Plans are approved only from the Revit panel or the command-line tool.")
        if not isinstance(arguments, dict):
            raise BridgeError("Arguments must be an object.")
        plan_id = arguments.get("plan_id")
        if name == "approve_plan":
            return self.gate.update_plan_state(
                plan_id, "approved", approver=approver_identity(), via=via,
                expected_hash=arguments.get("expected_hash"),
            )
        if name == "reject_plan":
            return self.gate.update_plan_state(plan_id, "rejected", via=via)
        if name == "rollback_plan":
            async def execute_helper(t_name, t_args):
                prov = self.registry.lookup_tool_provider(t_name)
                if not prov:
                    raise ValueError(f"Provider not found for tool {t_name}")
                return await prov.execute_tool(t_name, t_args)

            return await self.gate.rollback_plan(plan_id, execute_helper)
        raise BridgeError(f"'{name}' is not a plan decision.")

    async def _execute_plan(self, plan_id: str) -> Dict[str, Any]:
        # One live-document read serves every action of this plan (see ApprovalGate.reuse_binding_probe).
        with self.gate.reuse_binding_probe():
            return await self._execute_plan_actions(plan_id)

    async def _execute_plan_actions(self, plan_id: str) -> Dict[str, Any]:
        """Run every action in an approved plan, report-and-continue on failure.

        A partially-failed plan is left in state 'approved' (not 'executed') so it is
        never mistaken for fully applied and never silently retried by rollback; failed
        and succeeded actions are both recorded so nothing is dropped from the audit trail.
        """
        self.gate.refuse_if_look_only()  # before any plan state is touched
        plan = self.gate.load_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        if plan.get("state") != "approved":
            raise ValueError(
                f"Plan {plan_id} is in state '{plan.get('state')}', not 'approved'. Execution blocked."
            )
        try:
            self.gate.verify_approved(plan)
        except ApprovalExpired:
            self.gate.expire_plan(plan_id)
            raise
        self.gate.verify_binding(plan)  # whole plan refused up front, so a wrong document consumes nothing
        self.gate.verify_bound_files(plan)  # a changed bound file (e.g. the CSV) also refuses it up front

        # The policy may have tightened since drafting: re-check before the first action runs.
        check_actions(load_policy(self.gate.workspace_dir), plan["actions"], self.gate.workspace_dir,
                      plan.get("snapshot_id"), dev_mode=self.gate.dev_mode)

        # A profile is a discovery/dispatch choice, not a failed model action.
        # Refuse the entire pending plan before consuming anything or saving a
        # partial state, so the person can still run it in a full-profile process.
        profile_check = getattr(self.registry, "validate_profile_call", None)
        if profile_check is not None:
            for action in plan["actions"]:
                if action.get("state") in ("pending", None):
                    profile_check(action["tool"], action.get("arguments", {}))

        results = []
        pending_results = []
        for previous in plan["actions"]:
            if previous.get("state") != "running":
                continue
            key = previous.get("in_flight_key")
            if key and key.startswith("job_"):
                resume = f'revit_job_status(job_id="{key[4:]}")'
            elif key:
                resume = f'revit_get_result(request_id="{key}")'
            else:
                resume = "Inspect the model and recover the running action through the approval CLI."
            pending_results.append({"action_id": previous.get("action_id"), "key": key, "resume": resume})
        had_failure = any(a.get("state") in ("failed", "abandoned") for a in plan["actions"])
        # True once any action of this plan has been claimed (now or in an earlier run).
        started = had_failure or bool(pending_results) or any(
            a.get("state") not in ("pending", None) for a in plan["actions"])
        if not started:
            batch = self._plan_batch(plan_id, plan)
            if batch is not None:
                return await self._execute_plan_batch(plan_id, plan, *batch)
        for action in plan["actions"]:
            if action.get("state") not in ("pending", None):
                continue  # already consumed (e.g. a direct call earlier): never run an approved action twice
            tool = action["tool"]
            args = dict(action["arguments"]) if isinstance(action.get("arguments"), dict) else {}
            args["plan_id"] = plan_id
            # Each action is consumed before it runs, exactly like a direct call, so a
            # concurrent execute_plan or direct call cannot run it a second time.
            try:
                claim = self.gate.claim_action(tool, args)
            except Exception as e:
                if not started:
                    # Refused before anything ran: the plan stays approved and can run once the cause is fixed.
                    raise
                had_failure = True
                results.append({"action_id": action.get("action_id"), "tool": tool, "error": str(e)})
                continue
            started = True
            provider = self.registry.lookup_tool_provider(tool)
            if not provider:
                had_failure = True
                error = f"Provider not found for tool {tool}"
                self.gate.finish_action(claim, ok=False, error=error)
                results.append({"action_id": action["action_id"], "tool": tool, "error": error})
                continue
            try:
                with authorized_module_execution(tool):
                    result = await provider.execute_tool(tool, args)
            except Exception as e:
                had_failure = True
                self.gate.finish_action(claim, ok=False, error=str(e))
                results.append({"action_id": action["action_id"], "tool": tool, "error": str(e)})
                continue
            verdict = gate_after_result(self.gate, claim, tool, result)
            entry = {"action_id": action["action_id"], "tool": tool, "result": result}
            if verdict.state == "failed":
                had_failure = True
                entry["error"] = verdict.error
            elif verdict.state == "running":
                pending_results.append({"action_id": action["action_id"], "key": verdict.key, "resume": verdict.resume})
            results.append(entry)

        return self._finish_plan_run(plan_id, plan, results, had_failure, pending_results)

    def _finish_plan_run(self, plan_id: str, plan: Dict[str, Any], results: List[Dict[str, Any]],
                         had_failure: bool, pending_results: List[Dict[str, Any]],
                         extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Settle the plan state and proof after its actions ran (one by one or as one batch)."""
        plan = self.gate.load_plan(plan_id) or plan
        if plan.get("state") == "approved" and had_failure:
            # Some action could not even be claimed; the plan is not fully applied.
            plan["state"] = "partial"
        elif plan.get("state") == "approved" and not plan.get("actions"):
            plan["state"] = "executed"
        if not pending_results:
            plan.setdefault("executed_at", datetime.now(timezone.utc).isoformat())
        self.gate.save_plan(plan)
        n_failed = sum(1 for r in results if "error" in r)
        # Proof outcome: "failed" when nothing was applied; "success" only if every action ran.
        if not had_failure:
            outcome = "success"
        elif n_failed == len(results):
            outcome = "failed"
        else:
            outcome = "partial"
        if not pending_results:
            try:
                self.gate.record_proof(plan, results=results, outcome=outcome)
            except Exception:
                logger.exception("Failed to write proof bundle for plan %s", plan_id)
        reply = {"plan_id": plan_id, "state": plan["state"], "results": results, "ok": not had_failure}
        if extra:
            reply.update(extra)
        if pending_results:
            reply["pending_results"] = pending_results
        return reply

    def _plan_batch(self, plan_id: str, plan: Dict[str, Any]) -> Optional[Tuple[Any, List[Dict[str, Any]]]]:
        """(provider, add-in members) when every action of this not-yet-started plan can run as one
        revit.execute_plan_batch (one Revit turn, one undo step, #294); None for today's path."""
        actions = plan.get("actions") or []
        if not actions or any(a.get("state") not in ("pending", None) for a in actions):
            return None
        provider = None
        for action in actions:
            found = self.registry.lookup_tool_provider(action.get("tool")) if self.registry is not None else None
            if found is None or (provider is not None and found is not provider):
                return None
            provider = found
        prepare = getattr(provider, "plan_batch_members", None)
        if not callable(prepare) or not callable(getattr(provider, "execute_plan_batch", None)):
            return None
        try:
            members = prepare(plan_id, actions)
        except Exception:  # noqa: BLE001 - fall back to one action at a time
            logger.exception("Could not prepare plan %s as one batch", plan_id)
            return None
        if not isinstance(members, list) or len(members) != len(actions):
            return None
        return provider, members

    @staticmethod
    def _plan_title(plan: Dict[str, Any]) -> str:
        review = plan.get("review")
        summary = review.get("summary") if isinstance(review, dict) else None
        if isinstance(summary, str) and summary.strip():
            return _clip(" ".join(summary.split()), 80)
        n = len(plan.get("actions") or [])
        return f"{n} action{'s' if n != 1 else ''}"

    async def _execute_plan_batch(self, plan_id: str, plan: Dict[str, Any], provider: Any,
                                  members: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run the plan as one add-in batch: one Revit turn, one TransactionGroup, one undo step.

        Approval bookkeeping is the same as the one-by-one path: every action is claimed before
        anything runs (a claim that fails after the first is reported as that action's error, as
        today), and each claimed action's outcome is recorded from the add-in's per-action result.
        The add-in stops at the first failure and rolls the whole group back, so a failed batch
        records every claimed action as failed: the one that failed, the ones rolled back with it,
        and the ones not run. When Revit has not answered after the extra waits, the claimed actions
        stay 'running' (consumed, never replayed) for a person to check and recover."""
        n = len(plan["actions"])
        entries: List[Optional[Dict[str, Any]]] = [None] * n
        claimed: List[Tuple[int, Dict[str, Any], Any, Dict[str, Any]]] = []
        had_failure = False
        started = False
        for index, (action, member) in enumerate(zip(plan["actions"], members)):
            tool = action["tool"]
            args = dict(action["arguments"]) if isinstance(action.get("arguments"), dict) else {}
            args["plan_id"] = plan_id
            try:
                claim = self.gate.claim_action(tool, args)
            except Exception as e:
                if not started:
                    raise  # refused before anything ran: the plan stays approved
                had_failure = True
                entries[index] = {"action_id": action.get("action_id"), "tool": tool, "error": str(e)}
                continue
            started = True
            claimed.append((index, action, claim, member))

        pending_results: List[Dict[str, Any]] = []
        extra: Dict[str, Any] = {"batched": True}

        def fail_all(error: str) -> None:
            for index, action, claim, _member in claimed:
                self.gate.finish_action(claim, ok=False, error=error)
                entries[index] = {"action_id": action["action_id"], "tool": action["tool"], "error": error}

        reply: Any = None
        if claimed:
            try:
                reply = await provider.execute_plan_batch(
                    plan_id, self._plan_title(plan), [member for _i, _a, _c, member in claimed])
            except Exception as e:
                had_failure = True
                fail_all(str(e) or type(e).__name__)
                claimed = []

        if claimed and isinstance(reply, dict) and reply.get("status") in ("running", "queued") \
                and isinstance(reply.get("request_id"), str) and reply["request_id"]:
            request_id = reply["request_id"]
            for index, action, _claim, _member in claimed:
                pending_results.append({
                    "action_id": action["action_id"], "key": None,
                    "resume": (f'Inspect the model. revit_get_result(request_id="{request_id}") shows the plan '
                               "batch outcome; a person then closes these actions with the approval CLI."),
                })
                entries[index] = {"action_id": action["action_id"], "tool": action["tool"],
                                  "result": {"status": "running", "request_id": request_id}}
            extra["batch_request_id"] = request_id
        elif claimed:
            results_in = reply.get("results") if isinstance(reply, dict) else None
            ids = [member["action_id"] for _i, _a, _c, member in claimed]
            if not isinstance(results_in, list) or len(results_in) != len(claimed) or any(
                    not isinstance(r, dict) or r.get("action_id") != i for r, i in zip(results_in, ids)):
                had_failure = True
                fail_all("The add-in returned a plan batch result that does not match the request. "
                         "Check the model before drafting a new plan.")
            else:
                committed = reply.get("committed") is True
                extra["undo"] = {"one_step": committed, "group_name": reply.get("group_name")}
                for (index, action, claim, _member), answer in zip(claimed, results_in):
                    tool = action["tool"]
                    entry: Dict[str, Any] = {"action_id": action["action_id"], "tool": tool}
                    if answer.get("ok") is True and committed:
                        result = answer.get("result")
                        entry["result"] = result
                        verdict = gate_after_result(self.gate, claim, tool, result)
                        if verdict.state == "failed":
                            had_failure = True
                            entry["error"] = verdict.error
                    else:
                        had_failure = True
                        error = str(answer.get("error") or "The plan batch did not apply this action.")
                        self.gate.finish_action(claim, ok=False, error=error)
                        entry["error"] = error
                        for flag in ("rolled_back", "not_run", "group_not_committed"):
                            if answer.get(flag) is True:
                                entry[flag] = True
                        if isinstance(answer.get("result"), dict):
                            entry["result"] = answer["result"]
                    entries[index] = entry

        results = [e for e in entries if e is not None]
        return self._finish_plan_run(plan_id, plan, results, had_failure, pending_results, extra)

    async def _plan_revert(self, plan_id: str, allow_conflicts: bool) -> Dict[str, Any]:
        """Draft (never execute) a plan that restores the recorded before values.

        Refuses unless the original plan fully executed, every reverted element has a
        recorded before value, and the model still holds the value the plan wrote.
        Elements whose current value differs are conflicts: refused unless
        allow_conflicts=True, in which case they are listed in the plan's hashed review block
        (``review.conflicts`` and ``review.warnings``) for the approver.
        """
        bundle = self.gate.load_proof(plan_id)
        if bundle is None:
            raise ValueError(f"Cannot revert plan {plan_id}: no proof bundle (plan has not been executed).")
        if bundle.get("outcome") != "success":
            raise ValueError(
                f"Cannot revert plan {plan_id}: its execution outcome is '{bundle.get('outcome')}', "
                "not a fully executed 'success'."
            )
        plan = self.gate.load_plan(plan_id)
        if not plan or plan.get("state") != "executed":
            raise ValueError(
                f"Cannot revert plan {plan_id}: plan state is '{plan.get('state') if plan else 'missing'}', not 'executed'."
            )
        elements = bundle.get("elements", [])
        if not elements:
            raise ValueError(f"Cannot revert plan {plan_id}: the proof bundle records no parameter changes.")
        missing = [e for e in elements if not e.get("before_recorded")]
        if missing:
            ids = ", ".join(f"{e.get('element_id')}/{e.get('parameter')}" for e in missing)
            raise ValueError(f"Cannot revert plan {plan_id}: no before value was recorded for: {ids}.")

        read_tool = "revit_get_parameter_value"
        provider = self.registry.lookup_tool_provider(read_tool)
        if not provider:
            raise ValueError(f"Cannot revert plan {plan_id}: cannot verify current values ({read_tool} unavailable).")

        actions, before_states, conflicts, notes = [], [], [], []
        for e in elements:
            eid, pname = e["element_id"], e["parameter"]
            try:
                res = await provider.execute_tool(read_tool, {"element_id": eid, "parameter_name": pname})
            except Exception as exc:
                raise ValueError(f"Cannot revert plan {plan_id}: failed to read current value of {eid}/{pname}: {exc}")
            current = res.get("value")
            if not _values_equal(current, e.get("new")):
                conflicts.append({"element_id": eid, "parameter": pname,
                                  "expected_current": e.get("new"), "actual_current": current,
                                  "revert_to": e.get("before")})
                if not allow_conflicts:
                    continue
            value, note = _typed_revert_value(e.get("before"), e.get("before_storage_type"), e.get("new"))
            if note:
                notes.append(f"{eid}/{pname}: {note}")
            actions.append({"tool": "revit_set_parameter_value",
                            "arguments": {"element_id": eid, "parameter_name": pname, "value": value}})
            before_states.append({str(eid): {pname: current}})

        if conflicts and not allow_conflicts:
            detail = "; ".join(
                f"{c['element_id']}/{c['parameter']}: expected {c['expected_current']!r}, now {c['actual_current']!r}"
                for c in conflicts
            )
            raise ValueError(
                f"Cannot revert plan {plan_id}: the model changed since it ran ({detail}). "
                "Re-run with allow_conflicts=true to draft a plan that lists these elements for explicit review."
            )

        # Conflicts, notes and warnings go into the hashed, displayed review block, built
        # inside a byte budget so a revert with many drifted elements can still be drafted.
        warnings: List[str] = []
        for a in bundle.get("other_actions", []):
            if a.get("status") == "executed":
                warnings.append(_clip(
                    f"Action {a.get('action_id')} ({a.get('tool')}) is not a parameter change and is not reverted.",
                    1000))
        if conflicts:
            warnings.append(
                f"{len(conflicts)} element(s) were changed since the original plan ran; this revert overwrites "
                "their current values (see Conflicts)."
            )
        assumptions = [_clip(n, 1000) for n in notes]
        listed: List[Dict[str, Any]] = []
        overflow: List[str] = []
        used = _bytes(warnings) + _bytes(assumptions)
        for c in conflicts:
            entry = {
                "element_id": c["element_id"] if isinstance(c["element_id"], (int, str)) else str(c["element_id"]),
                "parameter": _clip(str(c["parameter"]), 200),
                "expected_current": _value_text(c["expected_current"]),
                "actual_current": _value_text(c["actual_current"]),
                "revert_to": _value_text(c["revert_to"]),
            }
            size = _bytes(entry)
            if len(listed) < proof_mod.REVIEW_MAX_ITEMS["conflicts"] and used + size <= 40000:
                listed.append(entry)
                used += size
            else:
                overflow.append(f"{c['element_id']}/{c['parameter']}")
        # Conflicts past the detailed list are still named, by element and parameter.
        chunk: List[str] = []
        for name in overflow:
            if used > proof_mod.REVIEW_BUDGET_BYTES - 2000:
                break
            if sum(len(x) + 2 for x in chunk) + len(name) > 900:
                text = "Also changed (details in the proof bundle): " + ", ".join(chunk)
                warnings.append(text)
                used += len(text.encode("utf-8")) + 4
                chunk = []
            chunk.append(name)
        if chunk:
            warnings.append("Also changed (details in the proof bundle): " + ", ".join(chunk))
        review = {
            "summary": f"Revert of plan {plan_id}: restore the recorded before values of {len(actions)} parameter(s).",
            "assumptions": _capped(assumptions, 100),
            "warnings": _capped(warnings, 200),
            "conflicts": listed,
        }
        if _bytes(review) > proof_mod.REVIEW_BUDGET_BYTES:
            # Last resort: drop detail, never fail the draft.
            review["conflicts"] = listed[: max(1, len(listed) // 4)]
            review["warnings"] = review["warnings"][:50] + [
                f"... {len(conflicts)} conflict(s) in total; the rest are not listed, see the proof bundle."]
        return self.gate.create_plan(actions, before_states, snapshot_id=plan.get("snapshot_id"),
                                     extra={"reverts_plan_id": plan_id}, review=review,
                                     binding=await self._draft_binding([]))

    _capabilities = [
        ProviderTool(
            name="plan_actions",
            description=("Create a draft ActionPlan of proposed modifications, capturing their before-states. "
                         "Only when revit_get_context shows server.plans_required true; otherwise call the write "
                         "tool directly with no plan_id."),
            inputSchema={
                "type": "object",
                "properties": {
                    "snapshot_id": {"type": "string"},
                    "skipped": {"type": "array", "items": {"type": "object"}},
                    "review": {"type": "object"},
                    "actions": {
                        "type": "array",
                        "items": {
                              "type": "object",
                              "properties": {
                                  "tool": {"type": "string"},
                                  "arguments": {"type": "object"}
                              },
                              "required": ["tool", "arguments"]
                        }
                    }
                },
                "required": ["actions"]
            }
        ),
        ProviderTool(
            name="list_pending_plans",
            description="List pending ActionPlans waiting for review. Plans older than pending_ttl are left out "
                        "and counted in expired_hidden; include_expired shows them (they cannot be approved).",
            inputSchema={"type": "object", "properties": {"include_expired": {"type": "boolean", "description": "Also list expired pending plans."}}}
        ),
        ProviderTool(
            name="approve_plan",
            description="Approve a pending ActionPlan for execution (human only: the Revit panel or "
                        "aec-model-bridge-approve). expected_hash is the plan_hash of the plan that was shown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "expected_hash": {"type": "string"}
                },
                "required": ["plan_id", "expected_hash"]
            }
        ),
        ProviderTool(
            name="reject_plan",
            description="Reject a pending or approved (not yet executed) ActionPlan (human only).",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"}
                },
                "required": ["plan_id"]
            }
        ),
        ProviderTool(
            name="rollback_plan",
            description="Rollback an executed ActionPlan using inverse values.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"}
                },
                "required": ["plan_id"]
            }
        ),
        ProviderTool(
            name="execute_plan",
            description="Run every action in an approved ActionPlan. Report-and-continue: a partial "
                        "failure leaves the plan in state 'approved' with per-action results recorded, "
                        "rather than silently skipping the rest or marking the plan fully executed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"}
                },
                "required": ["plan_id"]
            }
        ),
        ProviderTool(
            name="policy_show",
            description="Show the effective workspace policy (blocked and allowed tools, allowed categories, "
                        "blocked parameters, plan size limits) and its hash. Read-only. An invalid policy file "
                        "is reported as an error and refuses all writes.",
            inputSchema={"type": "object", "properties": {}}
        ),
        ProviderTool(
            name="get_proof_bundle",
            description="Return the proof bundle of a finished ActionPlan (success, partial or failed). Read-only.",
            inputSchema={
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"]
            }
        ),
        ProviderTool(
            name="plan_revert",
            description="Draft a new ActionPlan restoring the before values recorded in an executed plan's "
                        "proof bundle. Never executes; the draft still needs human approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "allow_conflicts": {"type": "boolean"}
                },
                "required": ["plan_id"]
            }
        )
    ]
