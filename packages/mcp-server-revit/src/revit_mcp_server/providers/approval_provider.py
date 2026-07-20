import logging
from typing import Any, Dict, List
from ..security.workspace import WorkspaceMonitor
from ..security.approval import ApprovalGate
from .base import AECProvider, ProviderTool
from ..config import config

logger = logging.getLogger(__name__)

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
            for action in actions:
                tool = action.get("tool")
                args = action.get("arguments", {})
                before_val = {}
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
                    except Exception as e:
                        logger.warning("Failed to get before-state for plan: %s", e)
                before_states.append(before_val)

            plan = self.gate.create_plan(actions, before_states)
            return plan

        elif name == "list_pending_plans":
            return {"plans": self.gate.list_pending_plans()}

        elif name == "approve_plan":
            plan_id = arguments.get("plan_id")
            return self.gate.update_plan_state(plan_id, "approved")

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

        plan["state"] = "partial" if had_failure else "executed"
        self.gate.save_plan(plan)
        return {"plan_id": plan_id, "state": plan["state"], "results": results}

    _capabilities = [
        ProviderTool(
            name="plan_actions",
            description="Create a draft ActionPlan of proposed modifications, capturing their before-states.",
            inputSchema={
                "type": "object",
                "properties": {
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
                    "plan_id": {"type": "string"}
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
        )
    ]
