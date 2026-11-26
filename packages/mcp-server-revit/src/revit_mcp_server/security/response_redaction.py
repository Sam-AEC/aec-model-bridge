"""Opt-in redaction of personal data in tool responses (issue #179).

Levels, set with ``MCP_REVIT_REDACT_RESPONSES``:
  off     (default) no extra redaction. Paths and secrets are still masked by redact_data.
  basic   email addresses and the local OS user name are masked.
  strict  basic, plus the values of person-name fields (user, author, owner, ...).
Any other value fails closed to ``strict``.
"""
from __future__ import annotations

import getpass
import logging
import os
import re
from collections.abc import Mapping
from typing import Any

log = logging.getLogger(__name__)

ENV_VAR = "MCP_REVIT_REDACT_RESPONSES"
_LEVELS = ("off", "basic", "strict")
_MASK = "<redacted-user>"
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PERSON_KEYS = {
    "user", "username", "author", "owner", "createdby", "lasteditedby", "editedby",
    "modifiedby", "checkedoutby", "worksetowner", "creator", "currentowner", "lastmodifiedby",
    "lastsavedby", "savedby",
}


def redaction_level() -> str:
    raw = os.environ.get(ENV_VAR)
    if raw is None or not raw.strip():
        return "off"
    level = raw.strip().lower()
    if level in _LEVELS:
        return level
    log.warning("Invalid %s=%r; using 'strict'.", ENV_VAR, raw)
    return "strict"


def _local_user_names() -> set[str]:
    names = {(os.environ.get("USER") or "").strip(), (os.environ.get("USERNAME") or "").strip()}
    try:
        names.add(getpass.getuser().strip())
    except Exception:  # noqa: BLE001 - no user database; env names still apply
        pass
    # Very short or generic names would mask ordinary words.
    return {n for n in names if len(n) >= 3 and n.lower() not in {"root", "user", "admin"}}


def _text(value: str, names: set[str]) -> str:
    value = _EMAIL_RE.sub(_MASK, value)
    for name in names:
        value = re.sub(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", _MASK, value, flags=re.I)
    return value


def _walk(value: Any, key: str | None, level: str, names: set[str]) -> Any:
    if level == "strict" and key and isinstance(value, (str, list, tuple)):
        if re.sub(r"[^a-z0-9]", "", key.lower()) in _PERSON_KEYS:
            return _MASK if isinstance(value, str) else [_MASK for _ in value]
    if isinstance(value, Mapping):
        return {str(k): _walk(v, str(k), level, names) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, None, level, names) for v in value]
    if isinstance(value, tuple):
        return tuple(_walk(v, None, level, names) for v in value)
    if isinstance(value, str):
        return _text(value, names)
    return value


def redact_response(value: Any, level: str | None = None) -> Any:
    """Return value with personal data masked for the configured level."""
    level = level or redaction_level()
    if level == "off":
        return value
    return _walk(value, None, level, _local_user_names())
