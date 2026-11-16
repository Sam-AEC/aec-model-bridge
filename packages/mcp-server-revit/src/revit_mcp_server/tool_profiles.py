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
from typing import Mapping

from .errors import BridgeError


DAILY_EXCLUDE = (
    "revit_mep", "rhino*", "speckle*", "navisworks*", "bcf_exchange*",
    "clash_triage*", "ifc*", "revit_ifc*",
)


# Provider that owns plan_actions, execute_plan, list_pending_plans and the other
# approval tools. No profile may hide it: without it a client cannot see or follow
# the approval flow that guards every write.
APPROVAL_PROVIDER_ID = "approval"


class ToolProfileBlocked(BridgeError):
    """A registered tool is unavailable in this process's static MCP profile."""


@dataclass(frozen=True)
class ToolProfile:
    name: str = "full"
    include: tuple[str, ...] = ("*",)
    exclude: tuple[str, ...] = ()

    def allows(self, provider_id: str, module_id: str | None = None) -> bool:
        if provider_id == APPROVAL_PROVIDER_ID:
            return True
        identities = (provider_id,) if module_id is None else (provider_id, module_id)
        def matches(patterns: tuple[str, ...]) -> bool:
            return any(fnmatchcase(identity, pattern) for identity in identities for pattern in patterns)

        return matches(self.include) and not matches(self.exclude)

    def refusal(self, tool_name: str) -> ToolProfileBlocked:
        return ToolProfileBlocked(
            f"Tool '{tool_name}' is hidden by MCP tool profile '{self.name}'. "
            "Change MCP_REVIT_TOOL_PROFILE / MCP_REVIT_TOOL_PROFILE_FILE and restart "
            "the MCP server to make it available."
        )


def load_tool_profile(environ: Mapping[str, str] | None = None) -> ToolProfile:
    """Read and validate settings once. JSON include/exclude contain ID globs.

    The optional file narrows any profile; custom requires a file. Exclusions
    always win, including daily's built-in exclusions, except that the approval
    provider is never hidden: an exclusion matching it is refused. No file is reread later.
    """
    env = os.environ if environ is None else environ
    name = env.get("MCP_REVIT_TOOL_PROFILE", "full")
    if name not in {"full", "daily", "custom"}:
        raise ValueError("MCP_REVIT_TOOL_PROFILE must be full, daily, or custom")
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
    return ToolProfile(name=name, include=include, exclude=exclude)
