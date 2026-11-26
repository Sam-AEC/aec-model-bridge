from __future__ import annotations

import httpx
import os
import threading
import time
import uuid
from typing import Any

from ..errors import BridgeError, CommandFailed
from .contract_generated import validate_command

DEFAULT_SOFT_WAIT_SECONDS = 25.0
# Poll gaps after the add-in's own wait: 0.5 s, 1 s, 2 s, then 3 s until the soft wait ends.
_POLL_BACKOFF = (0.5, 1.0, 2.0, 3.0)
_MAX_POLL_FAILURES = 3
# revit.batch (#277): the add-in command name and its member cap (BridgeBatch.MaxCommands in C#).
BATCH_COMMAND = "revit.batch"
MAX_BATCH_COMMANDS = 25
_BATCH_EXTRA_WAITS = 3
# revit.execute_plan_batch (#294): one approved plan's writes in one Revit turn and one undo step.
# The cap and the add-in's time budget are PlanBatch.MaxActions and PlanBatch.TimeBudgetMs in C#.
PLAN_BATCH_COMMAND = "revit.execute_plan_batch"
MAX_PLAN_BATCH_ACTIONS = 50
_PLAN_BATCH_EXTRA_WAITS = 4
# revit.preview_plan_batch (#293): the same members run in a TransactionGroup that is always rolled back.
PLAN_PREVIEW_COMMAND = "revit.preview_plan_batch"


def _soft_wait_from_env() -> float:
    try:
        value = float(os.environ.get("AEC_BRIDGE_SOFT_WAIT_SECONDS", DEFAULT_SOFT_WAIT_SECONDS))
    except ValueError:
        return DEFAULT_SOFT_WAIT_SECONDS
    return value if value > 0 else DEFAULT_SOFT_WAIT_SECONDS


VALIDATE_ENV = "MCP_REVIT_VALIDATE_BRIDGE_PAYLOADS"
_VALIDATE_OFF = ("0", "false", "off", "no")


def _validation_from_env() -> bool:
    """On unless MCP_REVIT_VALIDATE_BRIDGE_PAYLOADS is 0, false, off or no. Any other value keeps it on."""
    return os.environ.get(VALIDATE_ENV, "").strip().lower() not in _VALIDATE_OFF


class BridgeClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3000",
        timeout: int = 30,
        token: str | None = None,
        soft_wait: float | None = None,
        validate_payloads: bool | None = None,
    ):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.token = token
        # How long one call waits for Revit before it hands back {"status": "running", "request_id": ...}.
        self.soft_wait = soft_wait if soft_wait and soft_wait > 0 else _soft_wait_from_env()
        # Check each payload against contracts/bridge-commands.json before sending. None: read the
        # MCP_REVIT_VALIDATE_BRIDGE_PAYLOADS setting on every call (default on).
        self.validate_payloads = validate_payloads
        self._sleep = time.sleep
        self._clock = time.monotonic
        self._tool_catalog: list[str] | None = None
        self._http: httpx.Client | None = None
        self._http_key: tuple[Any, ...] | None = None
        self._http_lock = threading.Lock()
        self._registry_session = None
        self._pipe = None  # PipeTransport when the opt-in pipe transport is in use (ADR 0021)

    def use_pipe(self, pipe_name: str, expected_pid: int | None, **kwargs: Any) -> None:
        """Send every request over the add-in's named pipe instead of HTTP. Windows only."""
        from .pipe_transport import PipeTransport

        self._pipe = PipeTransport(pipe_name, expected_pid, timeout=self.timeout, **kwargs)

    @property
    def transport(self) -> str:
        return "pipe" if self._pipe is not None else "http"

    def bind_registry_session(self, switch: Any) -> None:
        """Pin an auto-discovered client to the chosen session, never to another Revit."""
        self._registry_session = (
            switch.pid, switch.host_version, switch.started_at,
            switch.endpoint.rstrip('/'), switch.session_token,
            getattr(switch, "pipe_name", None),
        )

    def _check_registry_session(self) -> None:
        if self._registry_session is None:
            return  # Explicit URLs and legacy ports do not use registry discovery.
        from .discovery import discover_switch_list

        pid, year, started_at, endpoint, token, pipe_name = self._registry_session
        for switch in discover_switch_list(prune=False):
            if (switch.provider_id == "revit" and switch.pid == pid
                    and switch.host_version == year and switch.started_at == started_at
                    and switch.endpoint.rstrip('/') == endpoint and switch.session_token == token
                    and getattr(switch, "pipe_name", None) == pipe_name):
                return
        raise BridgeError(
            f"The selected Revit {year} session (process {pid}) changed or closed. "
            "Call revit_reconnect, or restart this MCP client, to select the current session. "
            "No request was sent to a replacement Revit. Check the model before repeating an earlier write."
        )

    def initialize(self) -> None:
        """Check bridge health and fetch tool catalog on startup."""
        try:
            health = self._get("/health")
            if health.get("status") != "healthy":
                raise BridgeError(f"Bridge unhealthy: {health}")

            tools_resp = self._get("/tools")
            self._tool_catalog = tools_resp.get("tools", [])

        except httpx.RequestError as e:
            raise BridgeError(
                f"Bridge unreachable at {self.base_url}. "
                f"Ensure Revit is running with the AEC Model Bridge add-in loaded. Error: {e}"
            ) from e

    def call_tool(self, tool: str, payload: dict[str, Any], wait_s: float | None = None) -> dict[str, Any]:
        """Execute a tool with retry logic.

        A call that outlives the soft wait is not an error: the add-in keeps running it and keeps the
        result, so this returns {"status": "running", "request_id": ...}; pass that id to get_result().
        wait_s overrides the soft wait for this one call (a quick probe should not hold for 25 s).
        A payload that does not fit the command contract is refused before anything is sent.
        """
        self._validate(tool, payload)
        self._check_registry_session()
        if self._tool_catalog and tool not in self._tool_catalog:
            raise BridgeError(
                f"Tool '{tool}' not available in bridge. "
                f"Available tools: {', '.join(self._tool_catalog)}"
            )

        request_id = str(uuid.uuid4())
        soft_wait = self.soft_wait if wait_s is None else max(0.5, float(wait_s))
        deadline = self._clock() + soft_wait
        # The add-in answers within wait_ms; keep that below the HTTP timeout so a slow command
        # comes back as "running" instead of as a client-side read timeout.
        wait_ms = int(max(0.5, min(soft_wait, self.timeout - 5)) * 1000)
        last_error = None

        for attempt in range(3):
            try:
                response = self._post(
                    "/execute",
                    {"tool": tool, "payload": payload, "request_id": request_id, "wait_ms": wait_ms}
                )
                if self._is_running(response):
                    return self._await_result(request_id, deadline, first=response)
                return self._unwrap(response)

            except httpx.RequestError as e:
                last_error = e
                if attempt < 2:
                    delay = 2 ** attempt  # 1s, 2s
                    self._sleep(delay)
                    continue
                raise BridgeError(
                    f"Bridge request failed after 3 attempts: {e}"
                ) from e

        raise BridgeError(f"Bridge request failed: {last_error}") from last_error

    def _validate(self, tool: str, payload: Any) -> None:
        enabled = _validation_from_env() if self.validate_payloads is None else self.validate_payloads
        if enabled:
            validate_command(tool, payload)
    def supports_batch(self) -> bool:
        """True when the add-in's command list names revit.batch (#277). Unknown catalog: False."""
        return bool(self._tool_catalog) and BATCH_COMMAND in self._tool_catalog

    def call_batch(self, commands: list[dict[str, Any]]) -> list[Any]:
        """Run up to MAX_BATCH_COMMANDS add-in reads in one Revit turn (revit.batch).

        ``commands`` is [{"tool": "revit.x", "payload": {...}}, ...]. Returns one entry per command,
        in order: the unwrapped result dict, or the CommandFailed for a command that failed. The
        add-in refuses the whole batch when a member is not read-only; that raises here. Callers must
        check that every member is a read-only tool before calling (RevitProvider.execute_read_batch).
        """
        if not commands:
            return []
        if len(commands) > MAX_BATCH_COMMANDS:
            raise ValueError(f"A batch takes at most {MAX_BATCH_COMMANDS} commands; got {len(commands)}.")
        members = []
        for index, command in enumerate(commands):
            tool = command.get("tool") if isinstance(command, dict) else None
            payload = command.get("payload", {}) if isinstance(command, dict) else None
            if not isinstance(tool, str) or not tool:
                raise ValueError(f"Batch command {index} needs a tool name.")
            if tool == BATCH_COMMAND:
                raise ValueError("Batches cannot be nested.")
            if payload is not None and not isinstance(payload, dict):
                raise ValueError(f"Batch command {index} ({tool}) has a payload that is not an object.")
            members.append({"tool": tool, "payload": payload or {}})

        result = self.call_tool(BATCH_COMMAND, {"commands": members})
        # Reads are bounded, but a slow batch can outlive one soft wait. Keep collecting it for a
        # few more waits instead of returning a "running" envelope the caller cannot split up.
        for _ in range(_BATCH_EXTRA_WAITS):
            if not self._is_running(result):
                break
            result = self.get_result(str(result.get("request_id")))
        if self._is_running(result):
            raise BridgeError(
                f"The read batch (request {result.get('request_id')}) is still running in Revit. "
                "Collect it with revit_get_result."
            )

        entries = result.get("results") if isinstance(result, dict) else None
        if not isinstance(entries, list) or len(entries) != len(members):
            raise BridgeError("The add-in returned a batch result that does not match the request.")
        out: list[Any] = []
        for member, entry in zip(members, entries):
            if not isinstance(entry, dict):
                out.append(CommandFailed(f"Bridge error: no result for {member['tool']}"))
            elif entry.get("ok") is True:
                try:
                    out.append(self._unwrap({"status": "ok", "result": entry.get("result")}))
                except BridgeError as exc:
                    out.append(exc)
            else:
                payload = entry.get("result")
                out.append(CommandFailed(
                    f"Bridge error: {entry.get('error') or 'Unknown error'}",
                    payload=payload if isinstance(payload, dict) else None,
                ))
        return out

    def supports_plan_batch(self) -> bool:
        """True when the add-in's command list names revit.execute_plan_batch (#294). Unknown catalog: False."""
        return bool(self._tool_catalog) and PLAN_BATCH_COMMAND in self._tool_catalog

    def call_plan_batch(self, plan_id: str, title: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Run one approved plan's write actions in one Revit turn, inside one undo group.

        ``actions`` is [{"action_id", "tool", "payload"}, ...]. Returns the add-in's result dict
        ({"committed", "group_name", "results": [...]}), or the {"status": "running", "request_id"}
        envelope when Revit has not answered after a few extra waits. The caller claims every action
        before calling and books each outcome from the results (ApprovalProvider).
        """
        if not actions:
            raise ValueError("A plan batch needs at least one action.")
        if len(actions) > MAX_PLAN_BATCH_ACTIONS:
            raise ValueError(f"A plan batch takes at most {MAX_PLAN_BATCH_ACTIONS} actions; got {len(actions)}.")
        result = self.call_tool(PLAN_BATCH_COMMAND, {"plan_id": plan_id, "title": title, "actions": actions})
        for _ in range(_PLAN_BATCH_EXTRA_WAITS):
            if not self._is_running(result):
                break
            result = self.get_result(str(result.get("request_id")))
        if isinstance(result, dict) and not self._is_running(result):
            for entry in result.get("results") or []:
                if isinstance(entry, dict) and isinstance(entry.get("result"), dict):
                    self._normalize_element_ids(entry["result"])
        return result

    def supports_plan_preview(self) -> bool:
        """True when the add-in's command list names revit.preview_plan_batch (#293). Unknown catalog: False."""
        return bool(self._tool_catalog) and PLAN_PREVIEW_COMMAND in self._tool_catalog

    def call_plan_preview(self, title: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Run a plan's write actions inside a group the add-in always rolls back, and return what they
        would have changed ({"rolled_back", "changed_element_ids", "results": [...]}).

        This is not an execution: nothing is claimed and nothing is kept in the model. ``actions`` is
        [{"action_id", "tool", "payload"}, ...], the same members call_plan_batch takes. Returns the
        {"status": "running", "request_id"} envelope when Revit has not answered after a few extra waits.
        """
        if not actions:
            raise ValueError("A plan preview needs at least one action.")
        if len(actions) > MAX_PLAN_BATCH_ACTIONS:
            raise ValueError(f"A plan preview takes at most {MAX_PLAN_BATCH_ACTIONS} actions; got {len(actions)}.")
        result = self.call_tool(PLAN_PREVIEW_COMMAND, {"plan_id": "preview", "title": title, "actions": actions})
        for _ in range(_PLAN_BATCH_EXTRA_WAITS):
            if not self._is_running(result):
                break
            result = self.get_result(str(result.get("request_id")))
        return result

    def get_result(self, request_id: str, wait_s: float | None = None) -> dict[str, Any]:
        """Collect the outcome of an earlier call by request id.

        Returns the command result when it is done and raises BridgeError when it failed or the id
        is unknown or expired. If it is still going after wait_s (default: the soft wait) it returns
        {"status": "running", "request_id": ...} so the caller can ask again.
        """
        wait = self.soft_wait if wait_s is None else max(0.0, float(wait_s))
        return self._await_result(request_id, self._clock() + wait)

    @staticmethod
    def _is_running(response: dict[str, Any]) -> bool:
        return (response.get("status") or response.get("Status")) in ("running", "queued")

    def _await_result(
        self, request_id: str, deadline: float, first: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        snapshot = first
        polls = 0
        failures = 0
        while True:
            if snapshot is None:
                try:
                    snapshot = self._get(f"/result/{request_id}")
                    failures = 0
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        raise BridgeError(
                            f"Request {request_id} is unknown to the add-in: its result expired "
                            "or Revit was restarted. Check the model before repeating a write."
                        ) from e
                    raise
                except httpx.RequestError as e:
                    failures += 1
                    if failures >= _MAX_POLL_FAILURES:
                        raise BridgeError(
                            f"Lost contact with the bridge while waiting for request {request_id}; "
                            f"it may still be running in Revit. Error: {e}"
                        ) from e

            if snapshot is not None:
                state = snapshot.get("state") or snapshot.get("status") or snapshot.get("Status")
                if state in ("done", "failed"):
                    if snapshot.get("response") is None:
                        raise BridgeError(f"Request {request_id} finished but its result is missing")
                    return self._unwrap(snapshot["response"])
                if state not in ("running", "queued"):
                    return self._unwrap(snapshot)

            remaining = deadline - self._clock()
            if remaining <= 0:
                return self._running_result(request_id, snapshot)
            self._sleep(min(_POLL_BACKOFF[min(polls, len(_POLL_BACKOFF) - 1)], remaining))
            polls += 1
            snapshot = None

    @staticmethod
    def _running_result(request_id: str, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = snapshot or {}
        state = snapshot.get("state") or "running"
        result: dict[str, Any] = {
            "status": "running",
            "state": state,
            "request_id": request_id,
            "message": (
                "Revit is still working on this request; nothing has been lost. "
                "Call revit_get_result with this request_id to collect the output. "
                "Do not repeat a write until it has finished."
            ),
        }
        for key in ("tool", "elapsed_ms"):
            if key in snapshot:
                result[key] = snapshot[key]
        return result

    def _unwrap(self, response: dict[str, Any]) -> dict[str, Any]:
        # Blueprint §3.2 envelope: { ok, request_id, data, warnings, artifacts, job }
        # Legacy Revit envelope: { Status/status, Tool, Result/result }
        if "ok" in response:
            if not response["ok"]:
                raise CommandFailed(
                    f"Bridge error: {response.get('message', 'Unknown error')}",
                    payload=response.get("data") if isinstance(response.get("data"), dict) else None,
                )
            result = response.get("data") or {}
        else:
            # Handle both lowercase (status) and Pascal case (Status) from C# server
            status = response.get("status") or response.get("Status", "ok")
            if status == "error":
                message = response.get("message") or response.get("Message", "Unknown error")
                stack = response.get("stack_trace") or response.get("StackTrace", "N/A")
                raise CommandFailed(
                    f"Bridge error: {message}\n"
                    f"Stack: {stack}",
                    payload=(response.get("result") or response.get("Result"))
                    if isinstance(response.get("result") or response.get("Result"), dict) else None,
                )
            # Handle both lowercase and Pascal case for Result
            result = response.get("result") or response.get("Result", {})

        # Normalize element ID keys from specific types to generic element_id
        if isinstance(result, dict):
            self._normalize_element_ids(result)

        return result

    def list_commands(self) -> list[dict[str, Any]]:
        """The add-in's command list: [{name, is_mutating, confirmation_required}]."""
        try:
            return list(self._get("/capabilities").get("tools", []))
        except httpx.RequestError as e:
            raise BridgeError(f"Bridge unreachable at {self.base_url}: {e}") from e

    def send_tool(self, tool_name: str, payload: dict) -> dict:
        """Legacy method for backward compatibility."""
        return self.call_tool(tool_name, payload)

    def _get_client(self) -> httpx.Client:
        """Return the shared httpx.Client, rebuilding it if the token or timeout changed."""
        key = (self.token, self.timeout)
        with self._http_lock:
            if self._http is None or self._http_key != key:
                old = self._http
                # The add-in gzips large responses when asked; httpx decodes them before .json().
                headers = {"Accept-Encoding": "gzip"}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"
                self._http = httpx.Client(headers=headers, timeout=self.timeout)
                self._http_key = key
                if old is not None:
                    old.close()
            return self._http

    def close(self) -> None:
        """Close the shared HTTP client. A later call transparently rebuilds it."""
        with self._http_lock:
            client, self._http, self._http_key = self._http, None, None
        if client is not None:
            client.close()

    def __enter__(self) -> "BridgeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _pipe_call(self, method: str, path: str, data: Any = None) -> dict[str, Any]:
        """One request over the pipe. A status of 400 or more raises httpx.HTTPStatusError, as HTTP does."""
        assert self._pipe is not None
        status, body = self._pipe.request(method, path, self.token, data)
        if status >= 400:
            request = httpx.Request(method, self._pipe.url(path))
            response = httpx.Response(status, json=body, request=request)
            raise httpx.HTTPStatusError(
                f"Bridge answered {status} for {method} {path} over the pipe", request=request, response=response
            )
        return body if isinstance(body, dict) else {}

    def _get(self, path: str) -> dict[str, Any]:
        self._check_registry_session()
        if self._pipe is not None:
            return self._pipe_call("GET", path)
        resp = self._get_client().get(f"{self.base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        self._check_registry_session()
        if self._pipe is not None:
            return self._pipe_call("POST", path, data)
        resp = self._get_client().post(f"{self.base_url}{path}", json=data)
        resp.raise_for_status()
        return resp.json()

    def _normalize_element_ids(self, result: dict[str, Any]) -> None:
        """Normalize specific element ID keys to generic element_id for consistency."""
        # Map specific element type IDs to generic element_id
        # Order matters: a door or window result also carries its host's wall_id, and element_id must be the
        # new element, so wall_id comes after the keys of the things that can be placed in a wall.
        id_keys = [
            'floor_id', 'roof_id', 'door_id', 'window_id',
            'column_id', 'beam_id', 'level_id', 'view_id', 'sheet_id',
            'room_id', 'grid_id', 'family_instance_id', 'instance_id', 'wall_id', 'element_id'
        ]

        for key in id_keys:
            if key in result and 'element_id' not in result:
                result['element_id'] = result[key]
                break
