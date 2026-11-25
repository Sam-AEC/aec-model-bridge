"""Ask the client's user one structured question for a missing or ambiguous input.

MCP elicitation (`elicitation/create`, form mode) lets the server ask the person at
the client a short question with a flat schema of primitive fields. This module has
the one helper the server uses for it, `elicit_choice`, and `InputNeeded`, the error a
tool raises when it needs such an input.

Rules (see docs/elicitation.md):

- Only when the client declared the elicitation capability. Otherwise, and when the
  person declines, cancels, does not answer in time or gives an invalid answer, the
  call ends with the plain refusal that names the missing input.
- Never for plan approval and never from the approval tools. Answers pass through
  the AI client, so they are not a person's approval. `elicit_choice` refuses to run
  for an approval tool or when called from an approval module.
- Never for secrets. Field names and questions that look like a request for a
  password, token or key are refused.
"""
from __future__ import annotations

import asyncio
import copy
import difflib
import inspect
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .errors import BridgeError
from .security.approval import HUMAN_ONLY_TOOLS
from .security.safe_paths import safe_child

logger = logging.getLogger(__name__)

# Seconds to wait for the person's answer before the call ends with the plain refusal.
ELICITATION_TIMEOUT_S = 120.0
# Questions asked for one tool call at most (one input at a time).
MAX_ROUNDS = 3
MAX_OPTIONS = 25
MAX_TEXT = 200

# Tools that may never ask: everything that drafts, approves, runs, rejects, rolls back
# or reports plans. Approval comes from a person in the panel or the CLI, never from an answer.
APPROVAL_TOOLS = frozenset(HUMAN_ONLY_TOOLS | {
    "plan_actions", "execute_plan", "plan_revert", "list_pending_plans",
    "policy_show", "get_proof_bundle",
})
_APPROVAL_NAME = re.compile(r"(approv|plan|rollback|revert|proof|polic)", re.IGNORECASE)

# Modules that hold the approval gate. Code running in them can never call elicit_choice.
FORBIDDEN_CALLER_MODULES = frozenset({
    "revit_mcp_server.security.approval",
    "revit_mcp_server.security.approval_override",
    "revit_mcp_server.security.plan_review",
    "revit_mcp_server.security.dispatch",
    "revit_mcp_server.security.gating",
    "revit_mcp_server.providers.approval_provider",
    "revit_mcp_server.approve_cli",
    "revit_mcp_server.panel_server",
})

_SECRET = re.compile(r"(passw|secret|token|api[_ -]?key|credential|private[_ -]?key|\bpin\b)", re.IGNORECASE)
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,39}")


class ElicitationForbidden(RuntimeError):
    """elicit_choice was called where asking is never allowed (approval tools, secrets)."""


class InputNeeded(BridgeError):
    """A tool needs one more input from the person: a choice from options or a short text.

    ``str(exc)`` is the plain refusal returned when the server cannot ask. ``apply``
    takes the call's arguments and the answer and returns new arguments (a copy).
    """

    def __init__(
        self,
        refusal: str,
        *,
        question: str,
        field: str,
        apply: Callable[[Dict[str, Any], str], Dict[str, Any]],
        options: Optional[Sequence[str]] = None,
        title: str = "",
    ) -> None:
        super().__init__(refusal)
        self.refusal = refusal
        self.question = question
        self.field = field
        self.apply = apply
        self.options = list(options) if options else None
        self.title = title


def elicitation_allowed(tool: str) -> bool:
    """False for every approval tool, by name and by pattern (fail closed)."""
    return bool(tool) and tool not in APPROVAL_TOOLS and not _APPROVAL_NAME.search(tool)


def client_supports_elicitation(session: Any) -> bool:
    """True when the client declared form elicitation in its initialize capabilities."""
    try:
        caps = session.client_params.capabilities
        elicitation = caps.elicitation
    except AttributeError:
        return False
    if elicitation is None:
        return False
    # No mode named means form (older clients); a client that names only url cannot show a form.
    return getattr(elicitation, "form", None) is not None or getattr(elicitation, "url", None) is None


def _guard(tool: str, field: str, message: str) -> None:
    if not elicitation_allowed(tool):
        raise ElicitationForbidden(f"'{tool}' may not ask the person anything; plan approval is never asked for this way.")
    for frame in inspect.stack()[2:12]:
        if frame.frame.f_globals.get("__name__") in FORBIDDEN_CALLER_MODULES:
            raise ElicitationForbidden("The approval code may not ask the person anything through the AI client.")
    if not _FIELD.fullmatch(field or ""):
        raise ElicitationForbidden("The answer field must be a short lower-case name.")
    if _SECRET.search(field) or _SECRET.search(message):
        raise ElicitationForbidden("Secrets are never asked for through the AI client.")


def _schema(field: str, title: str, options: Optional[List[str]]) -> Dict[str, Any]:
    prop: Dict[str, Any] = {"type": "string", "title": title or field.replace("_", " ")}
    if options:
        prop["enum"] = options
    else:
        prop["minLength"] = 1
        prop["maxLength"] = MAX_TEXT
    return {"type": "object", "properties": {field: prop}, "required": [field]}


async def elicit_choice(
    session: Any,
    message: str,
    options: Optional[Sequence[str]] = None,
    *,
    tool: str,
    field: str = "choice",
    title: str = "",
    timeout: float = ELICITATION_TIMEOUT_S,
    related_request_id: Any = None,
) -> Optional[str]:
    """Ask one question; return the answer, or None to fall back to the plain refusal.

    With ``options`` the person picks one of them (an enum). Without, they type a short
    text. None when the client cannot ask, or the person declines, cancels, times out or
    gives an answer outside the options. Raises ElicitationForbidden for approval tools,
    approval callers and secret-looking questions, whatever the client supports.
    """
    _guard(tool, field, message)
    choices = [str(o) for o in options][:MAX_OPTIONS] if options else None
    if session is None or not client_supports_elicitation(session):
        return None
    schema = _schema(field, title, choices)
    try:
        result = await asyncio.wait_for(
            session.elicit_form(message, schema, related_request_id), timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.info("Elicitation for %s timed out after %ss", tool, timeout)
        return None
    except Exception as exc:  # the client refused or failed: fall back, never guess
        logger.info("Elicitation for %s failed: %s", tool, exc)
        return None
    if getattr(result, "action", None) != "accept":
        return None
    value = (getattr(result, "content", None) or {}).get(field)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if choices is not None:
        return value if value in choices else None
    return value if 0 < len(value) <= MAX_TEXT else None


# --------------------------------------------------------------- shared inputs


def close_matches(word: str, known: Sequence[str], n: int = 5) -> List[str]:
    """Known names close to ``word``: same text ignoring case first, then difflib matches."""
    lower = word.lower()
    same = [k for k in known if k.lower() == lower and k != word]
    near = difflib.get_close_matches(word, list(known), n=n, cutoff=0.75)
    out: List[str] = []
    for k in same + near:
        if k != word and k not in out:
            out.append(k)
    return out[:n]


# Export tools that take an output file path: tool -> (argument, extension or None for "from format").
EXPORT_PATH_TOOLS: Dict[str, tuple] = {
    # revit_export_dwg takes an output folder (the add-in names each file after its view), so it does not ask.
    "revit_export_ifc": ("output_path", ".ifc"),
    "revit_export_navisworks": ("output_path", ".nwc"),
    "revit_export_image": ("output_path", ".png"),
    "revit_export": ("path", None),
}
EXPORT_FORMAT_EXT = {"pdf": ".pdf", "dwg": ".dwg", "ifc": ".ifc", "nwc": ".nwc"}
_FILE_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}")


def missing_export_path(tool: str, arguments: Any, workspace_root: Optional[Path]) -> Optional[InputNeeded]:
    """InputNeeded when an export tool was called without its output file, else None."""
    spec = EXPORT_PATH_TOOLS.get(tool)
    if spec is None or not isinstance(arguments, dict):
        return None
    key, ext = spec
    value = arguments.get(key)
    if isinstance(value, str) and value.strip():
        return None
    if ext is None:
        ext = EXPORT_FORMAT_EXT.get(str(arguments.get("format") or "").lower())
        if ext is None:
            return None  # the tool refuses a missing or unknown format itself
    refusal = (
        f"{tool} needs {key}: the output file, a path inside the workspace ending in {ext}. "
        f"Call again with {key} set."
    )

    def apply(args: Dict[str, Any], answer: str) -> Dict[str, Any]:
        stem = answer[: -len(ext)] if answer.lower().endswith(ext) else answer

        def refuse(_reason: str) -> Exception:
            return InputNeeded(
                refusal + " The answer was not a plain file name.",
                question="", field="file_name", apply=apply,
            )

        if workspace_root is None or stem.endswith((".", " ")):
            raise refuse("name")
        new = copy.deepcopy(args)
        new[key] = str(safe_child(workspace_root, stem, ext, _FILE_STEM, refuse))
        return new

    return InputNeeded(
        refusal,
        question=(f"{tool} needs a file name for the export. It is saved in the workspace "
                  f"folder with the extension {ext}."),
        field="file_name",
        title=f"File name ({ext})",
        apply=apply,
    )


# ------------------------------------------------------- view and sheet names

# Tools that name an existing view (view_name; the answer sets view_id) or sheet (a sheet
# number), and where. Revit resolves these by exact name or number. They are checked before the
# call only when the server may ask (no plan needed, no plan_id), so no approved action changes.
VIEW_SHEET_REFS: Dict[str, tuple] = {
    "revit_make_sheet": (("views[].view_name", "view"),),
    "revit_place_views": (("sheet", "sheet"), ("views[].view_name", "view")),
    "revit_set_view_templates": (("views[].view_name", "view"),),
    "revit_make_view_template": (("view.view_name", "view"),),
    "revit_align_crop": (("reference.view_name", "view"), ("views[].view_name", "view")),
    "revit_add_revision_clouds": (("view.view_name", "view"),),
    "revit_make_schedule": (("sheet.number", "sheet"),),
    "revit_export": (("sheets[]", "sheet"),),
    "revit_issue_revision": (("sheets[]", "sheet"),),
    "revit_update_sheets": (("sheets[].number", "sheet"),),
}
# Longest name the list tool accepts as name_contains.
MAX_NEEDLE = 100
# list_rows(kind, needle) -> awaitable of (rows, total) or None when the model cannot be read.
RowLister = Callable[[str, str], Any]
_SEGMENT = re.compile(r"([a-z_]+)(?:\[(\d+)\])?")


def _name_refs(arguments: Any, path: str) -> List[tuple]:
    """(label, value) for each non-empty string at ``path`` (``a.b``, ``a[].b``, ``a[]``)."""
    found: List[tuple] = []

    def walk(node: Any, parts: List[str], label: str) -> None:
        head, rest = parts[0], parts[1:]
        key = head[:-2] if head.endswith("[]") else head
        if not isinstance(node, dict) or key not in node:
            return
        value = node[key]
        where = f"{label}.{key}" if label else key
        if head.endswith("[]"):
            if not isinstance(value, list):
                return
            for i, item in enumerate(value):
                if rest:
                    walk(item, rest, f"{where}[{i}]")
                elif isinstance(item, str) and item.strip():
                    found.append((f"{where}[{i}]", item.strip()))
        elif rest:
            walk(value, rest, where)
        elif isinstance(value, str) and value.strip():
            found.append((where, value.strip()))

    walk(arguments, path.split("."), "")
    return found


def _locate(args: Dict[str, Any], label: str) -> tuple:
    """(container, key) for a concrete label such as ``views[1].view_name`` or ``sheets[0]``."""
    node: Any = args
    parts = label.split(".")
    for n, part in enumerate(parts):
        key, index = _SEGMENT.fullmatch(part).groups()
        if index is not None:
            node, key = node[key], int(index)
        if n == len(parts) - 1:
            return node, key
        node = node[key]
    raise KeyError(label)


def _exact_key(kind: str) -> str:
    return "number" if kind == "sheet" else "name"


def _row_keys(kind: str, row: Dict[str, Any]) -> List[str]:
    keys = [str(row.get("number") or "")] if kind == "sheet" else []
    keys.append(str(row.get("name") or ""))
    return [k for k in keys if k]


def view_sheet_candidates(kind: str, wanted: str, rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows the person may have meant. Empty when exactly one row matches as Revit matches
    (view name or sheet number, character for character) or when nothing is close."""
    exact = [r for r in rows if str(r.get(_exact_key(kind)) or "") == wanted]
    if len(exact) == 1:
        return []
    if exact:
        return list(exact)
    needle = wanted.casefold()
    same = [r for r in rows if any(k.casefold() == needle for k in _row_keys(kind, r))]
    part = [r for r in rows if r not in same and any(
        needle in k.casefold() or k.casefold() in needle for k in _row_keys(kind, r))]
    found = same + part
    if not found:
        by_key: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            for k in _row_keys(kind, r):
                by_key.setdefault(k, []).append(r)
        for k in difflib.get_close_matches(wanted, list(by_key), n=MAX_OPTIONS, cutoff=0.6):
            found.extend(r for r in by_key[k] if r not in found)
    return found


def _labels(kind: str, rows: Sequence[Dict[str, Any]]) -> List[str]:
    if kind == "sheet":
        base = [f"{r.get('number')} - {r.get('name')}" if r.get("name") else str(r.get("number")) for r in rows]
    else:
        base = [str(r.get("name") or "") for r in rows]
    return [f"{b} [id {r.get('id')}]" if base.count(b) > 1 else b for b, r in zip(base, rows)]


def ambiguous_view_or_sheet(
    tool: str, label: str, kind: str, wanted: str, rows: Sequence[Dict[str, Any]], more: int = 0,
) -> Optional[InputNeeded]:
    """InputNeeded for one view or sheet reference that does not match exactly one, else None.

    At most MAX_OPTIONS candidates are offered; the rest, plus ``more`` rows the list did not
    return, are counted as "+N more" in the question and the refusal."""
    found = view_sheet_candidates(kind, wanted, rows)
    if not found:
        return None
    shown = found[:MAX_OPTIONS]
    hidden = len(found) - len(shown) + max(0, more)
    labels = _labels(kind, shown)
    row_of = dict(zip(labels, shown))
    word = kind
    several = all(str(r.get(_exact_key(kind)) or "") == wanted for r in shown)
    what = f"matches several {word}s" if several else f"does not match a {word} exactly"
    extra = f" (+{hidden} more)" if hidden else ""
    how = "view_id or the exact view name" if kind == "view" else "the exact sheet number"
    refusal = (
        f"{tool}: {word} '{wanted}' in {label} {what}. Candidates: "
        + ", ".join(f"'{x}'" for x in labels) + f"{extra}. Call again with {label} set to {how}."
    )

    def apply(args: Dict[str, Any], chosen: str) -> Dict[str, Any]:
        row = row_of[chosen]
        new = copy.deepcopy(args)
        container, key = _locate(new, label)
        if kind == "view":
            container.pop("view_name", None)
            container["view_id"] = int(row["id"])
        else:
            container[key] = str(row["number"])
        return new

    question = f"{word.capitalize()} '{wanted}' ({label}) {what}. Which {word} do you mean?"
    if hidden:
        question += f" +{hidden} more not shown; decline and call again with {how} to pick another."
    return InputNeeded(refusal, question=question, field=word, title=word.capitalize(), options=labels, apply=apply)


async def check_view_sheet_names(tool: str, arguments: Any, list_rows: RowLister) -> Optional[InputNeeded]:
    """InputNeeded for the first view or sheet reference in ``arguments`` that needs a choice, or None.

    ``list_rows(kind, needle)`` returns ``(rows, total)`` for rows whose name (or sheet number)
    contains ``needle``, or None when the model cannot be read; then that reference is not
    checked and the tool resolves it itself, as before."""
    refs = VIEW_SHEET_REFS.get(tool)
    if not refs or not isinstance(arguments, dict):
        return None
    for path, kind in refs:
        for label, wanted in _name_refs(arguments, path):
            if len(wanted) > MAX_NEEDLE:
                continue
            listed = await list_rows(kind, wanted)
            if listed is None:
                continue
            rows, total = listed
            more = max(0, total - len(rows))
            if not rows:
                # No name contains it: look for a name inside it or a close spelling in the full list.
                listed = await list_rows(kind, "")
                if listed is None:
                    continue
                rows, more = listed[0], 0
            need = ambiguous_view_or_sheet(tool, label, kind, wanted, rows, more=more)
            if need is not None:
                return need
    return None
