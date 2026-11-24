import argparse
import hashlib
import json
import math
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
    for secret in tuple(_KNOWN_SECRET_VALUES):
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


# --- narrow redaction for content a person approves --------------------------------------
# The panel list route must show the human exactly what they approve (paths, code, parameter
# names such as "Assembly Code", prose such as "Token: 3"). Only real credentials are masked
# there; anything masked makes the hub refuse Approve for that plan (see proof.panel_plans_redacted).
# Everything else (logs, audit, diagnostics, MCP and chat results, proofs) keeps redact_data.
_APPROVAL_SECRET_KEYS = {
    "apikey", "secret", "password", "passwd", "authorization", "accesstoken", "refreshtoken",
    "idtoken", "clientsecret", "privatekey", "rhinocomputekey", "sessiontoken", "codeverifier",
}
_APPROVAL_TEXT_RE = re.compile(
    r"(?i)(?<![a-z0-9])(password|passwd|api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|rhinocomputekey)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_KEY_LIKE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,})"
)
_LONG_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{32,}(?![A-Za-z0-9+/_=-])")


def _looks_high_entropy(token: str) -> bool:
    if not (any(c.isdigit() for c in token) and any(c.isupper() for c in token) and any(c.islower() for c in token)):
        return False
    counts = {c: token.count(c) for c in set(token)}
    entropy = -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())
    return entropy >= 4.0


def _redact_approval_text(value: str) -> str:
    value = redact_known_secrets(value)
    value = _APPROVAL_TEXT_RE.sub(lambda m: f"{m.group(1)}=<redacted>", value)
    value = _BEARER_RE.sub("Bearer <redacted>", value)
    value = _KEY_LIKE_RE.sub("<redacted>", value)
    return _LONG_TOKEN_RE.sub(lambda m: "<redacted>" if _looks_high_entropy(m.group(0)) else m.group(0), value)


def redact_for_approval(value: Any, key: str | None = None) -> Any:
    """Mask only real credentials: the panel token, bearer/authorization values, values under
    secret-bearing keys (exact names such as api_key, password, access_token), key-shaped
    strings and long high-entropy tokens. Paths, parameter names, ``code`` fields and ordinary
    prose are returned unchanged."""
    if key and isinstance(value, str):
        if re.sub(r"[^a-z0-9]", "", key.strip().lower()) in _APPROVAL_SECRET_KEYS:
            return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): redact_for_approval(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_approval(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_approval(item) for item in value)
    if isinstance(value, str):
        return _redact_approval_text(value)
    return value


GENESIS_HASH = "0" * 64


def _entry_hash(entry: Mapping[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _last_hash(path: Path) -> str:
    """Return the hash of the last chained line, or the genesis hash."""
    if not path.exists():
        return GENESIS_HASH
    last = ""
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        block = 4096
        data = b""
        pos = size
        while pos > 0 and data.count(b"\n") < 2:
            step = min(block, pos)
            pos -= step
            fh.seek(pos)
            data = fh.read(step) + data
        for raw in reversed(data.splitlines()):
            if raw.strip():
                last = raw.decode("utf-8", errors="replace")
                break
    try:
        value = json.loads(last).get("hash")
    except (ValueError, AttributeError):
        return GENESIS_HASH
    return value if isinstance(value, str) and len(value) == 64 else GENESIS_HASH


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
            "prev_hash": _last_hash(self.path),
        }
        entry["hash"] = _entry_hash(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def verify_audit_log(path: Path) -> dict:
    """Check the hash chain of an audit log.

    Lines written before chaining existed (no ``hash`` field) are accepted only
    at the start of the file. Returns ``{"ok", "entries", "legacy_entries",
    "error", "line"}``.
    """
    result: dict = {"ok": True, "entries": 0, "legacy_entries": 0, "error": None, "line": None}

    def fail(line_no: int, message: str) -> dict:
        result.update(ok=False, error=message, line=line_no)
        return result

    path = Path(path)
    if not path.exists():
        return fail(0, "audit log not found")
    prev = GENESIS_HASH
    chained = False
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                return fail(line_no, "line is not valid JSON")
            if not isinstance(entry, dict):
                return fail(line_no, "line is not a JSON object")
            if "hash" not in entry:
                if chained:
                    return fail(line_no, "unchained line after chain start")
                result["legacy_entries"] += 1
                continue
            chained = True
            if entry.get("prev_hash") != prev:
                return fail(line_no, "chain broken: previous hash does not match (line removed, reordered or edited)")
            if entry["hash"] != _entry_hash(entry):
                return fail(line_no, "entry hash does not match its content (line edited)")
            prev = entry["hash"]
            result["entries"] += 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m revit_mcp_server.security.audit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="verify the hash chain of an audit log")
    v.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    result = verify_audit_log(args.path)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
