"""Fuzz of the panel hub HTTP surface and the payload path check (issue #296).

The hub's request handler is driven in memory (no socket): random request bytes go in, the
raw HTTP response comes out. Properties:

* Any request that fails the Host, Origin, Content-Type or token check gets 401, 403, 415 or
  429, never reaches a tool, and never approves a plan.
* Any authenticated request to /execute, /approval-mode or /agent/chat gets a 2xx or a 4xx
  with a plain JSON error. Never a 5xx, never an unhandled exception.
* RevitProvider._assert_paths_in_workspace never admits a path outside the workspace or in
  plans/ or proofs/.

UNVERIFIED: nothing here runs Revit, WebView2 or the C# add-in.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple
from unittest import mock

import pytest
from hypothesis import event, given
from hypothesis import strategies as st

from revit_mcp_server import panel_server
from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.panel_server import MAX_BODY_BYTES, build_handler, parse_json_object
from revit_mcp_server.security.panel_token import TOKEN_HEADER
from revit_mcp_server.security.workspace import RESERVED_DIRS, WorkspaceMonitor

from test_property_safe_paths import FRAGMENTS

PORT = 8787
TOKEN = "t0k3n-" + "a" * 40
HOST = f"127.0.0.1:{PORT}"
AUTH_REFUSALS = {401, 403, 415, 429}
DOCUMENTED = {200, 400, 404, 409, 413}
SET = "revit_set_parameter_value"
PATH_KEYS = ["path", "csv_path", "output_path", "output_directory", "file_path", "template_path"]


# --- in-memory driver -----------------------------------------------------------------------


def _request(method: str, path: str, headers: Dict[str, str], body: bytes) -> bytes:
    lines = [f"{method} {path} HTTP/1.1"] + [f"{k}: {v}" for k, v in headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def _drive(handler_cls: type, raw: bytes) -> Tuple[int, Dict[str, Any]]:
    """Run one request through the handler. An exception the handler did not turn into a
    response propagates and fails the test."""
    handler = handler_cls.__new__(handler_cls)
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.server = SimpleNamespace(server_address=("127.0.0.1", PORT))
    handler.client_address = ("127.0.0.1", 50000)
    handler.request = None
    handler.close_connection = True
    handler.handle_one_request()
    head, _, payload = handler.wfile.getvalue().partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    assert b"Content-Type: application/json" in head, head
    body = json.loads(payload)
    assert isinstance(body, dict)
    return status, body


def _headers(body: bytes, **overrides: Optional[str]) -> Dict[str, str]:
    headers = {"Host": HOST, "Content-Type": "application/json", TOKEN_HEADER: TOKEN, "Content-Length": str(len(body))}
    for key, value in overrides.items():
        key = {"token": TOKEN_HEADER, "content_type": "Content-Type", "content_length": "Content-Length"}.get(key, key)
        if value is None:
            headers.pop(key, None)
        else:
            headers[key] = value
    return headers


@pytest.fixture(scope="module")
def hub(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """A hub handler with one pending plan in its workspace."""
    workspace = tmp_path_factory.mktemp("panel-fuzz") / "ws"
    handler_cls = build_handler(WorkspaceMonitor([workspace]), TOKEN)
    body = json.dumps({"tool": "plan_actions", "arguments": {"actions": [
        {"tool": SET, "arguments": {"element_id": 42, "parameter_name": "Mark", "value": "D-1"}}]}}).encode()
    status, plan = _drive(handler_cls, _request("POST", "/execute", _headers(body), body))
    assert status == 200 and plan["result"]["state"] == "pending"
    return SimpleNamespace(cls=handler_cls, plan=plan["result"], gate=handler_cls.approval_provider.gate)


def _plan_state(hub: SimpleNamespace) -> str:
    return hub.gate.load_plan(hub.plan["plan_id"])["state"]


# --- strategies -----------------------------------------------------------------------------

json_scalars = st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False, allow_infinity=False),
                         st.text(max_size=20))
json_values = st.recursive(
    json_scalars,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)
TOOLS = ["approve_plan", "reject_plan", "rollback_plan", "execute_plan", "plan_actions", "list_pending_plans",
         "get_proof_bundle", SET, "revit_save_document", "revit_list_views", "revit_get_context", "", "nope"]
tool_names = st.one_of(st.sampled_from(TOOLS), st.text(max_size=30), json_values)


def _dump(value: Any) -> bytes:
    return json.dumps(value).encode("utf-8")


shaped_bodies = st.fixed_dictionaries(
    {},
    optional={"tool": tool_names, "arguments": json_values, "instance": json_values,
              "message": json_values, "provider": json_values, "session_id": json_values,
              "mode": st.one_of(st.sampled_from(["auto", "dev", "ask_first", "required", "look_only"]), json_values),
              "confirm": json_values, "minutes": json_values},
).map(_dump)
hostile_bodies = st.one_of(
    st.binary(max_size=200),
    json_values.map(_dump),
    st.integers(min_value=1, max_value=3000).map(lambda n: b"[" * n + b"]" * n),
    st.integers(min_value=60, max_value=200).map(
        lambda n: b'{"tool": "list_pending_plans", "arguments": ' + b'{"a": ' * n + b"1" + b"}" * n + b"}"),
    st.integers(min_value=4301, max_value=6000).map(lambda n: b'{"tool": ' + b"1" * n + b"}"),
    st.sampled_from([b"NaN", b"Infinity", b"-Infinity", b"1e999"]).map(
        lambda c: b'{"tool": "list_pending_plans", "arguments": {"a": ' + c + b"}}"),
    st.sampled_from([b"\xff", b"\xc3\x28", b"\xed\xa0\x80", b"\x00"]).map(lambda b: b'{"tool": "x' + b + b'"}'),
    st.text(max_size=40).map(lambda t: json.dumps({"tool": t}, ensure_ascii=False).encode("utf-8", "surrogatepass")),
)
bodies = st.one_of(shaped_bodies, hostile_bodies)
header_text = st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xFF, exclude_characters="\x7f"),
                      max_size=40)
content_lengths = st.one_of(st.none(), st.sampled_from(["-1", "abc", "", " 12", str(MAX_BODY_BYTES + 1), "1e3"]),
                            st.integers(min_value=0, max_value=400).map(str))
paths = st.sampled_from(["/execute", "/approval-mode", "/agent/chat", "/execute?x=1", "/EXECUTE", "/nope"])


# --- the gate in front of every route -------------------------------------------------------


@st.composite
def unauthorized_requests(draw: st.DrawFn) -> Tuple[str, Dict[str, str]]:
    """One or more of: bad Host, an Origin, wrong Content-Type, missing or wrong token."""
    body = draw(st.one_of(bodies, st.just(b"approve")))
    overrides: Dict[str, Optional[str]] = {}
    defects = draw(st.lists(st.sampled_from(["host", "origin", "ctype", "token"]), min_size=1, max_size=4, unique=True))
    if "host" in defects:
        overrides["Host"] = draw(st.one_of(st.none(), header_text.map(lambda h: "x" + h),
                                           st.sampled_from(["127.0.0.1", "localhost", f"127.0.0.1:{PORT + 1}",
                                                            f"127.0.0.1.evil.example:{PORT}", f"[::1]:{PORT}"])))
    if "origin" in defects:
        overrides["Origin"] = draw(st.one_of(st.sampled_from(["null", "http://127.0.0.1", f"http://{HOST}"]), header_text))
    if "ctype" in defects:
        overrides["content_type"] = draw(st.one_of(st.none(), header_text.map(lambda c: "x" + c),
                                                   st.sampled_from(["text/plain", "application/json5",
                                                                    "multipart/form-data; boundary=a"])))
    if "token" in defects:
        overrides["token"] = draw(st.one_of(st.none(), st.just(""), st.just(TOKEN + "x"), st.just(TOKEN.upper()),
                                            st.just("a" * 10_000), header_text.map(lambda t: "x" + t)))
    return body, overrides


@given(request=unauthorized_requests(), path=paths)
def test_unauthorized_requests_never_reach_a_tool(hub: SimpleNamespace, request: Any, path: str) -> None:
    body, overrides = request
    if body == b"approve":  # the exact call that would approve the seeded plan
        body = _dump({"tool": "approve_plan", "arguments": {
            "plan_id": hub.plan["plan_id"], "expected_hash": hub.plan["plan_hash"]}})
    with mock.patch.object(panel_server, "_run_tool_sync") as run, \
            mock.patch.object(panel_server.PanelRequestHandler, "_dispatch_chat") as chat:
        status, payload = _drive(hub.cls, _request("POST", path, _headers(body, **overrides), body))
    event(f"status {status}")
    assert status in AUTH_REFUSALS, (status, payload)
    assert payload["ok"] is False and isinstance(payload["error"], str) and payload["error"]
    assert not run.called and not chat.called
    assert _plan_state(hub) == "pending"


# --- authenticated bodies -------------------------------------------------------------------


@given(body=bodies, path=paths, content_length=content_lengths)
def test_authenticated_bodies_get_only_documented_answers(
    hub: SimpleNamespace, body: bytes, path: str, content_length: Optional[str]
) -> None:
    overrides = {} if content_length is None else {"content_length": content_length}
    # /agent/chat must never start a real CLI or call the API; /approval-mode must not change the mode.
    stub = {"ok": True, "response": "stub", "session_id": "s"}
    # Route rate limits have their own tests (test_call_limits.py); thousands of examples would trip them.
    # The chat dispatch itself is stubbed: which providers are installed on the runner (none on the
    # secret-free nightly job, where every provider answers 502) is not what this parser test checks.
    with mock.patch.object(panel_server.agent_bridge, "run_agent_turn", return_value=stub), \
            mock.patch.object(panel_server.agent_native, "run_native_turn", return_value=stub), \
            mock.patch.object(panel_server.PanelRequestHandler, "_dispatch_chat", return_value=stub), \
            mock.patch.object(panel_server.PanelRequestHandler, "_rate_limited", return_value=False), \
            mock.patch.object(panel_server, "set_panel_mode"):
        status, payload = _drive(hub.cls, _request("POST", path, _headers(body, **overrides), body))
    event(f"status {status}")
    assert status in DOCUMENTED, (status, payload, body[:200])
    if status >= 400:
        assert payload["ok"] is False and isinstance(payload["error"], str) and payload["error"]
    assert _plan_state(hub) == "pending"


# --- regressions found by the fuzz ----------------------------------------------------------


@pytest.mark.parametrize("raw,error", [
    (b'{"tool": "x\xff"}', "valid JSON"),                     # invalid UTF-8: was an unhandled UnicodeDecodeError
    (b'{"tool": ' + b"1" * 5000 + b"}", "valid JSON"),        # int digit limit: was an unhandled ValueError
    (b"[" * 100_000 + b"]" * 100_000, "nested too deeply"),   # was an unhandled RecursionError
    (b'{"arguments": ' + b"[" * 70 + b"]" * 70 + b"}", "nested too deeply"),
    (b'{"tool": "list_pending_plans", "arguments": {"a": NaN}}', "valid JSON"),
    (b'{"tool": "list_pending_plans", "arguments": {"a": 1e999}}', "valid JSON"),
    (b"[]", "JSON object"),
], ids=["invalid-utf8", "long-int", "deep-array", "deep-arguments", "nan", "overflow-float", "not-object"])
# Short ids: pytest puts the test id in PYTEST_CURRENT_TEST, and Windows caps an environment
# variable at 32767 characters, so a 200 KB input as its own id breaks the run there.
def test_unparseable_bodies_are_400(hub: SimpleNamespace, raw: bytes, error: str) -> None:
    for path in ("/execute", "/approval-mode", "/agent/chat"):
        status, payload = _drive(hub.cls, _request("POST", path, _headers(raw), raw))
        assert status == 400 and error in payload["error"], (path, payload)


@pytest.mark.parametrize("arguments", [[], "x", 1, None, True])
def test_execute_refuses_non_object_arguments(hub: SimpleNamespace, arguments: Any) -> None:
    raw = _dump({"tool": "list_pending_plans", "arguments": arguments})
    status, payload = _drive(hub.cls, _request("POST", "/execute", _headers(raw), raw))
    assert status == 400 and payload["error"] == "'arguments' must be a JSON object"


def test_execute_unknown_tool_is_400(hub: SimpleNamespace) -> None:
    raw = _dump({"tool": "not_a_real_tool", "arguments": {}})
    status, payload = _drive(hub.cls, _request("POST", "/execute", _headers(raw), raw))
    assert status == 400 and "not_a_real_tool" in payload["error"]


def test_parse_json_object_accepts_plain_requests() -> None:
    assert parse_json_object(b"") == {}
    assert parse_json_object(b'{"tool": "x", "arguments": {"a": [1, 2.5, "\\u00e9"]}}') == {
        "tool": "x", "arguments": {"a": [1, 2.5, "é"]}}
    deep = b'{"a": ' * 63 + b"1" + b"}" * 63
    assert parse_json_object(deep)


# --- the payload path check -----------------------------------------------------------------


@pytest.fixture(scope="module")
def path_tree(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """ws/ with links that point out of it and a reserved folder; outside/ next to it."""
    base = tmp_path_factory.mktemp("payload-paths")
    ws, outside = base / "ws", base / "outside"
    for folder in (ws / "inside", outside, *(ws / name for name in RESERVED_DIRS)):
        folder.mkdir(parents=True)
    links = {}
    for name, target in {"dirlink": outside, "plink": ws / "plans", "loop": ws / "loop"}.items():
        try:
            (ws / name).symlink_to(target, target_is_directory=True)
            links[name] = target
        except OSError:  # no symlink privilege on this Windows runner
            pass
    from revit_mcp_server.config import BridgeMode
    from revit_mcp_server.providers.revit import RevitProvider

    provider = RevitProvider(WorkspaceMonitor([ws]), BridgeMode.mock)
    return SimpleNamespace(ws=ws, outside=outside, provider=provider)


def _inside(resolved: str, root: Path) -> bool:
    resolved, root_text = os.path.normcase(resolved), os.path.normcase(os.path.realpath(root))
    return resolved == root_text or resolved.startswith(os.path.join(root_text, ""))


@st.composite
def payload_paths(draw: st.DrawFn, tree: SimpleNamespace) -> Any:
    prefix = draw(st.sampled_from(["", str(tree.ws) + os.sep, str(tree.outside) + os.sep, str(tree.ws.parent) + os.sep,
                                   os.sep, str(tree.ws)]))
    tail = draw(st.one_of(st.lists(st.sampled_from(FRAGMENTS + ["plans", "proofs", "plink", "/", os.sep]),
                                   max_size=6).map("".join),
                          st.text(max_size=30)))
    return prefix + tail


@given(data=st.data())
def test_payload_paths_never_leave_the_workspace(path_tree: SimpleNamespace, data: st.DataObject) -> None:
    keys = data.draw(st.lists(st.sampled_from(PATH_KEYS + ["name", "folder"]), min_size=1, max_size=3, unique=True))
    arguments = {key: data.draw(st.one_of(payload_paths(path_tree), json_values)) for key in keys}
    try:
        path_tree.provider._assert_paths_in_workspace(arguments)
    except WorkspaceViolation:
        event("refused")
        return
    event("admitted")
    for key in PATH_KEYS:
        value = arguments.get(key)
        if value is None:
            continue
        assert isinstance(value, str), f"{key}={value!r} was admitted without a path check"
        resolved = os.path.normpath(os.path.realpath(value))
        assert _inside(resolved, path_tree.ws), (key, value, resolved)
        for name in RESERVED_DIRS:
            assert not _inside(resolved, path_tree.ws / name), (key, value, resolved)


@pytest.mark.parametrize("value", [["/etc/passwd"], {"p": "/etc"}, 1, True, ["inside"]])
def test_payload_path_keys_refuse_non_strings(path_tree: SimpleNamespace, value: Any) -> None:
    for key in PATH_KEYS:
        with pytest.raises(WorkspaceViolation, match="must be a text path"):
            path_tree.provider._assert_paths_in_workspace({key: value})
