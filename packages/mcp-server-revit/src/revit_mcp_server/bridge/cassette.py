"""Record bridge traffic to a JSONL cassette and replay it without Revit.

Recording (opt-in, bridge mode only): ``MCP_REVIT_RECORD=<name>`` writes every bridge
request/response pair to ``<workspace>/cassettes/<name>.jsonl``. The name must be a plain
name (letters, digits, ``_`` and ``-``); ``1``, ``true`` or ``on`` pick a timestamped name.
The path is built with ``safe_child``. Before a line is written, secrets, tokens and local
file paths are masked (``redact_data``) and user names, email addresses and person fields
are scrubbed (``redact_response`` at ``strict``).

Replay: ``MCP_REVIT_MODE=replay`` with ``MCP_REVIT_CASSETTE=<file>`` serves the recorded
responses. A request matches on its command plus its normalised parameters (redacted the
same way, volatile keys such as ``request_id`` and ``wait_ms`` removed, keys sorted). Equal
requests are served in recorded order; once they run out the last one repeats. A request
with no recorded match fails with a plain error. Replay never talks to Revit.

A cassette from a real model may contain model data (names, parameters, element ids).
Review it before you share it.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..errors import BridgeError, CommandFailed
from ..security.audit import redact_data
from ..security.response_redaction import redact_response
from ..security.safe_paths import safe_child

log = logging.getLogger(__name__)

RECORD_ENV = "MCP_REVIT_RECORD"
CASSETTE_ENV = "MCP_REVIT_CASSETTE"
CASSETTE_VERSION = 1
CASSETTE_SUBDIR = "cassettes"
CASSETTE_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ON_VALUES = {"1", "true", "on", "yes"}
# Parameters that change on every call and say nothing about what was asked.
_VOLATILE_KEYS = frozenset({"request_id", "wait_ms"})
GET_RESULT_COMMAND = "__get_result__"

# The MCP tool call a bridge request belongs to, set by the Revit provider. Recorded so a
# cassette can also be replayed at tool level (see revit_mcp_server.testing.cassette).
_TOOL_CALL: contextvars.ContextVar = contextvars.ContextVar("cassette_tool_call", default=None)


@contextlib.contextmanager
def tool_call(name: str, arguments: dict[str, Any]) -> Iterator[None]:
    token = _TOOL_CALL.set((name, dict(arguments)))
    try:
        yield
    finally:
        _TOOL_CALL.reset(token)


def scrub(value: Any) -> Any:
    """Mask secrets, tokens, local paths, user names and person fields."""
    return redact_response(redact_data(value), "strict")


def normalise_params(command: str, params: Any) -> Any:
    """The form two requests are compared in: scrubbed, volatile keys dropped."""
    value = scrub(params if params is not None else {})
    if isinstance(value, dict) and command != GET_RESULT_COMMAND:
        value = {k: v for k, v in value.items() if k not in _VOLATILE_KEYS}
    return value


def request_key(command: str, params: Any) -> str:
    return json.dumps(
        {"command": command, "params": normalise_params(command, params)},
        sort_keys=True, separators=(",", ":"), default=str,
    )


class CassetteError(BridgeError):
    """A cassette cannot be opened, read or matched."""


# --- recording ------------------------------------------------------------------------------

def _refuse_name(_reason: str) -> Exception:
    return CassetteError(
        f"{RECORD_ENV} must be a plain cassette name (letters, digits, '_' or '-', at most 64), "
        "or 1/true/on for a timestamped name. Paths are not accepted: the cassette is always "
        f"written to the '{CASSETTE_SUBDIR}' folder in the workspace."
    )


def cassette_path(workspace: Any, value: str) -> Path:
    """``<workspace>/cassettes/<name>.jsonl`` for a recording name; CassetteError otherwise."""
    name = value.strip()
    if name.lower() in _ON_VALUES:
        name = "session-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return safe_child(workspace, name, ".jsonl", CASSETTE_NAME_RE, _refuse_name, subdir=CASSETTE_SUBDIR)


class CassetteRecorder:
    """Appends scrubbed request/response pairs to one JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0

    def record(self, command: str, params: Any, *, ok: bool, response: Any = None,
               error: BaseException | None = None) -> None:
        entry: dict[str, Any] = {"v": CASSETTE_VERSION}
        call = _TOOL_CALL.get()
        if call is not None:
            name, arguments = call
            scrubbed = scrub(arguments)
            entry["tool"] = name
            entry["arguments"] = scrubbed
            if scrubbed != arguments:
                # The tool arguments changed under redaction, so they may not replay at tool level.
                entry["arguments_redacted"] = True
        entry["command"] = command
        entry["params"] = normalise_params(command, params)
        entry["ok"] = ok
        if ok:
            entry["response"] = scrub(response)
        else:
            entry["error"] = {
                "type": "CommandFailed" if isinstance(error, CommandFailed) else "BridgeError",
                "message": scrub(str(error)),
            }
            payload = getattr(error, "payload", None)
            if isinstance(payload, dict):
                entry["error"]["payload"] = scrub(payload)
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, **entry}
            line = json.dumps(entry, ensure_ascii=False, sort_keys=False, default=str)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")


class RecordingBridge:
    """Wraps a live bridge client and records each call. Anything else passes straight through.

    Batches are turned off while recording: the inner client would send a batch through its own
    ``call_tool``, past this recorder, so the writes would be missing from the cassette. With
    ``supports_batch`` and ``supports_plan_batch`` False the provider sends one request per
    command, each recorded, and the cassette replays the same way (replay never batches)."""

    def __init__(self, inner: Any, recorder: CassetteRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _run(self, command: str, params: Any, call: Any) -> Any:
        try:
            result = call()
        except BridgeError as exc:
            self._safe_record(command, params, ok=False, error=exc)
            raise
        self._safe_record(command, params, ok=True, response=result)
        return result

    def _safe_record(self, *args: Any, **kwargs: Any) -> None:
        try:
            self._recorder.record(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a full disk must not fail the Revit call
            log.error("Could not write to cassette %s: %s", self._recorder.path.name, type(exc).__name__)

    def send_tool(self, tool_name: str, payload: dict) -> dict:
        return self._run(tool_name, payload, lambda: self._inner.send_tool(tool_name, payload))

    def call_tool(self, tool: str, payload: dict, wait_s: float | None = None) -> dict:
        return self._run(tool, payload, lambda: self._inner.call_tool(tool, payload, wait_s=wait_s))

    def get_result(self, request_id: str, wait_s: float | None = None) -> dict:
        return self._run(GET_RESULT_COMMAND, {"request_id": request_id},
                         lambda: self._inner.get_result(request_id, wait_s=wait_s))

    def supports_batch(self) -> bool:
        return False

    def supports_plan_batch(self) -> bool:
        return False

    def supports_plan_preview(self) -> bool:
        return False

    def call_batch(self, *args: Any, **kwargs: Any) -> Any:
        raise CassetteError("Read batches are not sent while recording; send each command on its own.")

    def call_plan_batch(self, *args: Any, **kwargs: Any) -> Any:
        raise CassetteError("Plan batches are not sent while recording; run the plan one action at a time.")


def wrap_for_recording(bridge: Any, workspace: Any, value: str | None = None) -> Any:
    """Return bridge wrapped in a recorder when MCP_REVIT_RECORD is set; bridge itself otherwise.

    An invalid name raises CassetteError, so the session does not run unrecorded by surprise.
    """
    value = os.environ.get(RECORD_ENV) if value is None else value
    if value is None or not value.strip():
        return bridge
    path = cassette_path(workspace, value)
    log.warning(
        "Recording bridge traffic to %s. Secrets, paths and user names are masked, but the "
        "cassette can still hold model data; review it before sharing.", path.name,
    )
    return RecordingBridge(bridge, CassetteRecorder(path))


# --- replay ---------------------------------------------------------------------------------

def load_cassette(path: Any) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CassetteError(f"Cannot read cassette '{path.name}': {exc.strerror or exc}.") from exc
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CassetteError(f"Cassette '{path.name}' line {number} is not valid JSON.") from exc
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), str) or "ok" not in entry:
            raise CassetteError(
                f"Cassette '{path.name}' line {number} needs at least 'command' and 'ok'."
            )
        if entry.get("v", CASSETTE_VERSION) != CASSETTE_VERSION:
            raise CassetteError(
                f"Cassette '{path.name}' line {number} has version {entry.get('v')!r}; "
                f"this server reads version {CASSETTE_VERSION}."
            )
        entries.append(entry)
    return entries


class ReplayBridge:
    """Serves recorded responses. Never contacts Revit."""

    def __init__(self, entries: list[dict[str, Any]], name: str = "cassette") -> None:
        self.name = name
        self.entries = entries
        self._queues: dict[str, list[int]] = defaultdict(list)
        for index, entry in enumerate(entries):
            self._queues[request_key(entry["command"], entry.get("params"))].append(index)
        self._served: dict[str, int] = defaultdict(int)
        self.used: set[int] = set()
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path: Any) -> "ReplayBridge":
        return cls(load_cassette(path), Path(path).name)

    def _serve(self, command: str, params: Any) -> Any:
        key = request_key(command, params)
        with self._lock:
            queue = self._queues.get(key)
            if not queue:
                raise CassetteError(
                    f"Replay: cassette '{self.name}' has no recorded response for command '{command}' "
                    "with these parameters. Record the session again, or add the request to the cassette."
                )
            served = self._served[key]
            index = queue[min(served, len(queue) - 1)]
            self._served[key] = served + 1
            self.used.add(index)
        entry = self.entries[index]
        if entry["ok"]:
            response = entry.get("response")
            return json.loads(json.dumps(response)) if response is not None else {}
        error = entry.get("error") or {}
        message = str(error.get("message") or "Recorded bridge error")
        if error.get("type") == "CommandFailed":
            payload = error.get("payload")
            raise CommandFailed(message, payload=payload if isinstance(payload, dict) else None)
        raise BridgeError(message)

    def unused(self) -> list[dict[str, Any]]:
        return [entry for index, entry in enumerate(self.entries) if index not in self.used]

    def send_tool(self, tool_name: str, payload: dict) -> dict:
        return self._serve(tool_name, payload)

    def call_tool(self, tool: str, payload: dict, wait_s: float | None = None) -> dict:
        return self._serve(tool, payload)

    def get_result(self, request_id: str, wait_s: float | None = None) -> dict:
        return self._serve(GET_RESULT_COMMAND, {"request_id": request_id})

    def list_commands(self) -> list[dict[str, Any]]:
        raise CassetteError("Replay mode cannot list the add-in's commands; it only serves recorded requests.")


class UnconfiguredReplayBridge:
    """Stands in when replay mode has no usable cassette; every call fails with the reason."""

    def __init__(self, message: str) -> None:
        self.message = message

    def send_tool(self, tool_name: str, payload: dict) -> dict:
        raise CassetteError(self.message)

    def call_tool(self, tool: str, payload: dict, wait_s: float | None = None) -> dict:
        raise CassetteError(self.message)

    def get_result(self, request_id: str, wait_s: float | None = None) -> dict:
        raise CassetteError(self.message)

    def list_commands(self) -> list[dict[str, Any]]:
        raise CassetteError(self.message)


def replay_bridge_from_env(value: str | None = None) -> Any:
    value = os.environ.get(CASSETTE_ENV) if value is None else value
    if value is None or not value.strip():
        return UnconfiguredReplayBridge(
            f"MCP_REVIT_MODE=replay needs {CASSETTE_ENV} set to a cassette file (.jsonl)."
        )
    try:
        return ReplayBridge.from_file(value.strip())
    except CassetteError as exc:
        log.error("%s", exc)
        return UnconfiguredReplayBridge(str(exc))
