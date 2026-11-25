"""The review that ``aec-model-bridge-approve`` prints before a person approves a plan.

``build_review`` turns a stored plan into a plain dictionary: per action, one row per element
with the parameter and its old and new value, and every other argument of the action; plus
counts, warnings, the plan hash, the approval mode, expiry and the document binding. ``render_review`` prints it as plain text
(ASCII borders, wrapped cells, no ANSI unless asked for and supported). ``--json`` prints the
dictionary itself.

Everything here is read-only. Old values and arguments come from the hashed plan content.
Element names and marks come from the plan's snapshot when it can be read; they are labels
only and are not part of the plan hash.
"""
from __future__ import annotations

import json
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .security import proof as proof_mod
from .security.approval import running_actions
from .security.plan_review import ID_KEYS, ID_LIST_KEYS, element_ids_of, review_aids
from .security.proof import normalize_review

REVIEW_SCHEMA = "aec-model-bridge/plan-review"
REVIEW_SCHEMA_VERSION = 1

DEFAULT_MAX_ROWS = 30         # change rows printed before "+N more, use --all"
VALUE_MAX_CHARS = 300         # characters of one value printed before it is cut
DEFAULT_WIDTH = 100
MIN_WIDTH, MAX_WIDTH = 60, 200

NOT_CAPTURED = "(not captured)"
EMPTY = "(empty)"
NO_ELEMENT = "(no element named)"
SAME_AS_ABOVE = "(same as above)"
SAME_MIN_CHARS = 40

_ARG_SKIP = ("plan_id",)


def safe_text(value: Any) -> str:
    """Make model-controlled text safe to print: control and format characters
    (ESC/ANSI/OSC sequences, carriage returns, bidi overrides, zero-width marks)
    are shown as visible escapes instead of being sent to the terminal."""
    out = []
    for ch in str(value):
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"):
            code = ord(ch)
            out.append(f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}")
        else:
            out.append(ch)
    return "".join(out)


# ---- building the review (data) ------------------------------------------------------------


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _snapshot_labels(workspace_dir: Optional[Path], snapshot_id: Any) -> Dict[str, Dict[str, str]]:
    """element_id -> {name, mark, unique_id} from the plan's snapshot; {} when unreadable."""
    if not workspace_dir or not isinstance(snapshot_id, str) or not snapshot_id:
        return {}
    try:
        path = proof_mod.snapshot_file(Path(workspace_dir) / "snapshots", snapshot_id)
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
        out: Dict[str, Dict[str, str]] = {}
        for el in snap.get("elements", []) if isinstance(snap, dict) else []:
            if not isinstance(el, dict) or el.get("element_id") is None:
                continue
            info: Dict[str, str] = {}
            if _scalar(el.get("name")) and str(el["name"]).strip():
                info["name"] = str(el["name"])
            params = el.get("params") if isinstance(el.get("params"), dict) else {}
            mark = params.get("Mark")
            mark = mark.get("v") if isinstance(mark, dict) else mark
            if _scalar(mark) and str(mark).strip():
                info["mark"] = str(mark)
            if _scalar(el.get("uid")) and str(el["uid"]).strip():
                info["unique_id"] = str(el["uid"])
            out[str(el["element_id"])] = info
        return out
    except Exception:  # noqa: BLE001 - labels are optional; an unreadable snapshot only hides them
        return {}


def _parse_time(stamp: Any) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _expiry(plan: Dict[str, Any], gate: Any, reason: Optional[str]) -> Dict[str, Any]:
    state = plan.get("state")
    if state == "approved":
        rule, ttl, start = "approval_ttl", gate.approval_ttl, plan.get("approved_at")
    elif state == "pending":
        rule, ttl, start = "pending_ttl", gate.pending_ttl, plan.get("created_at")
    else:
        return {"applies": False, "expired": False, "reason": None, "rule": None,
                "ttl_seconds": None, "expires_at": None}
    started = _parse_time(start)
    expires_at = (started + timedelta(seconds=ttl)).isoformat() if ttl and started else None
    return {"applies": True, "expired": bool(reason), "reason": reason, "rule": rule,
            "ttl_seconds": int(ttl or 0), "expires_at": expires_at}


def _binding(plan: Dict[str, Any]) -> Dict[str, Any]:
    if "binding" not in plan:
        return {"recorded": False, "bound": False}
    b = plan["binding"]
    if not isinstance(b, dict):
        return {"recorded": True, "bound": False}
    return {"recorded": True, "bound": True, "doc_title": b.get("doc_title"),
            "revit_version": b.get("revit_version"), "active_view_id": b.get("active_view_id")}


def _approval_mode(gate: Any) -> Dict[str, Any]:
    try:
        state = gate.approval_state()
    except Exception:  # noqa: BLE001 - report what is known rather than fail the review
        return {"mode": getattr(gate, "baseline_approval_mode", "unknown"), "configured_mode": None,
                "auto_expires_at": None}
    return {"mode": state.get("mode"), "configured_mode": state.get("configured_mode"),
            "auto_expires_at": state.get("auto_expires_at")}


def _id_keys_shown(args: Dict[str, Any]) -> set:
    """The id keys whose whole value the Element column shows: the keys ``element_ids_of`` reads
    (first list key with a list, first single key with a non-blank scalar), and only when every
    item of that value is shown. Any other id-like key is an argument like the rest."""
    keys = set()
    for key in ID_LIST_KEYS:
        value = args.get(key)
        if isinstance(value, list):
            if all(_scalar(v) for v in value):
                keys.add(key)
            break
    for key in ID_KEYS:
        value = args.get(key)
        if _scalar(value) and str(value).strip() != "":
            keys.add(key)
            break
    return keys


def _action_entry(index: int, action: Any, labels: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    if not isinstance(action, dict):
        return {"index": index, "action_id": None, "tool": None, "state": None, "malformed": True,
                "raw": action, "changes": [], "arguments": None, "other_arguments": {}}
    args = action.get("arguments", {})
    entry: Dict[str, Any] = {"index": index, "action_id": action.get("action_id"), "tool": action.get("tool"),
                             "state": action.get("state"), "malformed": not isinstance(args, dict), "changes": [],
                             "other_arguments": {}}
    if not isinstance(args, dict):
        entry["raw"] = args
        entry["arguments"] = None
        return entry
    shown = {k: v for k, v in args.items() if k not in _ARG_SKIP}
    entry["arguments"] = shown
    in_element_column = _id_keys_shown(shown)
    diff = action.get("diff") if isinstance(action.get("diff"), dict) else {}
    before = diff.get("before") if isinstance(diff.get("before"), dict) else {}
    param = args.get("parameter_name") if _scalar(args.get("parameter_name")) else None
    ids = element_ids_of(args) or [None]
    if param is not None:
        new_value: Any = args.get("value")
        new_is_args = False
        # Every argument that decides what runs (a filter, a type, a mode) and is not in the
        # Element, Parameter or New column is shown on its own line.
        entry["other_arguments"] = {k: v for k, v in shown.items()
                                    if k not in in_element_column and k not in ("parameter_name", "value")}
    else:
        new_value = {k: v for k, v in shown.items() if k not in in_element_column}
        new_is_args = True
    for eid in ids:
        label = labels.get(str(eid), {}) if eid is not None else {}
        captured = False
        old: Any = None
        if eid is not None and param is not None:
            per = before.get(str(eid))
            if isinstance(per, dict) and param in per:
                captured, old = True, per[param]
        entry["changes"].append({
            "element_id": eid, "element_name": label.get("name"), "mark": label.get("mark"),
            "unique_id": label.get("unique_id"), "parameter": param,
            "old": old, "old_captured": captured, "new": new_value, "new_is_arguments": new_is_args,
        })
    return entry


def build_review(plan: Dict[str, Any], gate: Any, shown_hash: str, expired: Optional[str] = None,
                 problems: Iterable[str] = ()) -> Dict[str, Any]:
    """A JSON-serialisable review of ``plan``. ``shown_hash`` is the hash the approval binds to."""
    problems = list(problems)
    actions_raw = plan.get("actions", [])
    actions_raw = actions_raw if isinstance(actions_raw, list) else []
    labels = _snapshot_labels(getattr(gate, "workspace_dir", None), plan.get("snapshot_id"))
    actions = [_action_entry(i, a, labels) for i, a in enumerate(actions_raw, 1)]
    changes = [c for a in actions for c in a["changes"]]
    elements = {str(c["element_id"]) for c in changes if c["element_id"] is not None}
    params = {str(c["parameter"]) for c in changes if c["parameter"] is not None}
    aids = review_aids(plan, getattr(gate, "workspace_dir", None))
    radius = aids.get("blast_radius")

    review_block = None
    if plan.get("review") is not None:
        try:
            review_block = normalize_review(plan.get("review"))
        except ValueError:
            review_block = None

    warnings: List[Dict[str, str]] = []
    if expired:
        warnings.append({"source": "expiry", "text": expired})
    for p in problems:
        warnings.append({"source": "malformed", "text": f"Plan is malformed: {p}. It cannot be approved."})
    if isinstance(review_block, dict):
        for w in review_block.get("warnings", []):
            warnings.append({"source": "review", "text": str(w)})
        if review_block.get("conflicts"):
            warnings.append({"source": "review", "text": f"{len(review_block['conflicts'])} conflict(s): the model "
                             "changed since the original plan ran (details below)."})
    if "warnings" in plan:
        legacy = plan["warnings"]
        for w in legacy if isinstance(legacy, list) else [legacy]:
            warnings.append({"source": "not_hashed", "text": str(w)})
    if radius:
        if radius.get("unidentified_actions"):
            warnings.append({"source": "preview", "text": f"{radius['unidentified_actions']} action(s) name no element, "
                             "so the element count is a lower bound."})
        if radius.get("risk") == "high":
            warnings.append({"source": "preview", "text": "Risk is high: many elements or actions."})
    missing = sum(1 for c in changes if c["parameter"] is not None and not c["old_captured"])
    if missing:
        warnings.append({"source": "preview", "text": f"Old value not captured for {missing} change(s)."})
    stuck = running_actions(plan)
    if stuck:
        warnings.append({"source": "state", "text": f"{len(stuck)} action(s) stuck in 'running' (details below)."})

    try:
        not_hashed = list(proof_mod.unhashed_metadata_keys(plan))
    except Exception:  # noqa: BLE001
        not_hashed = []
    reasons = list(problems)
    if plan.get("state") != "pending":
        reasons.append(f"state is '{plan.get('state')}'")
    if expired:
        reasons.append("expired")
    digest = shown_hash.split(":", 1)[-1]
    return {
        "schema": REVIEW_SCHEMA,
        "schema_version": REVIEW_SCHEMA_VERSION,
        "plan_id": plan.get("plan_id"),
        "state": plan.get("state"),
        "created_at": plan.get("created_at"),
        "plan_hash": shown_hash,
        "plan_hash_short": ("sha256:" if shown_hash.startswith("sha256:") else "") + digest[:12],
        "approval_mode": _approval_mode(gate),
        "expiry": _expiry(plan, gate, expired),
        "binding": _binding(plan),
        "counts": {
            "actions": len(actions),
            "elements": len(elements),
            "parameters": len(params),
            "changes": len(changes),
            "old_values_captured": sum(1 for c in changes if c["old_captured"]),
        },
        "tools": sorted({str(a["tool"]) for a in actions if a["tool"] is not None}),
        "risk": radius,
        "warnings": warnings,
        "approvable": not reasons,
        "not_approvable_reasons": reasons,
        "actions": actions,
        "review": review_block,
        "not_hashed_keys": not_hashed,
        "snapshot_id": plan.get("snapshot_id"),
        "reverts_plan_id": plan.get("reverts_plan_id"),
    }


def review_json(review: Dict[str, Any]) -> str:
    """The review as JSON. ``ensure_ascii`` escapes every control character, so it is safe to print."""
    return json.dumps(review, indent=2, ensure_ascii=True, default=str)


# ---- rendering (text) ----------------------------------------------------------------------


def color_supported(stream: Any, env: Optional[Dict[str, str]] = None, os_name: Optional[str] = None) -> bool:
    """True when ANSI color may be written to ``stream``: NO_COLOR is unset or empty, the stream
    is a terminal, TERM is not 'dumb', and on Windows the terminal is one known to handle ANSI."""
    env = dict(os.environ) if env is None else env
    if env.get("NO_COLOR"):
        return False
    try:
        if not stream.isatty():
            return False
    except Exception:  # noqa: BLE001
        return False
    term = env.get("TERM", "")
    if term == "dumb":
        return False
    if (os_name or os.name) == "nt":
        return bool(env.get("WT_SESSION") or env.get("ANSICON") or env.get("ConEmuANSI") == "ON"
                    or env.get("TERM_PROGRAM") == "vscode" or term)
    return bool(term)


class _Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def label(self, text: str) -> str:
        return self._wrap("1", text)

    def warn(self, text: str) -> str:
        return self._wrap("33", text)

    def bad(self, text: str) -> str:
        return self._wrap("31;1", text)


def _char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(_char_width(ch) for ch in text)


def _split_width(word: str, width: int) -> Tuple[str, str]:
    used = 0
    for i, ch in enumerate(word):
        w = _char_width(ch)
        if used + w > width and i > 0:
            return word[:i], word[i:]
        used += w
    return word, ""


def wrap_cell(text: str, width: int) -> List[str]:
    """Wrap one cell to ``width`` display columns (wide characters count as two)."""
    width = max(1, width)
    lines: List[str] = []
    cur = ""
    for word in text.split():
        candidate = f"{cur} {word}" if cur else word
        if display_width(candidate) <= width:
            cur = candidate
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while display_width(word) > width:
            head, word = _split_width(word, width)
            lines.append(head)
        cur = word
    if cur or not lines:
        lines.append(cur)
    return lines


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def format_value(value: Any, show_all: bool = False) -> str:
    """One value as printable text: strings as given, numbers, booleans, lists and objects as
    compact JSON. Cut to VALUE_MAX_CHARS unless ``show_all``."""
    if value is None or value == "":
        text = EMPTY
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(", ", ": "))
    text = safe_text(text)
    if not show_all and len(text) > VALUE_MAX_CHARS:
        text = text[:VALUE_MAX_CHARS] + f" ... (+{len(text) - VALUE_MAX_CHARS} chars, use --all)"
    return text


def _element_label(change: Dict[str, Any]) -> str:
    if change["element_id"] is None:
        return NO_ELEMENT
    parts = [safe_text(change["element_id"])]
    if change.get("element_name"):
        parts.append(safe_text(change["element_name"]))
    if change.get("mark"):
        parts.append(f"Mark {safe_text(change['mark'])}")
    return parts[0] + (f" ({', '.join(parts[1:])})" if len(parts) > 1 else "")


def _table(rows: List[Tuple[str, str, str, str]], width: int, indent: str = "    ") -> List[str]:
    """Element | Parameter | Old -> New, each cell wrapped to its column."""
    header = ("Element", "Parameter", "Old", "New")
    gap, arrow = "  ", " -> "
    avail = width - len(indent) - 2 * len(gap) - len(arrow)
    ew = min(max(display_width(r[0]) for r in rows + [header]), max(12, avail // 3))
    pw = min(max(display_width(r[1]) for r in rows + [header]), max(10, avail // 5))
    rest = max(20, avail - ew - pw)
    ow = max(10, min(max(display_width(r[2]) for r in rows + [header]), rest // 2))
    nw = max(10, rest - ow)
    out = [indent + _pad(header[0], ew) + gap + _pad(header[1], pw) + gap + _pad(header[2], ow)
           + "    " + header[3],
           indent + "-" * ew + gap + "-" * pw + gap + "-" * ow + "    " + "-" * min(nw, 40)]
    for element, param, old, new in rows:
        cells = [wrap_cell(element, ew), wrap_cell(param, pw), wrap_cell(old, ow), wrap_cell(new, nw)]
        for n in range(max(len(c) for c in cells)):
            line = (indent + _pad(cells[0][n] if n < len(cells[0]) else "", ew) + gap
                    + _pad(cells[1][n] if n < len(cells[1]) else "", pw) + gap
                    + _pad(cells[2][n] if n < len(cells[2]) else "", ow)
                    + (arrow if n == 0 else " " * len(arrow))
                    + (cells[3][n] if n < len(cells[3]) else ""))
            out.append(line.rstrip())
    return out


def _wrapped(prefix: str, text: str, width: int, indent: str = "") -> List[str]:
    body = wrap_cell(text, max(20, width - len(indent) - display_width(prefix)))
    pad = " " * display_width(prefix)
    return [indent + (prefix if i == 0 else pad) + line for i, line in enumerate(body)]


def _span(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def terminal_width(default: int = DEFAULT_WIDTH) -> int:
    try:
        cols = os.get_terminal_size().columns
    except OSError:
        cols = default
    return max(MIN_WIDTH, min(MAX_WIDTH, cols or default))


def is_cut(review: Dict[str, Any], max_rows: int = DEFAULT_MAX_ROWS) -> bool:
    """True when ``render_review`` without ``show_all`` leaves rows out or cuts a value."""
    if sum(max(1, len(a["changes"])) for a in review["actions"]) > max_rows:
        return True
    values = [a.get("raw") for a in review["actions"] if a["malformed"]]
    values += [a["other_arguments"] for a in review["actions"] if a.get("other_arguments")]
    values += [v for a in review["actions"] for c in a["changes"] for v in (c["old"], c["new"])]
    return any(len(format_value(v, show_all=True)) > VALUE_MAX_CHARS for v in values)


def render_review(review: Dict[str, Any], show_all: bool = False, width: Optional[int] = None,
                  color: bool = False, max_rows: int = DEFAULT_MAX_ROWS) -> str:
    """The review as plain text. Without ``show_all`` at most ``max_rows`` change rows are
    printed, followed by one "+N more ..., use --all" line."""
    width = max(MIN_WIDTH, min(MAX_WIDTH, width or DEFAULT_WIDTH))
    st = _Style(color)
    counts = review["counts"]
    lines = [st.label(f"Plan {safe_text(review['plan_id'])}") + f"  [{safe_text(review['state'])}]",
             f"Created: {safe_text(review.get('created_at') or 'unknown')}",
             f"Plan hash: {safe_text(review['plan_hash_short'])} (short; full hash at the end)"]

    mode = review["approval_mode"]
    mode_text = safe_text(mode.get("mode"))
    if mode.get("configured_mode") and mode.get("configured_mode") != mode.get("mode"):
        mode_text += f" (configured: {safe_text(mode['configured_mode'])})"
    if mode.get("auto_expires_at"):
        mode_text += f", temporary auto window until {safe_text(mode['auto_expires_at'])}"
    lines.append(f"Approval mode: {mode_text}")

    exp = review["expiry"]
    if exp["expired"]:
        lines.extend(st.bad(ln) for ln in _wrapped("EXPIRED: ", safe_text(exp["reason"]), width))
    elif not exp["applies"]:
        lines.append(f"Expiry: does not apply to a plan in state '{safe_text(review['state'])}'")
    elif not exp["ttl_seconds"]:
        lines.append(f"Expiry: no limit ({exp['rule']} is 0)")
    elif exp["expires_at"]:
        lines.append(f"Expiry: {safe_text(exp['expires_at'])} ({exp['rule']} {_span(exp['ttl_seconds'])})")
    else:
        lines.append(f"Expiry: unknown ({exp['rule']} {_span(exp['ttl_seconds'])}; start time unreadable)")

    b = review["binding"]
    if not b["recorded"]:
        lines.extend(_wrapped("Document: ", "no binding recorded (older plan format); it is not checked against "
                              "the active document.", width))
    elif not b["bound"]:
        lines.extend(_wrapped("Document: ", "NOT BOUND to a Revit document (no live document could be read when it "
                              "was drafted); it will not be refused for being run in another model.", width))
    else:
        view = f", view {safe_text(b['active_view_id'])}" if b.get("active_view_id") is not None else ""
        lines.extend(_wrapped("Document: ", f"{safe_text(b.get('doc_title'))} (Revit {safe_text(b.get('revit_version'))}"
                              f"{view}); refused if another document is active when it runs.", width))

    lines.append(f"Actions: {counts['actions']}   Elements: {counts['elements']}   Parameters: {counts['parameters']}")
    lines.append(f"Changes: {counts['changes']} (old value captured for {counts['old_values_captured']})")
    if review["tools"]:
        lines.extend(_wrapped("Tools: ", ", ".join(safe_text(t) for t in review["tools"]), width))
    risk = review.get("risk")
    if risk:
        scope = (f"categories {', '.join(map(safe_text, risk['categories']))}; levels "
                 f"{', '.join(map(safe_text, risk['levels']))}; worksets {', '.join(map(safe_text, risk['worksets']))}")
        lines.extend(_wrapped(f"Risk: {safe_text(risk['risk'])}  ", scope, width))

    if review["warnings"]:
        lines.append("")
        lines.append(st.warn(f"Warnings ({len(review['warnings'])}):"))
        for w in review["warnings"]:
            tag = {"not_hashed": " [not covered by the approval]", "review": " [from the hashed review]"}.get(w["source"], "")
            lines.extend(st.warn(ln) for ln in _wrapped("  ! ", safe_text(w["text"]) + tag, width))

    shown = 0
    hidden_rows = 0
    hidden_actions = 0
    for action in review["actions"]:
        n_rows = max(1, len(action["changes"]))
        if not show_all and shown >= max_rows:
            hidden_rows += len(action["changes"]) if action["changes"] else 1
            hidden_actions += 1
            continue
        lines.append("")
        head = f"Action {action['index']}/{counts['actions']}: {safe_text(action['tool'])}"
        if action.get("state"):
            head += f"  [{safe_text(action['state'])}]"
        if action.get("action_id"):
            head += f"  {safe_text(action['action_id'])}"
        lines.extend(_wrapped("", head, width))
        if action["malformed"]:
            what = "MALFORMED ACTION" if action["action_id"] is None and action["tool"] is None else \
                "MALFORMED ARGUMENTS (not an object)"
            lines.extend(st.bad(ln) for ln in _wrapped(f"    {what}: ", format_value(action.get("raw"), show_all), width))
            shown += 1
            continue
        budget = n_rows if show_all else max(0, max_rows - shown)
        rows: List[Tuple[str, str, str, str]] = []
        prev_old = prev_new = None
        for c in action["changes"][:budget]:
            old = format_value(c["old"], show_all) if c["old_captured"] else (NOT_CAPTURED if c["parameter"] else "-")
            new = format_value(c["new"], show_all) if not c["new_is_arguments"] or c["new"] else EMPTY
            # A long value repeated on the next row is printed once.
            old_cell = SAME_AS_ABOVE if old == prev_old and len(old) > SAME_MIN_CHARS else old
            new_cell = SAME_AS_ABOVE if new == prev_new and len(new) > SAME_MIN_CHARS else new
            prev_old, prev_new = old, new
            old, new = old_cell, new_cell
            rows.append((_element_label(c), safe_text(c["parameter"]) if c["parameter"] is not None else "-", old, new))
        lines.extend(_table(rows, width))
        if action.get("other_arguments"):
            lines.extend(_wrapped("    Other arguments: ", format_value(action["other_arguments"], show_all), width))
        shown += len(rows)
        left = len(action["changes"]) - len(rows)
        if left > 0:
            hidden_rows += left
            lines.append(f"    +{left} more row(s) in this action")
    if hidden_rows:
        lines.append("")
        more = f"+{hidden_rows} more row(s)"
        if hidden_actions:
            more += f", {hidden_actions} more action(s) not shown"
        lines.append(st.warn(more + ", use --all to show every row."))
    return "\n".join(lines)
