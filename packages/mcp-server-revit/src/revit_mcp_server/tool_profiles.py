"""Startup-only MCP tool selection by provider and manifest module identity.

Profiles reduce discovery and dispatch, not authorization. The panel constructs
its own unrestricted registry; every exposed write still uses the approval gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
from datetime import date
from typing import Any, Mapping

from .errors import BridgeError


DAILY_EXCLUDE = (
    "revit_mep", "rhino*", "speckle*", "navisworks*", "bcf_exchange*",
    "clash_triage*", "ifc*", "revit_ifc*",
)

# The `core` profile: the BIM-coordinator loop in 50 tools (plus the always-visible
# approval tools). Matches tool names, not provider/module IDs. Families: see
# docs/mcp-token-budget.md.
CORE_TOOLS = (
    "revit_get_context", "revit_health", "revit_get_document_info", "revit_get_result",
    "job_status", "job_cancel",
    "snapshot_take", "snapshot_query", "snapshot_diff", "snapshot_compute",
    "qaqc_checker_run_check", "qaqc_checker_list_issues", "qaqc_checker_resolve_issue",
    "qaqc_checker_list_rules", "qaqc_checker_list_rule_packs",
    "revit_review", "revit_warnings_delta", "revit_check_levels_grids", "revit_system_report",
    "naming_checker_check_names", "schedule_consistency_check_doors_and_rooms",
    "sheet_view_audit_run_audit", "warnings_triage_review_warnings", "model_bloat_audit",
    "links_worksets_audit_audit", "revit_cleanup_audit",
    "revit_get_rvt_links", "revit_get_link_instances", "revit_get_worksets",
    "revit_list_elements", "revit_inspect_elements", "revit_get_element_parameters",
    "revit_get_element_geometry", "revit_list_levels", "revit_list_views", "revit_list_families",
    "revit_get_categories", "revit_get_warnings", "revit_list_views_sheets_schedules",
    "model_inspector_summarize_model", "model_inspector_inspect_selection",
    "revit_get_parameters", "revit_set_parameters", "parameter_manager_filter_params",
    "revit_get_selection", "revit_set_selection", "revit_select_by_unique_ids",
    "selection_tools_select_by_query",
    "revit_execute_python", "revit_api_lookup",
)


# Tools a client should keep loaded when it defers the rest of this server behind tool
# search (docs/deferred-tool-loading.md). list_tools marks each with
# `_meta["anthropic/alwaysLoad"] = true`. Every name must be visible in every built-in
# profile, so a deferred client can always read context, search, snapshot and plan.
ALWAYS_LOADED_TOOLS = (
    "revit_get_context", "snapshot_take", "snapshot_compute", "search_tools",
    "context_report", "plan_actions", "execute_plan", "list_pending_plans",
)


# Tools hidden in every profile until the thing behind them exists. The pyRevit run tool has
# no add-in runner yet (docs/pyrevit-bridge.md), so a live call could only report bridge_unavailable.
# The pyRevit list and plan tools stay available.
HIDDEN_TOOLS = ("pyrevit_bridge_run_pyrevit_script",)


# Provider that owns plan_actions, execute_plan, list_pending_plans and the other
# approval tools. No profile may hide it: without it a client cannot see or follow
# the approval flow that guards every write.
APPROVAL_PROVIDER_ID = "approval"
# Read-only search over the full registry. Also visible in every profile, so a
# client on `core` can learn which profile shows a hidden tool.
TOOL_SEARCH_PROVIDER_ID = "tool_search"


# The `learned` profile: core + always-loaded + the most used tools of the last
# WINDOW_DAYS days, from the local usage counts (usage_counts.py). With fewer than
# LEARNED_MIN_CALLS counted calls in that window it falls back to `daily`.
LEARNED_TOP_N_DEFAULT = 25
LEARNED_TOP_N_MAX = 200
LEARNED_MIN_CALLS = 50
PROFILE_NAMES = ("full", "daily", "core", "learned", "custom")


class ToolProfileBlocked(BridgeError):
    """A registered tool is unavailable in this process's static MCP profile."""


@dataclass(frozen=True)
class ToolProfile:
    name: str = "full"
    include: tuple[str, ...] = ("*",)
    exclude: tuple[str, ...] = ()
    tools: tuple[str, ...] | None = None  # exact tool names; None means no name filter
    detail: str = ""  # how the profile was chosen, for context_report (learned profile)

    def allows(self, provider_id: str, module_id: str | None = None, tool_name: str | None = None) -> bool:
        if provider_id in (APPROVAL_PROVIDER_ID, TOOL_SEARCH_PROVIDER_ID):
            return True
        if tool_name in HIDDEN_TOOLS:
            return False
        if self.tools is not None and tool_name not in self.tools:
            return False
        identities = (provider_id,) if module_id is None else (provider_id, module_id)
        def matches(patterns: tuple[str, ...]) -> bool:
            return any(fnmatchcase(identity, pattern) for identity in identities for pattern in patterns)

        return matches(self.include) and not matches(self.exclude)

    def refusal(self, tool_name: str) -> ToolProfileBlocked:
        return ToolProfileBlocked(
            f"Tool '{tool_name}' is hidden by MCP tool profile '{self.name}'. "
            "Set MCP_REVIT_TOOL_PROFILE=daily or full (or edit MCP_REVIT_TOOL_PROFILE_FILE) "
            "and restart the MCP server to make it available."
        )


def load_tool_profile(environ: Mapping[str, str] | None = None,
                      usage_data: Mapping[str, Any] | None = None,
                      today: date | None = None) -> ToolProfile:
    """Read and validate settings once. JSON include/exclude contain ID globs.

    The optional file narrows any profile; custom requires a file. Exclusions
    always win, including daily's built-in exclusions, except that the approval
    provider is never hidden: an exclusion matching it is refused. No file is reread later.
    `learned` reads the usage counts once here (``usage_data`` overrides the file, for tests).
    """
    env = os.environ if environ is None else environ
    name = env.get("MCP_REVIT_TOOL_PROFILE", "full")
    if name not in PROFILE_NAMES:
        raise ValueError("MCP_REVIT_TOOL_PROFILE must be full, daily, core, learned, or custom")
    tools: tuple[str, ...] | None = CORE_TOOLS if name == "core" else None
    detail = ""
    if name == "learned":
        name, tools, detail = _learned(env, usage_data, today)
    filename = env.get("MCP_REVIT_TOOL_PROFILE_FILE")
    if name == "custom" and not filename:
        raise ValueError("MCP_REVIT_TOOL_PROFILE=custom requires MCP_REVIT_TOOL_PROFILE_FILE")
    include = ("*",)
    exclude = DAILY_EXCLUDE if name == "daily" else ()
    if filename is not None:
        if not filename.strip():
            raise ValueError("MCP_REVIT_TOOL_PROFILE_FILE must be a non-empty JSON file path")
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid MCP_REVIT_TOOL_PROFILE_FILE: {exc}") from exc
        if not isinstance(data, dict) or set(data) - {"include", "exclude"}:
            raise ValueError("Tool profile JSON must be an object with only include/exclude ID globs")
        for key, default in (("include", ["*"]), ("exclude", [])):
            value = data.get(key, default)
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() or item != item.strip()
                for item in value
            ):
                raise ValueError(f"Tool profile '{key}' must be an array of non-empty provider/module ID globs")
        include = tuple(data.get("include", ["*"]))
        for pattern in data.get("exclude", []):
            if fnmatchcase(APPROVAL_PROVIDER_ID, pattern):
                raise ValueError(
                    f"Invalid MCP_REVIT_TOOL_PROFILE_FILE: exclude '{pattern}' matches the "
                    f"'{APPROVAL_PROVIDER_ID}' provider; approval tools cannot be excluded "
                    "(plan_actions, execute_plan, list_pending_plans stay visible in every profile)"
                )
        exclude += tuple(data.get("exclude", []))
    return ToolProfile(name=name, include=include, exclude=exclude, tools=tools, detail=detail)


def learned_top_n(environ: Mapping[str, str]) -> int:
    raw = environ.get("MCP_REVIT_LEARNED_TOP_N", "").strip()
    if not raw:
        return LEARNED_TOP_N_DEFAULT
    if not raw.isdigit() or not 1 <= int(raw) <= LEARNED_TOP_N_MAX:
        raise ValueError(f"MCP_REVIT_LEARNED_TOP_N must be a whole number from 1 to {LEARNED_TOP_N_MAX}")
    return int(raw)


def learned_tools(usage_data: Mapping[str, Any], top_n: int = LEARNED_TOP_N_DEFAULT,
                  today: date | None = None) -> tuple[tuple[str, ...] | None, int]:
    """(tool names for `learned`, calls in the window). Names is None when there is too little data."""
    from .usage_counts import WINDOW_DAYS, top_tools

    rows = top_tools(usage_data, today=today, days=WINDOW_DAYS)
    calls = sum(row["calls"] for row in rows)
    if calls < LEARNED_MIN_CALLS:
        return None, calls
    top = tuple(row["name"] for row in rows[:top_n])
    return tuple(dict.fromkeys(CORE_TOOLS + ALWAYS_LOADED_TOOLS + top)), calls


def _learned(env: Mapping[str, str], usage_data: Mapping[str, Any] | None,
             today: date | None) -> tuple[str, tuple[str, ...] | None, str]:
    """Resolve `learned` to (profile name, tool names, detail). Falls back to `daily`."""
    from . import usage_counts

    top_n = learned_top_n(env)
    days = usage_counts.WINDOW_DAYS
    if usage_data is None:
        if not usage_counts.counts_enabled(env):
            return "daily", None, (f"learned profile fell back to daily: usage counts are off "
                                   f"({usage_counts.ENV_VAR}).")
        from .config import config
        usage_data = usage_counts.load(usage_counts.usage_file(env.get("MCP_REVIT_WORKSPACE_DIR")
                                                               or config.workspace_dir))
    names, calls = learned_tools(usage_data, top_n, today)
    if names is None:
        return "daily", None, (f"learned profile fell back to daily: {calls} tool calls counted in the "
                               f"last {days} days, {LEARNED_MIN_CALLS} needed.")
    return "learned", names, (f"learned profile: core, always-loaded and the {top_n} most used tools "
                              f"from {calls} calls in the last {days} days.")
