import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..schemas import HealthOutput

_SECRET_KEYS = {
    "authorization",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "token",
    "password",
    "clientsecret",
    "secret",
    "codeverifier",
    "apikey",
    "authorizationcode",
    "code",
    "rhinocomputekey",
}

_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|session|authorization|rhinocomputekey)\b\s*[:=]\s*([^\s,;]+)"
)
_WINDOWS_PATH_RE = re.compile(r"(?<!\w)(?:[A-Za-z]:[\\/](?:[^\s\"'<>|]+[\\/])*[^\s\"'<>|]+)")
_POSIX_PATH_RE = re.compile(r"(?:(?<=^)|(?<=[\s\"'(<\[]))(/(?:[^/\s]+/)*[^/\s]+)")


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.strip().lower())
    return normalized in _SECRET_KEYS


def _redact_text(value: str) -> str:
    sanitized = _SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    sanitized = _WINDOWS_PATH_RE.sub("<redacted-path>", sanitized)
    sanitized = _POSIX_PATH_RE.sub("<redacted-path>", sanitized)
    return sanitized


def redact_data(value: Any, key: str | None = None) -> Any:
    if key and _is_sensitive_key(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(item_key): redact_data(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


class AuditRecorder:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, tool: str, request_id: str, payload: dict, response: dict) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "request_id": request_id,
            "payload": redact_data(payload),
            "response": redact_data(response),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

