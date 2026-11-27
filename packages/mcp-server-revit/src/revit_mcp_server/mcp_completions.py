"""completion/complete for prompt and resource-template arguments (issue #206).

Arguments named ``category``, ``level`` and ``parameter`` complete from the newest snapshot in
the workspace. Read-only: nothing is written and Revit is not asked. With no snapshot, an
unreadable one, or any other argument name, the answer is an empty list, never an error.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.types import Completion

from . import mcp_resources

MAX_VALUES = 100
LEVEL_CATEGORY = "OST_Levels"
LEVEL_NAME_KEYS = ("DATUM_TEXT", "Name")
ARGUMENTS = ("category", "level", "parameter")


def _elements(workspace_dir: Path) -> list[dict]:
    files = mcp_resources.snapshot_files(workspace_dir)
    data = mcp_resources._load_json(files[0]) if files else None
    items = data.get("elements") if data else None
    return [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []


def _level_name(el: dict) -> str | None:
    if el.get("name") not in (None, ""):
        return str(el["name"])
    params = el.get("params") if isinstance(el.get("params"), dict) else {}
    for key in LEVEL_NAME_KEYS:
        p = params.get(key)
        value = p.get("v") if isinstance(p, dict) else p
        if value not in (None, ""):
            return str(value)
    return None


def _candidates(argument: str, elements: list[dict]) -> set[str]:
    if argument == "category":
        return {str(e["category"]) for e in elements if e.get("category")}
    if argument == "level":
        names = (_level_name(e) for e in elements if e.get("category") == LEVEL_CATEGORY)
        return {n for n in names if n}
    return {str(k) for e in elements if isinstance(e.get("params"), dict) for k in e["params"]}


def _matches(value: str, prefix: str, argument: str) -> bool:
    low = value.lower()
    if low.startswith(prefix):
        return True
    return argument == "category" and low.startswith("ost_") and low[4:].startswith(prefix)


def complete(workspace_dir: Any, argument_name: str, typed: str) -> Completion:
    empty = Completion(values=[], total=0, hasMore=False)
    if argument_name not in ARGUMENTS or workspace_dir is None:
        return empty
    try:
        found = _candidates(argument_name, _elements(Path(workspace_dir)))
    except (OSError, ValueError, TypeError):
        return empty
    prefix = (typed or "").lower()
    hits = sorted((v for v in found if _matches(v, prefix, argument_name)), key=lambda v: (v.lower(), v))
    return Completion(values=hits[:MAX_VALUES], total=len(hits), hasMore=len(hits) > MAX_VALUES)
