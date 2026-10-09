import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from ..security.workspace import WorkspaceMonitor
from ..security.approval import ApprovalGate
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

class ApprovalProvider(AECProvider):
    def __init__(self, workspace: WorkspaceMonitor, registry: Any, approval_mode: str = config.approval_mode) -> None:
        self.workspace = workspace
        self.registry = registry
        # Use first allowed directory as workspace directory base
        workspace_base = workspace.allowed_directories[0] if workspace.allowed_directories else config.workspace_dir
        self.gate = ApprovalGate(workspace_base, approval_mode)

    def get_identity(self) -> str:
        return "approval"

    def get_capabilities(self) -> List[ProviderTool]:
        return self._capabilities

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy"}

    async def shutdown(self) -> None:
        pass

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "plan_actions":
            actions = arguments.get("actions", [])
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
            )
            return plan

        elif name == "list_pending_plans":
            return {"plans": self.gate.list_pending_plans()}

        elif name == "approve_plan":
            plan_id = arguments.get("plan_id")
            return self.gate.update_plan_state(plan_id, "approved", approver=arguments.get("approver"))

        elif name == "reject_plan":
            plan_id = arguments.get("plan_id")
            return self.gate.update_plan_state(plan_id, "rejected")

        elif name == "rollback_plan":
            plan_id = arguments.get("plan_id")
            async def execute_helper(t_name, t_args):
                prov = self.registry.lookup_tool_provider(t_name)
                if not prov:
                    raise ValueError(f"Provider not found for tool {t_name}")
                return await prov.execute_tool(t_name, t_args)

            return await self.gate.rollback_plan(plan_id, execute_helper)

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

    async def _execute_plan(self, plan_id: str) -> Dict[str, Any]:
        """Run every action in an approved plan, report-and-continue on failure.

        A partially-failed plan is left in state 'approved' (not 'executed') so it is
        never mistaken for fully applied and never silently retried by rollback; failed
        and succeeded actions are both recorded so nothing is dropped from the audit trail.
        """
        plan = self.gate.load_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        if plan.get("state") != "approved":
            raise ValueError(
                f"Plan {plan_id} is in state '{plan.get('state')}', not 'approved'. Execution blocked."
            )

        results = []
        had_failure = False
        for action in plan["actions"]:
            tool = action["tool"]
            args = dict(action["arguments"])
            args["plan_id"] = plan_id
            provider = self.registry.lookup_tool_provider(tool)
            if not provider:
                action["state"] = "failed"
                had_failure = True
                results.append({"action_id": action["action_id"], "tool": tool, "error": f"Provider not found for tool {tool}"})
                continue
            try:
                result = await provider.execute_tool(tool, args)
                action["state"] = "executed"
                results.append({"action_id": action["action_id"], "tool": tool, "result": result})
            except Exception as e:
                action["state"] = "failed"
                had_failure = True
                results.append({"action_id": action["action_id"], "tool": tool, "error": str(e)})

        n_failed = sum(1 for r in results if "error" in r)
        plan["state"] = "partial" if had_failure else "executed"
        plan["executed_at"] = datetime.now(timezone.utc).isoformat()
        self.gate.save_plan(plan)
        # Proof outcome: "failed" when nothing was applied; "success" only if every action ran.
        if not had_failure:
            outcome = "success"
        elif n_failed == len(results):
            outcome = "failed"
        else:
            outcome = "partial"
        try:
            self.gate.record_proof(plan, results=results, outcome=outcome)
        except Exception:
            logger.exception("Failed to write proof bundle for plan %s", plan_id)
        return {"plan_id": plan_id, "state": plan["state"], "results": results}

    async def _plan_revert(self, plan_id: str, allow_conflicts: bool) -> Dict[str, Any]:
        """Draft (never execute) a plan that restores the recorded before values.

        Refuses unless the original plan fully executed, every reverted element has a
        recorded before value, and the model still holds the value the plan wrote.
        Elements whose current value differs are conflicts: refused unless
        allow_conflicts=True, in which case they are listed on the plan for review.
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

        extra: Dict[str, Any] = {"reverts_plan_id": plan_id}
        if conflicts:
            extra["conflicts"] = conflicts
        if notes:
            extra["notes"] = notes
        unreverted = [a for a in bundle.get("other_actions", []) if a.get("status") == "executed"]
        if unreverted:
            extra["warnings"] = [
                f"Action {a.get('action_id')} ({a.get('tool')}) is not a parameter change and is not reverted."
                for a in unreverted
            ]
        return self.gate.create_plan(actions, before_states, snapshot_id=plan.get("snapshot_id"), extra=extra)

    _capabilities = [
        ProviderTool(
            name="plan_actions",
            description="Create a draft ActionPlan of proposed modifications, capturing their before-states.",
            inputSchema={
                "type": "object",
                "properties": {
                    "snapshot_id": {"type": "string"},
                    "skipped": {"type": "array", "items": {"type": "object"}},
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
            description="List all pending ActionPlans waiting for review.",
            inputSchema={"type": "object", "properties": {}}
        ),
        ProviderTool(
            name="approve_plan",
            description="Approve a pending ActionPlan for execution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "approver": {"type": "string"}
                },
                "required": ["plan_id"]
            }
        ),
        ProviderTool(
            name="reject_plan",
            description="Reject and archive a pending ActionPlan.",
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
