"""Rolled-back preview of a plan (#293).

When the add-in supports it, plan_actions asks it to run the plan's actions inside a TransactionGroup that
is always rolled back (revit.preview_plan_batch). The add-in reports the changed element ids, each action's
outcome and the Revit warnings. This module turns that reply into the small record stored on the plan as
``rollback_preview``, checks the record's shape, and renders it as text for the panel and the approval CLI.

The record is covered by the plan hash (security/proof.py), so it cannot be added, changed or removed after
approval. A preview is never an approval and never an execution: nothing here claims an action, records a
proof or changes plan state. If the add-in reports that the preview was NOT rolled back, the record says so
and the person is told to check the model; nothing is hidden.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

PREVIEW_VERSION = 1
STATUSES = ("ok", "failed", "unavailable")
MAX_ACTIONS = 50
MAX_WARNINGS = 100
MAX_IDS = 500
TEXT_LIMIT = 500
VALUE_LIMIT = 200
MAX_BYTES = 65536

_KEYS = ("version", "status", "rolled_back", "reason", "changed_element_ids", "actions", "warnings")
_ACTION_KEYS = ("index", "tool", "ok", "error", "element_id", "parameter", "before", "after")
_WARNING_KEYS = ("action_index", "severity", "message", "element_ids")
# Result fields that only repeat warnings or add-in bookkeeping. They are not an "after" value.
_NOISE = frozenset({"warnings", "revit_messages", "status", "success", "ok"})


def _text(value: Any, limit: int = TEXT_LIMIT) -> str:
    text = "" if value is None else (value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _ids(value: Any) -> List[int]:
    out: List[int] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                out.append(item)
            elif isinstance(item, str) and item.strip().lstrip("-").isdigit():
                out.append(int(item.strip()))
    return list(dict.fromkeys(out))


def unavailable(reason: str) -> Dict[str, Any]:
    """A record saying no preview was taken, and why. Never guesses a result."""
    return {"version": PREVIEW_VERSION, "status": "unavailable", "rolled_back": True, "reason": _text(reason),
            "changed_element_ids": [], "actions": [], "warnings": []}


def _after_of(result: Any) -> Any:
    """What the action left behind, from the add-in's per-action result: ``new_value`` when present,
    else the remaining result fields (capped), else None."""
    if not isinstance(result, dict):
        return None
    if "new_value" in result:
        return _text(result.get("new_value"), VALUE_LIMIT)
    rest = {k: v for k, v in result.items() if k not in _NOISE and k not in ("element_id", "parameter_name")}
    return _text(rest, VALUE_LIMIT) if rest else None


def _before_of(before_state: Any, element_id: Optional[int], parameter: Optional[str]) -> Any:
    if isinstance(before_state, dict) and element_id is not None and parameter is not None:
        row = before_state.get(str(element_id))
        if isinstance(row, dict) and parameter in row:
            return _text(row[parameter], VALUE_LIMIT)
    return None


def build(reply: Any, actions: List[Dict[str, Any]], before_states: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The stored record for an add-in reply. ``actions`` and ``before_states`` are the plan's own, in order.

    Anything the reply does not hold is left out, never filled in. A reply that is not an object, or whose
    ``results`` do not match the plan, gives an ``unavailable`` record."""
    if not isinstance(reply, dict) or not isinstance(reply.get("results"), list):
        return unavailable("The add-in returned a preview this server cannot read.")
    results = reply["results"]
    if len(results) != len(actions):
        return unavailable("The add-in returned a preview that does not match the plan.")
    if reply.get("committed") is True:
        # Cannot happen when the add-in behaves. Say so loudly instead of showing a normal preview.
        record = unavailable("The add-in reported that the preview was COMMITTED, not rolled back. "
                             "Check the model and undo the change before approving anything.")
        record["rolled_back"] = False
        return record
    out_actions: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    failed = False
    for i, (action, entry) in enumerate(zip(actions, results)):
        entry = entry if isinstance(entry, dict) else {}
        args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        eid = args.get("element_id")
        eid = eid if isinstance(eid, int) and not isinstance(eid, bool) else None
        parameter = args.get("parameter_name") if isinstance(args.get("parameter_name"), str) else None
        ok = entry.get("ok") is True
        failed = failed or not ok
        result = entry.get("result")
        item: Dict[str, Any] = {"index": i, "tool": _text(action.get("tool"), 120), "ok": ok}
        if not ok:
            if entry.get("not_run"):
                item["error"] = _text(entry.get("error") or "Not run.")
            else:
                item["error"] = _text(entry.get("error") or "The action failed in the preview.")
        if eid is not None:
            item["element_id"] = eid
        if parameter is not None:
            item["parameter"] = _text(parameter, 120)
        before = _before_of(before_states[i] if i < len(before_states) else None, eid, parameter)
        if before is not None:
            item["before"] = before
        if ok:
            after = _after_of(result)
            if after is not None:
                item["after"] = after
        out_actions.append(item)
        for w in (result.get("warnings") if isinstance(result, dict) and isinstance(result.get("warnings"), list) else []):
            if len(warnings) >= MAX_WARNINGS:
                break
            if isinstance(w, dict):
                warnings.append({"action_index": i, "severity": _text(w.get("Severity") or w.get("severity") or "Warning", 40),
                                 "message": _text(w.get("Message") or w.get("message")),
                                 "element_ids": _ids(w.get("ElementIds") or w.get("element_ids"))[:20]})
            elif isinstance(w, str):
                warnings.append({"action_index": i, "severity": "Warning", "message": _text(w), "element_ids": []})
    changed = reply.get("changed_element_ids")
    ids: List[int] = []
    if isinstance(changed, dict):
        for key in ("added", "modified", "deleted"):
            ids.extend(_ids(changed.get(key)))
    else:
        ids = _ids(changed)
    record: Dict[str, Any] = {
        "version": PREVIEW_VERSION,
        "status": "failed" if failed else "ok",
        "rolled_back": reply.get("rolled_back") is not False,
        "changed_element_ids": list(dict.fromkeys(ids))[:MAX_IDS],
        "actions": out_actions,
        "warnings": warnings,
    }
    if failed:
        record["reason"] = _text(reply.get("failure") or "At least one action failed in the preview.")
    return validate(record)


def validate(record: Any) -> Dict[str, Any]:
    """Strict shape check for a stored record. Raises ValueError; returns the record when it is valid."""
    if not isinstance(record, dict):
        raise ValueError("rollback_preview must be an object.")
    extra = sorted(str(k)[:40] for k in record if k not in _KEYS)
    if extra:
        raise ValueError("rollback_preview has unknown key(s): " + ", ".join(extra) + ".")
    if record.get("version") != PREVIEW_VERSION or type(record.get("version")) is not int:
        raise ValueError("rollback_preview.version must be 1.")
    if record.get("status") not in STATUSES:
        raise ValueError("rollback_preview.status must be ok, failed or unavailable.")
    if not isinstance(record.get("rolled_back"), bool):
        raise ValueError("rollback_preview.rolled_back must be true or false.")
    if "reason" in record and not isinstance(record["reason"], str):
        raise ValueError("rollback_preview.reason must be text.")
    ids = record.get("changed_element_ids")
    if not isinstance(ids, list) or len(ids) > MAX_IDS or any(type(i) is not int for i in ids):
        raise ValueError("rollback_preview.changed_element_ids must be a list of at most 500 integers.")
    acts = record.get("actions")
    if not isinstance(acts, list) or len(acts) > MAX_ACTIONS:
        raise ValueError("rollback_preview.actions must be a list of at most 50 entries.")
    for a in acts:
        if not isinstance(a, dict) or any(k not in _ACTION_KEYS for k in a):
            raise ValueError("rollback_preview.actions entries have unknown keys.")
        if type(a.get("index")) is not int or not isinstance(a.get("ok"), bool) or not isinstance(a.get("tool"), str):
            raise ValueError("rollback_preview.actions entries need index, tool and ok.")
    warns = record.get("warnings")
    if not isinstance(warns, list) or len(warns) > MAX_WARNINGS:
        raise ValueError("rollback_preview.warnings must be a list of at most 100 entries.")
    for w in warns:
        if not isinstance(w, dict) or any(k not in _WARNING_KEYS for k in w) or not isinstance(w.get("message"), str):
            raise ValueError("rollback_preview.warnings entries are malformed.")
    if len(json.dumps(record, default=str).encode("utf-8")) > MAX_BYTES:
        raise ValueError("rollback_preview is larger than 64 KiB.")
    return record


def markdown(record: Any) -> List[str]:
    """Plain lines for the panel and the CLI. A record that cannot be read is reported, not skipped."""
    try:
        validate(record)
    except ValueError as exc:
        return [f"Rolled-back preview: stored record is not valid ({exc})."]
    lines: List[str] = []
    if not record["rolled_back"]:
        lines.append("PREVIEW WAS NOT ROLLED BACK. Check the model before approving anything.")
    if record["status"] == "unavailable":
        lines.append("Rolled-back preview: not available. " + (record.get("reason") or ""))
        return [" ".join(line.split()) for line in lines]
    n_ids = len(record["changed_element_ids"])
    head = ("Rolled-back preview (nothing was kept in the model): "
            f"{n_ids} element(s) would change, {len(record['warnings'])} warning(s).")
    if record["status"] == "failed":
        head += " A step failed in the preview: " + (record.get("reason") or "no reason given") + "."
    lines.append(head)
    if n_ids:
        shown = ", ".join(str(i) for i in record["changed_element_ids"][:20])
        lines.append("Changed element ids: " + shown + (f" and {n_ids - 20} more" if n_ids > 20 else "") + ".")
    for a in record["actions"]:
        bits = [f"{a['index'] + 1}. {a['tool']}", "ok" if a["ok"] else "failed"]
        if "element_id" in a:
            bits.append(f"element {a['element_id']}")
        if "parameter" in a:
            bits.append(f"parameter {a['parameter']}")
        if "before" in a or "after" in a:
            bits.append(f"before {a.get('before', '(not captured)')} -> after {a.get('after', '(not reported)')}")
        if a.get("error"):
            bits.append(a["error"])
        lines.append("- " + "; ".join(bits))
    for w in record["warnings"]:
        lines.append(f"- Warning (action {w.get('action_index', 0) + 1}): {w['message']}")
    return lines
