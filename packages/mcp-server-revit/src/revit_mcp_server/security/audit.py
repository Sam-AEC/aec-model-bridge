import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_SECRET_KEYS = {
    "authorization",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "token",
    "sessiontoken",
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
    r"(?i)(?<![a-z0-9])(api[_-]?key|token|session[_-]?token|secret|password|passwd|session|authorization|rhinocomputekey)\b\s*[:=]\s*([^\s,;]+)"
)
_WINDOWS_PATH_RE = re.compile(r"(?<!\w)(?:[A-Za-z]:[\\/](?:[^\s\"'<>|]+[\\/])*[^\s\"'<>|]+)")
_POSIX_PATH_RE = re.compile(r"(?:(?<=^)|(?<=[\s\"'(<\[]))(/(?:[^/\s]+/)*[^/\s]+)")
# UNC shares (\\server\share\model.rvt, the usual way central models are shared) and rooted
# backslash paths without a drive letter (\projects\model.rvt). Needs at least two segments and
# must not follow a word character, so "a\b" in ordinary text is left alone.
_UNC_OR_ROOTED_PATH_RE = re.compile(r"(?<![\w\\:])\\{1,2}(?:[^\s\"'<>|\\/]+\\)+[^\s\"'<>|\\/]+")


# Exact secret values known to this process (for example the panel hub token). Matching is by
# value, so a secret is masked wherever it ends up, not only next to a "token=" label.
_KNOWN_SECRET_VALUES: set[str] = set()


def register_secret_value(value: str) -> None:
    """Mask this exact value in everything redact_data / redact_known_secrets touch."""
    if value and len(value) >= 8:
        _KNOWN_SECRET_VALUES.add(value)


def redact_known_secrets(text: str) -> str:
    for secret in _KNOWN_SECRET_VALUES:
        if secret in text:
            text = text.replace(secret, "<redacted>")
    return text


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.strip().lower())
    return any(normalized == secret or normalized.endswith(secret) for secret in _SECRET_KEYS)


def _redact_text(value: str) -> str:
    value = redact_known_secrets(value)
    sanitized = _SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    sanitized = _WINDOWS_PATH_RE.sub("<redacted-path>", sanitized)
    sanitized = _UNC_OR_ROOTED_PATH_RE.sub("<redacted-path>", sanitized)
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

