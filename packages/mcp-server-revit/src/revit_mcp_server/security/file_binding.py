"""Bind the content of a file a write tool reads to the plan a person approves.

A tool such as ``revit_batch_create_sheets_from_csv`` names a file (``csv_path``) and reads it
when the approved plan runs. The person only sees the path, so the file could be replaced after
approval. For a tool listed in ``CONTENT_BOUND_FILES``, drafting a plan reads the file through the
workspace check and the size cap and writes its sha256 (and, where the tool can count them, its
rows) into the action's arguments. Those arguments are part of the plan hash and of the preview.
Before anything is sent to Revit the file is read again and refused when its digest differs.

The payload builder reads the bytes it sends through ``read_verified``, so the bytes that were
checked are the bytes that are parsed: there is no second read after the check.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..errors import BridgeError, WorkspaceViolation
from .workspace import WorkspaceMonitor

DIGEST_PREFIX = "sha256:"


@dataclass(frozen=True)
class BoundFile:
    """One file input whose content is bound to the plan."""

    path_key: str
    digest_key: str
    max_bytes: int
    label: str = "file"
    count_key: Optional[str] = None
    # Counts the entries in the content for the preview; raises ValueError on content the tool
    # would refuse, so an unreadable file is refused when the plan is drafted.
    count: Optional[Callable[[bytes, Dict[str, Any]], int]] = None


def _count_csv_sheets(data: bytes, arguments: Dict[str, Any]) -> int:
    from ..providers.revit_payloads import sheets_from_csv_bytes  # lazy: providers import security

    return len(sheets_from_csv_bytes(data, arguments.get("titleblock_name"))["sheets"])


# Same cap as revit_payloads.CSV_MAX_BYTES (a test keeps them equal). Not imported here: the
# providers package imports this module through the approval gate.
CSV_MAX_BYTES = 1_000_000


# Tool name -> its content-bound file input. A file-reading write tool opts in by adding an entry.
CONTENT_BOUND_FILES: Dict[str, BoundFile] = {
    "revit_batch_create_sheets_from_csv": BoundFile(
        path_key="csv_path", digest_key="csv_sha256", max_bytes=CSV_MAX_BYTES, label="CSV",
        count_key="csv_row_count", count=_count_csv_sheets,
    ),
}

# Argument keys the server writes; the payload builders ignore them.
SERVER_KEYS = frozenset(k for b in CONTENT_BOUND_FILES.values() for k in (b.digest_key, b.count_key) if k)


def bound_file(tool: Any) -> Optional[BoundFile]:
    return CONTENT_BOUND_FILES.get(tool) if isinstance(tool, str) else None


def digest(data: bytes) -> str:
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def read_bound(tool: str, arguments: Dict[str, Any], workspace: WorkspaceMonitor) -> bytes:
    """Read the bound file of ``tool`` through the workspace check and the size cap."""
    spec = CONTENT_BOUND_FILES[tool]
    raw = arguments.get(spec.path_key)
    if not isinstance(raw, str) or not raw:
        raise BridgeError(f"{tool} needs {spec.path_key}, a {spec.label} file inside the workspace.")
    try:
        path: Path = workspace.assert_in_workspace(Path(raw))
    except WorkspaceViolation as e:
        raise BridgeError(f"{tool}: {e}.") from e
    if not path.is_file():
        raise BridgeError(f"{tool}: no {spec.label} file at {path}.")
    with open(path, "rb") as f:
        data = f.read(spec.max_bytes + 1)
    if len(data) > spec.max_bytes:
        raise BridgeError(f"{tool}: the {spec.label} is larger than {spec.max_bytes} bytes.")
    return data


def bind_actions(actions: List[Dict[str, Any]], workspace: WorkspaceMonitor) -> List[Dict[str, Any]]:
    """Return ``actions`` with the digest (and count) of each bound file written into its arguments.

    A caller-supplied digest that differs from the file is refused: only the server sets it."""
    out: List[Dict[str, Any]] = []
    for i, action in enumerate(actions):
        spec = bound_file(action.get("tool"))
        if spec is None:
            out.append(action)
            continue
        tool = action["tool"]
        arguments = dict(action.get("arguments") or {})
        try:
            data = read_bound(tool, arguments, workspace)
            count = spec.count(data, arguments) if spec.count else None
        except (BridgeError, ValueError, OSError) as e:
            raise BridgeError(f"Action {i + 1} ('{tool}'): {e} Nothing was drafted.") from e
        value = digest(data)
        supplied = arguments.get(spec.digest_key)
        if supplied is not None and supplied != value:
            raise BridgeError(
                f"Action {i + 1} ('{tool}'): {spec.digest_key} is set by the server from the {spec.label} "
                "content. Leave it out of plan_actions."
            )
        arguments[spec.digest_key] = value
        if spec.count_key and count is not None:
            arguments[spec.count_key] = count
        out.append({**action, "arguments": arguments})
    return out


def _changed(tool: str, spec: BoundFile) -> BridgeError:
    return BridgeError(
        f"{tool}: the {spec.label} changed after the plan was approved; draft a new plan. Nothing was sent to Revit."
    )


def read_verified(tool: str, arguments: Dict[str, Any], workspace: WorkspaceMonitor) -> bytes:
    """Read the bound file and refuse unless its digest equals the one recorded in the plan."""
    spec = CONTENT_BOUND_FILES[tool]
    expected = arguments.get(spec.digest_key)
    if not isinstance(expected, str) or not expected.startswith(DIGEST_PREFIX):
        raise BridgeError(
            f"{tool}: the plan holds no digest of the {spec.label} content ({spec.digest_key}). "
            "Draft a new plan so the content is recorded and shown for approval."
        )
    try:
        data = read_bound(tool, arguments, workspace)
    except BridgeError as e:
        raise BridgeError(f"{e} The plan was approved for a {spec.label} that cannot be read now; "
                          "nothing was sent to Revit.") from e
    if digest(data) != expected:
        raise _changed(tool, spec)
    return data


def verify_action(tool: Any, arguments: Any, workspace: WorkspaceMonitor) -> None:
    """Refuse a planned call whose bound file no longer matches the approved digest."""
    if bound_file(tool) is None or not isinstance(arguments, dict):
        return
    read_verified(tool, arguments, workspace)


def preview(tool: Any, arguments: Any) -> Optional[Dict[str, Any]]:
    """What the review shows for a bound file: path, digest and count."""
    spec = bound_file(tool)
    if spec is None or not isinstance(arguments, dict) or spec.digest_key not in arguments:
        return None
    shown: Dict[str, Any] = {"path": arguments.get(spec.path_key), "sha256": arguments.get(spec.digest_key)}
    if spec.count_key and spec.count_key in arguments:
        shown["rows"] = arguments.get(spec.count_key)
    return shown
