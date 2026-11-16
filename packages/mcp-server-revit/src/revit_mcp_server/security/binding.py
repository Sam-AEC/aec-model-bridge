"""Document binding: which Revit document a plan was drafted for (ADR 0017).

``binding_from_context`` turns a ``revit_get_context`` result into the small object stored inside the
hashed plan; ``mismatches`` compares a stored binding with the live one. Both are pure functions: the
live read itself is done by the caller, and nothing here is reachable from tool arguments.

A binding is None when the document cannot be identified (mock mode, no Revit, a document with
neither a guid nor a central path). Such a plan is not bound and is never refused for that reason.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

# The process id is not part of revit_get_context today, so it is not recorded.
BINDING_KEYS = ("doc_guid", "central_path_hash", "doc_title", "revit_version", "active_view_id")
_VIEW_ARGUMENT_KEYS = ("view_id", "view_ids")


def _path_hash(path: Any) -> Optional[str]:
    if not isinstance(path, str) or not path.strip():
        return None
    return "sha256:" + hashlib.sha256(path.strip().replace("\\", "/").lower().encode("utf-8")).hexdigest()


def _is_view_specific(actions: List[Dict[str, Any]]) -> bool:
    return any(
        isinstance(a.get("arguments"), dict) and any(k in a["arguments"] for k in _VIEW_ARGUMENT_KEYS)
        for a in actions if isinstance(a, dict)
    )


def live_binding(context: Any) -> Optional[Dict[str, Any]]:
    """Identity of the live document from a revit_get_context result, or None when unreadable."""
    if not isinstance(context, dict) or context.get("mock"):
        return None
    doc = context.get("document")
    if not isinstance(doc, dict):
        return None
    guid = doc.get("guid") if isinstance(doc.get("guid"), str) and doc.get("guid") else None
    central = _path_hash(doc.get("central_path")) if doc.get("is_workshared") else None
    if guid is None and central is None:
        return None
    revit = context.get("revit") if isinstance(context.get("revit"), dict) else {}
    view = doc.get("active_view") if isinstance(doc.get("active_view"), dict) else {}
    return {
        "doc_guid": guid,
        "central_path_hash": central,
        "doc_title": doc.get("title") if isinstance(doc.get("title"), str) else None,
        "revit_version": str(revit["version"]) if revit.get("version") is not None else None,
        "active_view_id": view.get("id") if isinstance(view.get("id"), int) else None,
    }


def binding_from_context(context: Any, actions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The binding to store at drafting. The active view is kept only for view-specific actions."""
    live = live_binding(context)
    if live is not None and not _is_view_specific(actions):
        live["active_view_id"] = None
    return live


def validate_binding(binding: Any) -> None:
    """Raise ValueError unless ``binding`` is None or an object with only the known keys."""
    if binding is None:
        return
    if not isinstance(binding, dict) or any(k not in BINDING_KEYS for k in binding):
        raise ValueError("Plan has a malformed document binding; it cannot be verified.")


def mismatches(bound: Dict[str, Any], live: Dict[str, Any]) -> List[str]:
    """Human-readable differences between the stored binding and the live document."""
    out = []
    for key in BINDING_KEYS:
        want = bound.get(key)
        if want is not None and live.get(key) != want:
            if key == "central_path_hash":
                out.append("central model path differs")
            elif key == "doc_guid":
                out.append("document id differs")
            elif key == "doc_title":
                out.append(f"document title: plan {want!r}, Revit {live.get(key)!r}")
            else:
                out.append(f"{key.replace('_', ' ')}: plan {want!r}, Revit {live.get(key)!r}")
    return out
