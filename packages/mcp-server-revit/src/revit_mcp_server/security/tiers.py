"""Tool tiers for policy: read, write, script, export. Every tool resolves to exactly one.

A policy can turn a tier off (``allowed_tiers`` / ``blocked_tiers``). The tier is derived from the
existing tool metadata, never from the tool's own claim about policy:

* ``script``: runs caller-supplied code or reaches arbitrary API members (``SCRIPT_TOOLS``).
* ``write``: ``is_mutating`` tools, plus ``plan_actions``, ``execute_plan`` and ``plan_revert``.
* ``export``: not mutating, but the ``readOnlyHint`` annotation is false: it writes files or other
  state outside the model (exports, reports, baselines, saved queries), except the UI-only tools
  in ``READ_OVERRIDES``.
* ``read``: everything else.

``CONTROL_TOOLS`` (approve, reject, roll back, list plans, show policy, proof bundle, job status and
cancel) are always callable, so a person can always reject a plan and see what is going on. Their
tier is ``read`` and no policy can hide them.
"""
from __future__ import annotations

from typing import Any, Optional

TIERS = ("read", "write", "script", "export")

CONTROL_TOOLS = frozenset({
    "approve_plan", "reject_plan", "rollback_plan", "list_pending_plans", "get_proof_bundle",
    "policy_show", "job_status", "job_cancel", "revit_job_status", "revit_job_cancel", "revit_get_result",
})

SCRIPT_TOOLS = frozenset({
    "revit_execute_python", "revit_invoke_method", "revit_reflect_get", "revit_reflect_set",
    "navisworks_invoke_method", "navisworks_reflect_get", "navisworks_reflect_set",
    "rhino_run_python", "rhino_invoke_method", "rhino_reflect_get", "rhino_reflect_set",
    "pyrevit_bridge_run_pyrevit_script", "pyrevit_bridge_plan_run_pyrevit_script",
    "revit_run_job",  # a job can wrap a script
    "revit_raw_command",  # forwards any add-in command, including revit.execute_python
})

WRITE_TOOLS = frozenset({"plan_actions", "execute_plan", "plan_revert"})

# Not read-only by annotation, but they only change selection, preview or in-memory UI state.
READ_OVERRIDES = frozenset({"revit_select_by_unique_ids", "revit_preview_elements", "revit_clear_preview",
                            "navisworks_activate_viewpoint", "navisworks_refresh"})

_registry: Any = None


def set_registry(registry: Any) -> None:
    """Called by build_registry so policy checks inside plans can look up a tool's tier."""
    global _registry
    _registry = registry


def tier_of(name: str, tool: Any, provider_id: str = "") -> str:
    """The one tier of a tool. Raises ValueError for a tool without a name or gate flags."""
    if not name or tool is None or not hasattr(tool, "is_mutating"):
        raise ValueError(f"Tool {name!r} has no tool metadata, so it has no tier.")
    if name in CONTROL_TOOLS:
        return "read"
    if name in SCRIPT_TOOLS:
        return "script"
    if name in WRITE_TOOLS or tool.is_mutating:
        return "write"
    from ..tool_metadata import annotations_for
    if not hasattr(tool, "destructive") or getattr(tool, "name", None) != name:  # minimal tool record
        from types import SimpleNamespace
        tool = SimpleNamespace(name=name, is_mutating=tool.is_mutating, destructive=getattr(tool, "destructive", False))
    if annotations_for(provider_id, tool).readOnlyHint is False and name not in READ_OVERRIDES:
        return "export"
    return "read"


def resolve_tier(name: str) -> Optional[str]:
    """Tier of a registered tool by name, or None when it cannot be looked up."""
    reg = _registry
    if reg is None:
        return None
    try:
        tool = reg.lookup_tool(name)
        provider = reg.lookup_tool_provider(name)
        if tool is None or provider is None:
            return None
        return tier_of(name, tool, provider.get_identity())
    except Exception:  # noqa: BLE001 - an unknown or profile-hidden tool has no tier here
        return None
