"""revit_reconnect: point this server at a live Revit session again after Revit restarted.

It only re-reads the session registry and repeats the health handshake. It sends no model request,
does not touch plans or the approval gate, and never picks a session by itself when more than one
is open. A pending plan is still checked against the live document by the gate when it runs.
"""
from __future__ import annotations

from typing import Any

from .base import ProviderTool

CHECK_MODEL_WARNING = (
    "Check the model before repeating an earlier write: a write sent before Revit closed may or may not "
    "have been applied, and its result is no longer available from the old session."
)
PLANS_UNTOUCHED_NOTE = (
    "Pending plans and approvals were not changed. The approval gate still compares each plan with the "
    "live document before it runs."
)

RECONNECT_TOOLS = [
    ProviderTool(
        name="revit_reconnect",
        description=(
            "Use after Revit was restarted or closed, when Revit calls are refused because the selected session "
            "changed or closed. Lists the live Revit sessions (process id, version, start time, active document "
            "title) and re-binds this server to one of them, without restarting the MCP client. Binds the only "
            "live session by itself; with several, nothing changes until you pass pid. It repeats the health "
            "check and sends no model request. It does not touch pending plans or approvals, and the approval "
            "gate and panel token are unchanged. Check the model before repeating an earlier write. Needs no "
            "approval. Needs a live Revit connection without an explicit bridge URL."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Process id of the Revit session to bind, from an earlier revit_reconnect list. "
                    "Needed only when more than one Revit session is open.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
]


def version_matches(host_version: str, wanted: str | None) -> bool:
    """Same rule as discovery.select_switch: equal, or the session version starts with the wanted text."""
    if not wanted:
        return True
    wanted = wanted.strip().lower()
    have = host_version.lower()
    return have == wanted or have.startswith(wanted)


def read_pid(arguments: dict[str, Any]) -> int | None:
    pid = arguments.get("pid")
    if pid is None:
        return None
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise ValueError("pid must be a positive integer: the process id of a Revit session from the list.")
    return pid


def describe(switch: Any, document: str | None, current_pid: int | None) -> dict[str, Any]:
    """One session for the reply. The registry endpoint and session token are never included."""
    return {
        "pid": switch.pid,
        "host_version": switch.host_version,
        "started_at": switch.started_at,
        "document": document,
        "bound": current_pid is not None and switch.pid == current_pid,
    }


def pick(sessions: list[Any], pid: int | None) -> Any | None:
    """The session to bind: the named one, or the only one. None when several are open and none is named.
    Raises ValueError when nothing matches (fail closed, no guess)."""
    if not sessions:
        raise ValueError(
            "No live Revit session was found in the registry. Start Revit, wait until the AEC Model Bridge "
            "add-in has loaded, then call revit_reconnect again. Nothing was changed."
        )
    if pid is not None:
        for switch in sessions:
            if switch.pid == pid:
                return switch
        known = ", ".join(str(s.pid) for s in sessions)
        raise ValueError(
            f"No live Revit session has process id {pid}. Live sessions: {known}. Nothing was changed."
        )
    return sessions[0] if len(sessions) == 1 else None
