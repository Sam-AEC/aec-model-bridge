import uuid
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..config import config
from ..errors import BridgeError

logger = logging.getLogger(__name__)

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

    def create_plan(self, actions: List[Dict[str, Any]], before_states: List[Dict[str, Any]]) -> Dict[str, Any]:
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
            "created_at": datetime.utcnow().isoformat() + "Z",
            "actions": plan_actions,
            "is_reversible": True,
            "reversible_strategy": "inverse"
        }
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

    def update_plan_state(self, plan_id: str, state: str) -> Dict[str, Any]:
        plan = self.load_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        plan["state"] = state
        self.save_plan(plan)
        return plan

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

    async def rollback_plan(self, plan_id: str, execute_fn) -> Dict[str, Any]:
        """Roll back an executed plan.

        `execute_fn` is an async callable `(tool_name, arguments) -> dict`; it MUST be
        awaited here rather than merely invoked, otherwise the inverse tool call never
        actually runs (a bare call just constructs and discards a coroutine object).
        """
        plan = self.load_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        if plan.get("state") != "executed":
            raise ValueError(f"Plan {plan_id} is in state '{plan.get('state')}', cannot rollback. Only executed plans can be rolled back.")

        errors = []
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
                errors.append(f"Rollback not supported for tool {tool}")

        if errors:
            raise BridgeError(f"Rollback encountered errors: {'; '.join(errors)}")

        plan["state"] = "rolled_back"
        self.save_plan(plan)
        return plan
