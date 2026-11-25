"""revit_perf_report: per-command timings from the add-in's /health, as a short table.

/health is answered on the add-in's HTTP thread, so this works while Revit is busy and never
queues work on the Revit thread. Add-ins that predate the ``timings`` field are reported as such.
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import BridgeError
from .base import ProviderTool

DEFAULT_TOP = 15
MAX_TOP = 100
_COLUMNS = ("tool", "count", "p50_ms", "p95_ms", "max_ms", "avg_bytes")

PERF_TOOLS = [
    ProviderTool(
        name="revit_perf_report",
        description=(
            "Read-only. Per-command timings the Revit add-in has recorded since Revit started: call count, "
            "p50, p95 and max milliseconds and average response bytes, sorted by p95 (slowest first), plus "
            "the current queue depth. Reads the add-in's /health, so it answers while Revit is busy and "
            "queues nothing. An older add-in without timings is reported, not an error. Needs no approval."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "top": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_TOP,
                    "description": f"How many commands to list, slowest p95 first. Default {DEFAULT_TOP}.",
                },
            },
            "required": [],
        },
    ),
]

# Mock mode only. The numbers are invented to show the shape of the reply.
MOCK_HEALTH: dict[str, Any] = {
    "status": "healthy",
    "queue_depth": 0,
    "timings": {
        "revit.list_elements_by_category": {"count": 42, "p50_ms": 180, "p95_ms": 950, "max_ms": 2400, "avg_bytes": 48000},
        "revit.get_element_parameters": {"count": 120, "p50_ms": 35, "p95_ms": 140, "max_ms": 410, "avg_bytes": 3100},
        "revit.execute_python": {"count": 9, "p50_ms": 600, "p95_ms": 4100, "max_ms": 7300, "avg_bytes": 1500},
        "revit.get_document_info": {"count": 15, "p50_ms": 12, "p95_ms": 30, "max_ms": 55, "avg_bytes": 700},
    },
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return float(value)


def _rows(timings: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    skipped = 0
    for tool, stats in timings.items():
        if not isinstance(tool, str) or not isinstance(stats, dict):
            skipped += 1
            continue
        row: dict[str, Any] = {"tool": tool}
        for key in _COLUMNS[1:]:
            number = _number(stats.get(key))
            row[key] = None if number is None else (int(number) if key == "count" else round(number, 1))
        rows.append(row)
    rows.sort(key=lambda r: (r["p95_ms"] is None, -(r["p95_ms"] or 0), r["tool"]))
    return rows, skipped


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _table(rows: list[dict[str, Any]]) -> str:
    lines = [" | ".join(_COLUMNS), " | ".join("---" for _ in _COLUMNS)]
    lines += [" | ".join(_cell(row[c]) for c in _COLUMNS) for row in rows]
    return "\n".join(lines)


def _top(arguments: dict[str, Any]) -> int:
    top = arguments.get("top", DEFAULT_TOP)
    if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= MAX_TOP:
        raise ValueError(f"top must be an integer from 1 to {MAX_TOP}.")
    return top


def format_report(health: dict[str, Any], top: int = DEFAULT_TOP, *, mock: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "tool": "revit_perf_report", "queue_depth": health.get("queue_depth")}
    if mock:
        result["mock"] = True
    timings = health.get("timings")
    if not isinstance(timings, dict):
        result.update(
            timings_available=False,
            commands=[],
            table="",
            message=(
                "The loaded add-in does not report per-command timings in /health; it is older than this "
                "tool. Rebuild and reinstall the add-in, then restart Revit. Queue depth is shown if reported."
            ),
        )
        return result
    rows, skipped = _rows(timings)
    shown = rows[:top]
    result.update(
        timings_available=True,
        commands_recorded=len(rows),
        commands=shown,
        table=_table(shown) if shown else "",
    )
    notes = []
    if mock:
        notes.append("Mock mode: sample numbers, not measured from any Revit session.")
    if not rows:
        notes.append("The add-in reports timings but has recorded no commands yet.")
    elif len(rows) > len(shown):
        notes.append(f"Showing the {len(shown)} slowest of {len(rows)} commands by p95; raise top to see more.")
    if skipped:
        notes.append(f"{skipped} malformed timing entries were ignored.")
    if notes:
        result["message"] = " ".join(notes)
    return result


def perf_report(bridge: Any, arguments: dict[str, Any], *, live: bool) -> dict[str, Any]:
    top = _top(arguments)
    if not live:
        return format_report(MOCK_HEALTH, top, mock=True)
    probe = getattr(bridge, "_get", None)
    if not callable(probe):
        raise ValueError("This bridge cannot read the add-in's /health.")
    health = probe("/health")
    if not isinstance(health, dict):
        raise BridgeError("The add-in's /health reply is not a JSON object.")
    if health.get("status") != "healthy" and not isinstance(health.get("timings"), dict):
        detail = health.get("error") or health.get("status") or "no status"
        raise BridgeError(f"The Revit add-in is not healthy, so there are no timings to report: {detail}")
    return format_report(health, top)
