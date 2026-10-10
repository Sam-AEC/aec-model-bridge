import uuid
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..config import config
from ..errors import BridgeError
from . import proof as proof_mod

logger = logging.getLogger(__name__)

# Tools that move a plan between approval states. They stay registered (the Revit
# panel and the command-line tool use them) but are never offered to a model: an
# agent that can approve its own plan has no human gate at all.
HUMAN_ONLY_TOOLS = frozenset({"approve_plan", "reject_plan", "rollback_plan"})

# Arguments that identify or schedule a call rather than describe the change, so
# they are ignored when matching a call to an approved action.
VOLATILE_ARGUMENT_KEYS = frozenset({"plan_id", "run_async", "idempotency_key"})


def _canonical(value: Any) -> Any:
    """Normalise JSON-ish data so equal calls compare equal (key order, 5 vs 5.0)."""
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical_arguments(arguments: Any) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    kept = {k: v for k, v in args.items() if k not in VOLATILE_ARGUMENT_KEYS}
    return json.dumps(_canonical(kept), sort_keys=True, default=str, separators=(",", ":"))


class ApprovalGate:
    def __init__(self, workspace_dir: Path, approval_mode: str = config.approval_mode) -> None:
        self.workspace_dir = workspace_dir
        self.approval_mode = approval_mode
        self.plans_dir = workspace_dir / "plans"
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def _get_plan_path(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.json"

    def load_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_plan_path(plan_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load plan %s: %s", plan_id, e)
            return None

    def save_plan(self, plan: Dict[str, Any]) -> None:
        plan_id = plan["plan_id"]
        path = self._get_plan_path(plan_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2)
        except Exception as e:
            logger.error("Failed to save plan %s: %s", plan_id, e)

    def create_plan(
        self,
        actions: List[Dict[str, Any]],
        before_states: List[Dict[str, Any]],
        snapshot_id: Optional[str] = None,
        skipped: Optional[List[Dict[str, Any]]] = None,
        extra: Optional[Dict[str, Any]] = None,
        before_storage_types: Optional[List[Optional[str]]] = None,
    ) -> Dict[str, Any]:
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        plan_actions = []
        for i, action in enumerate(actions):
            act_id = f"act_{uuid.uuid4().hex[:12]}"
            before = before_states[i] if i < len(before_states) else {}
            
            arguments = action.get("arguments", {})
            diff = {
                "type": "parameter_change" if "parameter_name" in arguments else "model_modification",
                "before": before,
                "after": arguments,
                "element_count": 1
            }
            if before_storage_types and i < len(before_storage_types) and before_storage_types[i]:
                # Revit StorageType of the parameter when the before value was captured, so a
                # revert can rebuild a correctly typed value (the live read returns strings).
                diff["before_storage_type"] = before_storage_types[i]
            plan_actions.append({
                "action_id": act_id,
                "tool": action.get("tool"),
                "arguments": arguments,
                "diff": diff,
                "state": "pending"
            })

        plan = {
            "plan_id": plan_id,
            "state": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actions": plan_actions,
            "is_reversible": True,
            "reversible_strategy": "inverse"
        }
        if snapshot_id:
            plan["snapshot_id"] = snapshot_id
        if skipped:
            plan["skipped"] = skipped
        if extra:
            plan.update(extra)
        self.save_plan(plan)
        return plan

    def list_pending_plans(self) -> List[Dict[str, Any]]:
        plans = []
        for path in self.plans_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    plan = json.load(f)
                    if plan.get("state") == "pending":
                        plans.append(plan)
            except Exception:
                continue
        return plans

    def update_plan_state(self, plan_id: str, state: str, approver: Optional[str] = None,
                          via: Optional[str] = None) -> Dict[str, Any]:
        plan = self.load_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        if state in ("approved", "rejected") and plan.get("state") != "pending":
            raise ValueError(
                f"Plan {plan_id} is in state '{plan.get('state')}'; only a pending plan can be {state}."
            )
        plan["state"] = state
        now = datetime.now(timezone.utc).isoformat()
        if state == "approved":
            plan["approved_at"] = now
            if approver:
                plan["approved_by"] = str(approver)
            if via:
                plan["approved_via"] = str(via)
        elif state == "rejected":
            plan["rejected_at"] = now
            if via:
                plan["rejected_via"] = str(via)
        fill_proof = False
        if state == "executed":
            plan["executed_at"] = now
            # execute_plan writes a richer proof itself; only fill in for direct tool calls.
            try:
                fill_proof = proof_mod.read_proof(self.workspace_dir, plan_id) is None
            except ValueError:
                fill_proof = False
        self.save_plan(plan)
        if fill_proof:
            try:
                self.record_proof(plan)
            except Exception:
                logger.exception("Failed to write proof bundle for plan %s", plan_id)
        return plan

    def record_proof(self, plan: Dict[str, Any], results: Optional[List[Dict[str, Any]]] = None,
                     outcome: Optional[str] = None) -> Dict[str, Any]:
        """Write proofs/<plan_id>.json for a finished (success / partial / failed) plan."""
        bundle = proof_mod.build_proof(plan, self.workspace_dir, results=results, outcome=outcome)
        proof_mod.write_proof(self.workspace_dir, bundle)
        return bundle

    def load_proof(self, plan_id: str) -> Optional[Dict[str, Any]]:
        return proof_mod.read_proof(self.workspace_dir, plan_id)

    def check_tool_execution(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        """
        Interceptors check before execution.
        """
        if self.approval_mode != "required":
            return

        # Check if plan_id is provided
        plan_id = arguments.get("plan_id")
        if not plan_id:
            raise BridgeError(f"Approval mode is enabled. Mutating tool '{tool_name}' requires a valid 'plan_id' parameter.")

        plan = self.load_plan(plan_id)
        if not plan:
            raise BridgeError(f"Plan '{plan_id}' does not exist.")

        if plan.get("state") != "approved":
            raise BridgeError(f"Plan '{plan_id}' is in state '{plan.get('state')}', not 'approved'. Execution blocked.")

        if self._find_open_action(plan, tool_name, arguments) is None:
            raise BridgeError(
                f"Plan '{plan_id}' does not approve this call: it has no remaining approved action for "
                f"'{tool_name}' with these arguments (an action can only run once, exactly as approved). "
                "Draft a new plan for this change and ask the person to approve it."
            )

    @staticmethod
    def _find_open_action(plan: Dict[str, Any], tool_name: str, arguments: Any) -> Optional[Dict[str, Any]]:
        wanted = canonical_arguments(arguments)
        for action in plan.get("actions", []):
            if action.get("state") == "executed" or action.get("tool") != tool_name:
                continue
            if canonical_arguments(action.get("arguments", {})) == wanted:
                return action
        return None

    def mark_action_executed(self, tool_name: str, arguments: Any) -> Optional[Dict[str, Any]]:
        """Record that a gated call ran: consume the matching approved action and, once
        every action in the plan has run, move the plan to 'executed'.

        Runs on every execution path (MCP, panel, chat, recipes, run_async). Does nothing
        when the call carries no plan_id or matches no open action. Returns the plan.
        """
        plan_id = arguments.get("plan_id") if isinstance(arguments, dict) else None
        if not plan_id:
            return None
        plan = self.load_plan(plan_id)
        if not plan:
            return None
        action = self._find_open_action(plan, tool_name, arguments)
        if action is None:
            return plan
        action["state"] = "executed"
        self.save_plan(plan)
        if all(a.get("state") == "executed" for a in plan.get("actions", [])):
            return self.update_plan_state(plan_id, "executed")
        return plan

    async def rollback_plan(self, plan_id: str, execute_fn) -> Dict[str, Any]:
        """Roll back an executed plan.

        `execute_fn` is an async callable `(tool_name, arguments) -> dict`; it MUST be
        awaited here rather than merely invoked, otherwise the inverse tool call never
        actually runs (a bare call just constructs and discards a coroutine object).

        Tools without a registered rollback handler are recorded as warnings (not
        errors) so that a mixed plan (some rollback-able, some not) still rolls back
        what it can and reports clearly what was skipped.
        """
        plan = self.load_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        if plan.get("state") != "executed":
            raise ValueError(f"Plan {plan_id} is in state '{plan.get('state')}', cannot rollback. Only executed plans can be rolled back.")

        errors = []
        warnings = []
        for action in reversed(plan["actions"]):
            tool = action["tool"]
            before = action["diff"]["before"]
            if tool == "revit_set_parameter_value":
                elem_id = action["arguments"].get("element_id")
                param_name = action["arguments"].get("parameter_name")
                old_val = before.get(str(elem_id), {}).get(param_name)
                if old_val is not None:
                    try:
                        # Make sure to bypass or satisfy the approved state check
                        # We temporarily set the plan state to 'approved' for the rollback calls
                        plan["state"] = "approved"
                        self.save_plan(plan)
                        await execute_fn("revit_set_parameter_value", {
                            "element_id": elem_id,
                            "parameter_name": param_name,
                            "value": old_val,
                            "plan_id": plan_id
                        })
                    except Exception as e:
                        errors.append(f"Failed to rollback action {action.get('action_id')}: {e}")
                    finally:
                        plan["state"] = "executed"
                        self.save_plan(plan)
                else:
                    warnings.append(f"Skipped rollback for action {action.get('action_id')}: no before-value recorded")
            else:
                warnings.append(f"No rollback handler for tool '{tool}' (action {action.get('action_id')}) — skipped")

        if errors:
            plan["state"] = "partial_rollback"
            plan["rollback_warnings"] = warnings
            self.save_plan(plan)
            raise BridgeError(f"Rollback encountered errors: {'; '.join(errors)}")

        plan["state"] = "rolled_back"
        plan["rollback_warnings"] = warnings
        self.save_plan(plan)
        return plan
