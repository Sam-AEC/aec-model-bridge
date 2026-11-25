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
    "revit_export_dwg": ("output_path", ".dwg"),
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
