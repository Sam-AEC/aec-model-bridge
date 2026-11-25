"""mcp_server.py error, refusal and shutdown paths (issue #238).

Everything runs in process with fakes or the mock registry: no subprocess, no Revit, no real sleeps.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from importlib import metadata
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult

from revit_mcp_server import mcp_apps, mcp_prompts, mcp_resources, mcp_server, mcp_tasks, usage_counts
from revit_mcp_server.elicitation import ElicitationForbidden, InputNeeded
from revit_mcp_server.errors import BridgeError, CommandFailed
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_profiles import ToolProfileBlocked


def run(coro):
    return asyncio.run(coro)


def kind_of(result) -> str:
    assert isinstance(result, CallToolResult) and result.isError
    return result.structuredContent["error"]["kind"]


class Gate:
    """Records every claim and outcome. ``claims`` False means claim_action refuses like the real gate."""

    approval_mode = "ask_first"

    def __init__(self):
        self.finished: list[tuple[bool, str | None]] = []

    def claim_action(self, name, arguments):
        return {"plan_id": "plan-1", "action_id": "act-1"}

    def finish_action(self, claim, ok, error=None):
        self.finished.append((ok, error))

    def audit_dev_call(self, name, arguments, mutating):
        pass


class Provider:
    def __init__(self, result=None, error=None):
        self.result = {"ok": True} if result is None else result
        self.error = error
        self.calls: list[tuple[str, object]] = []

    async def execute_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return self.result


def install(monkeypatch, provider=None, mutating=False, gate=None, registry=None):
    """Put fakes into the module globals; returns (registry, gate)."""
    provider = provider or Provider()
    gate = gate or Gate()
    registry = registry or SimpleNamespace(
        lookup_tool_provider=lambda name: provider,
        lookup_tool=lambda name: SimpleNamespace(is_mutating=mutating),
    )
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=gate))
    return registry, gate


# ---- version and plain MCP handlers ---------------------------------------------------------------


def test_package_version_reports_the_installed_version(monkeypatch):
    monkeypatch.setattr(metadata, "version", lambda dist: "9.8.7" if dist == "aec-model-bridge" else "other")
    assert mcp_server._package_version() == "9.8.7"


def test_package_version_falls_back_when_metadata_is_missing(monkeypatch):
    def missing(dist):
        raise metadata.PackageNotFoundError(dist)

    monkeypatch.setattr(metadata, "version", missing)
    assert mcp_server._package_version() == "0.0.0"


def test_prompt_and_resource_handlers_delegate_to_their_modules(monkeypatch):
    seen = []
    monkeypatch.setattr(mcp_prompts, "list_prompts", lambda: ["prompts"])
    monkeypatch.setattr(mcp_prompts, "get_prompt", lambda name, arguments: seen.append((name, arguments)) or "one")
    monkeypatch.setattr(mcp_resources, "list_resources", lambda: ["resources"])
    monkeypatch.setattr(mcp_resources, "list_resource_templates", lambda: ["templates"])
    assert run(mcp_server.list_prompts()) == ["prompts"]
    assert run(mcp_server.get_prompt("p", {"a": "b"})) == "one"
    assert seen == [("p", {"a": "b"})]
    assert run(mcp_server.list_resources()) == ["resources"]
    assert run(mcp_server.list_resource_templates()) == ["templates"]


def test_unknown_prompt_is_refused_not_swallowed():
    with pytest.raises(ValueError, match="Unknown prompt"):
        run(mcp_server.get_prompt("no_such_prompt", None))


def test_read_resource_serves_ui_and_workspace_resources(monkeypatch):
    gate = Gate()
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=gate))
    monkeypatch.setattr(mcp_server, "workspace_monitor", SimpleNamespace(allowed_directories=["ws-root"]))
    monkeypatch.setattr(mcp_apps, "read_resource", lambda uri, g: ("<html/>", {"m": 1}) if g is gate else None)
    monkeypatch.setattr(mcp_resources, "read_resource",
                        lambda uri, root, g: f"{root}|{uri}" if g is gate else None)
    ui = run(mcp_server.read_resource("ui://plan/review"))
    assert (ui[0].content, ui[0].mime_type, ui[0].meta) == ("<html/>", mcp_apps.MIME, {"m": 1})
    text = run(mcp_server.read_resource("aec://workspace"))
    assert (text[0].content, text[0].mime_type) == ("ws-root|aec://workspace", mcp_resources.MIME)


def test_request_helpers_are_none_outside_a_request():
    assert mcp_server._client_session() is None
    assert mcp_server._request_id() is None
    assert mcp_server._session_key() == "direct"


def test_workspace_root_is_none_without_a_workspace(monkeypatch):
    monkeypatch.setattr(mcp_server, "workspace_monitor", None)
    assert mcp_server._workspace_root() is None
    monkeypatch.setattr(mcp_server, "workspace_monitor", SimpleNamespace(allowed_directories=[]))
    assert mcp_server._workspace_root() is None


# ---- _may_elicit fails closed ----------------------------------------------------------------------


def test_may_elicit_is_false_when_the_tool_lookup_fails(monkeypatch):
    def boom(name):
        raise RuntimeError("registry broken")

    install(monkeypatch, registry=SimpleNamespace(lookup_tool=boom, lookup_tool_provider=boom))
    assert mcp_server._may_elicit("set_thing", {}) is False


def test_may_elicit_refuses_a_call_the_gate_would_refuse_unless_auto(monkeypatch):
    _, gate = install(monkeypatch, mutating=True)
    assert mcp_server._may_elicit("set_thing", {}) is False  # needs an approved plan
    assert mcp_server._may_elicit("set_thing", {"plan_id": "plan-1"}) is False  # carries a plan
    gate.approval_mode = "auto"
    assert mcp_server._may_elicit("set_thing", {}) is True
    assert mcp_server._may_elicit("approve_plan", {}) is False  # approval tools never ask


# ---- call_tool elicitation loop --------------------------------------------------------------------


def _need(refusal="Need a name.", apply=None):
    return InputNeeded(refusal, question="Which?", field="name", options=["a", "b"],
                       apply=apply or (lambda args, answer: {**args, "name": answer}))


def test_forbidden_elicitation_ends_with_the_plain_refusal(monkeypatch):
    async def once(name, arguments):
        raise _need("Need a name.")

    async def forbidden(*args, **kwargs):
        raise ElicitationForbidden("never")

    monkeypatch.setattr(mcp_server, "_call_tool_once", once)
    monkeypatch.setattr(mcp_server, "_may_elicit", lambda name, arguments: True)
    monkeypatch.setattr(mcp_server, "elicit_choice", forbidden)
    result = run(mcp_server.call_tool("set_thing", {}))
    assert kind_of(result) == "input_needed"
    assert "Need a name." in result.content[0].text


def test_second_input_needed_after_an_answer_returns_its_refusal(monkeypatch):
    async def once(name, arguments):
        raise _need("first", apply=lambda args, answer: (_ for _ in ()).throw(_need("second refusal")))

    async def answer(*args, **kwargs):
        return "a"

    monkeypatch.setattr(mcp_server, "_call_tool_once", once)
    monkeypatch.setattr(mcp_server, "_may_elicit", lambda name, arguments: True)
    monkeypatch.setattr(mcp_server, "elicit_choice", answer)
    result = run(mcp_server.call_tool("set_thing", {"keep": 1}))
    assert kind_of(result) == "input_needed"
    assert "second refusal" in result.content[0].text


def test_declined_question_returns_the_refusal_and_runs_nothing(monkeypatch):
    calls = []

    async def once(name, arguments):
        calls.append(arguments)
        raise _need("Need a name.")

    async def declined(*args, **kwargs):
        return None

    monkeypatch.setattr(mcp_server, "_call_tool_once", once)
    monkeypatch.setattr(mcp_server, "_may_elicit", lambda name, arguments: True)
    monkeypatch.setattr(mcp_server, "elicit_choice", declined)
    assert kind_of(run(mcp_server.call_tool("set_thing", {}))) == "input_needed"
    assert calls == [{}]  # asked once, never re-run


# ---- _list_views_or_sheets -------------------------------------------------------------------------


def _lister(monkeypatch, provider, tool_def, gate_result=None):
    registry = SimpleNamespace(lookup_tool_provider=lambda name: provider, lookup_tool=lambda name: tool_def)
    install(monkeypatch, registry=registry)
    monkeypatch.setattr(mcp_server, "gate_before", lambda reg, gate, name, args: gate_result)


READ_TOOL = SimpleNamespace(is_mutating=False)


def test_listing_returns_rows_and_total_for_views(monkeypatch):
    provider = Provider({"ok": True, "rows": [{"id": 1, "name": "L1"}, {"id": None}, "junk", {"id": 2}],
                         "limits": {"rows_total": 9}})
    _lister(monkeypatch, provider, READ_TOOL)
    assert run(mcp_server._list_views_or_sheets("view", "L")) == ([{"id": 1, "name": "L1"}, {"id": 2}], 9)
    args = provider.calls[0][1]
    assert args["kinds"] == ["views", "schedules"] and args["name_contains"] == "L"
    assert args["limit"] == mcp_server.VIEW_SHEET_LIST_LIMIT


def test_listing_sheets_keeps_only_rows_with_a_number(monkeypatch):
    provider = Provider({"ok": True, "rows": [{"id": 1, "number": "A1"}, {"id": 2, "number": ""}, {"id": 3}]})
    _lister(monkeypatch, provider, READ_TOOL)
    assert run(mcp_server._list_views_or_sheets("sheet", "A")) == ([{"id": 1, "number": "A1"}], 1)
    assert provider.calls[0][1]["kinds"] == ["sheets"]


@pytest.mark.parametrize("total", [None, "9", 0, 1.5])
def test_listing_ignores_a_total_that_is_not_a_plausible_count(monkeypatch, total):
    provider = Provider({"ok": True, "rows": [{"id": 1}, {"id": 2}], "limits": {"rows_total": total}})
    _lister(monkeypatch, provider, READ_TOOL)
    assert run(mcp_server._list_views_or_sheets("view", "x")) == ([{"id": 1}, {"id": 2}], 2)


@pytest.mark.parametrize("result", [
    "text", None, {"ok": True, "mock": True, "rows": [{"id": 1}]}, {"ok": False}, {"rows": [{"id": 1}]},
])
def test_listing_gives_up_quietly_on_an_unusable_result(monkeypatch, result):
    _lister(monkeypatch, SimpleNamespace(execute_tool=lambda n, a: _async(result)), READ_TOOL)
    assert run(mcp_server._list_views_or_sheets("view", "x")) is None


async def _async(value):
    return value


@pytest.mark.parametrize("provider,tool_def", [
    (None, READ_TOOL),
    (Provider(), None),
    (Provider(), SimpleNamespace(is_mutating=True)),
])
def test_listing_does_nothing_when_the_list_tool_is_missing_or_mutating(monkeypatch, provider, tool_def):
    _lister(monkeypatch, provider, tool_def)
    assert run(mcp_server._list_views_or_sheets("view", "x")) is None
    if provider is not None:
        assert provider.calls == []


def test_listing_does_not_run_when_the_gate_holds_the_call(monkeypatch):
    provider = Provider({"ok": True, "rows": [{"id": 1}]})
    _lister(monkeypatch, provider, READ_TOOL, gate_result={"plan_id": "p"})
    assert run(mcp_server._list_views_or_sheets("view", "x")) is None
    assert provider.calls == []


def test_listing_logs_and_gives_up_when_the_tool_raises(monkeypatch, caplog):
    _lister(monkeypatch, Provider(error=BridgeError("no Revit")), READ_TOOL)
    with caplog.at_level(logging.INFO, logger=mcp_server.logger.name):
        assert run(mcp_server._list_views_or_sheets("sheet", "x")) is None
    assert any("Could not list sheets" in r.getMessage() for r in caplog.records)


# ---- _call_tool_once refusals ----------------------------------------------------------------------


def test_profile_blocked_tool_is_refused_at_lookup(monkeypatch):
    def blocked(name):
        raise ToolProfileBlocked("hidden by the profile")

    install(monkeypatch, registry=SimpleNamespace(lookup_tool_provider=blocked))
    result = run(mcp_server.call_tool("revit_mep_thing", {}))
    assert kind_of(result) == "tool_profile_blocked"
    assert "hidden by the profile" in result.content[0].text


def test_profile_blocked_tool_is_refused_at_the_gate(monkeypatch):
    provider = Provider()
    install(monkeypatch, provider)

    def blocked(*args):
        raise ToolProfileBlocked("blocked at the gate")

    monkeypatch.setattr(mcp_server, "gate_before", blocked)
    assert kind_of(run(mcp_server.call_tool("revit_x", {}))) == "tool_profile_blocked"
    assert provider.calls == []


def test_profile_blocked_during_execution_is_reported(monkeypatch):
    install(monkeypatch, Provider(error=ToolProfileBlocked("blocked inside")))
    assert kind_of(run(mcp_server.call_tool("revit_x", {}))) == "tool_profile_blocked"


def test_gate_failure_is_reported_as_approval_blocked(monkeypatch):
    provider = Provider()

    class Refusing(Gate):
        def claim_action(self, name, arguments):
            raise BridgeError("no approved plan")

    install(monkeypatch, provider, mutating=True, gate=Refusing())
    result = run(mcp_server.call_tool("set_thing", {}))
    assert kind_of(result) == "approval_blocked"
    assert "Approval Gate Blocked: no approved plan" in result.content[0].text
    assert provider.calls == []


def test_failing_read_only_classification_fails_closed(monkeypatch):
    calls = {"n": 0}

    def lookup(name):
        calls["n"] += 1
        if calls["n"] == 2:  # the read-only check; the gate and others succeed
            raise RuntimeError("metadata broken")
        return SimpleNamespace(is_mutating=False)

    install(monkeypatch, registry=SimpleNamespace(lookup_tool_provider=lambda n: Provider(), lookup_tool=lookup))
    result = run(mcp_server.call_tool("revit_x", {}))
    assert result[0].text.startswith("✓ revit_x executed successfully")


def test_bad_response_options_are_refused_before_running(monkeypatch):
    provider = Provider()
    install(monkeypatch, provider)
    result = run(mcp_server.call_tool("revit_list_elements", {"response_options": "nope"}))
    assert kind_of(result) == "invalid_response_options"
    assert provider.calls == []


def test_usage_count_failure_never_fails_the_call(monkeypatch, caplog):
    class Counter:
        def record(self, name):
            raise OSError("disk full")

    registry, _ = install(monkeypatch)
    registry.usage_counter = Counter()
    with caplog.at_level(logging.DEBUG, logger=mcp_server.logger.name):
        result = run(mcp_server.call_tool("revit_x", {}))
    assert result[0].text.startswith("✓ revit_x executed successfully")
    assert any("Tool usage count skipped" in r.getMessage() for r in caplog.records)


# ---- cursor requests -------------------------------------------------------------------------------


def test_cursor_is_refused_when_the_call_holds_an_approved_action(monkeypatch):
    provider = Provider()
    install(monkeypatch, provider, mutating=False)
    monkeypatch.setattr(mcp_server, "gate_before", lambda *a: {"plan_id": "p", "action_id": "a"})
    result = run(mcp_server.call_tool("revit_list_elements", {"response_options": {"cursor": "abc"}}))
    assert kind_of(result) == "invalid_cursor"
    assert "does not take a cursor" in result.content[0].text
    assert provider.calls == []


def test_unknown_cursor_is_refused_without_running_the_tool(monkeypatch):
    provider = Provider()
    install(monkeypatch, provider)
    result = run(mcp_server.call_tool("revit_list_elements", {"response_options": {"cursor": "no-such-cursor"}}))
    assert kind_of(result) == "invalid_cursor"
    assert provider.calls == []


# ---- run_async queueing ----------------------------------------------------------------------------


class Jobs:
    def __init__(self, error=None):
        self.error = error
        self.submitted = []

    async def submit(self, func, idempotency_key=None):
        self.submitted.append((func, idempotency_key))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(job_id="job-1", to_dict=lambda: {"job_id": "job-1"})


@pytest.mark.parametrize("flag", ["true", "1", "YES"])
def test_run_async_text_flags_queue_a_job(monkeypatch, flag):
    provider = Provider()
    install(monkeypatch, provider)
    jobs = Jobs()
    monkeypatch.setattr(mcp_server, "job_manager", jobs)
    result = run(mcp_server.call_tool("revit_x", {"run_async": flag, "idempotency_key": "k1"}))
    assert "Job job-1 queued successfully" in result[0].text
    assert jobs.submitted[0][1] == "k1"
    assert provider.calls == []  # queued, not run


def test_run_async_false_text_runs_the_tool_now(monkeypatch):
    provider = Provider()
    install(monkeypatch, provider)
    monkeypatch.setattr(mcp_server, "job_manager", Jobs())
    result = run(mcp_server.call_tool("revit_x", {"run_async": "no"}))
    assert "executed successfully" in result[0].text
    assert len(provider.calls) == 1


@pytest.mark.parametrize("error,kind", [
    (CommandFailed("Revit said no", {"reason": "locked"}), "bridge_error"),
    (ToolProfileBlocked("blocked at queue time"), "tool_profile_blocked"),
    (BridgeError("bridge down"), "bridge_error"),
    (RuntimeError("queue closed"), "execution_error"),
])
def test_queueing_failures_are_reported_by_kind(monkeypatch, error, kind):
    install(monkeypatch)
    monkeypatch.setattr(mcp_server, "job_manager", Jobs(error))
    result = run(mcp_server.call_tool("revit_x", {"run_async": True}))
    assert kind_of(result) == kind
    if isinstance(error, CommandFailed):
        assert result.structuredContent["result"] == {"reason": "locked"}


def test_a_write_queued_as_a_job_still_needs_an_approved_plan(monkeypatch):
    provider = Provider()

    class Refusing(Gate):
        def claim_action(self, name, arguments):
            raise BridgeError("plan_id required")

    install(monkeypatch, provider, mutating=True, gate=Refusing())
    jobs = Jobs()
    monkeypatch.setattr(mcp_server, "job_manager", jobs)
    assert kind_of(run(mcp_server.call_tool("set_thing", {"run_async": True}))) == "approval_blocked"
    assert jobs.submitted == [] and provider.calls == []


def test_non_dict_arguments_skip_the_async_check(monkeypatch):
    provider = Provider()
    install(monkeypatch, provider)
    result = run(mcp_server.call_tool("revit_x", None))
    assert "executed successfully" in result[0].text
    assert provider.calls == [("revit_x", None)]


# ---- timeouts and in-flight bookkeeping ------------------------------------------------------------


def test_cancelled_background_write_leaves_the_action_running():
    gate = Gate()
    loop = asyncio.new_event_loop()
    try:
        task = loop.create_future()
        timed_out = SimpleNamespace(seconds=1, kept_running=True, task=task)
        mcp_server._timed_out("set_thing", {}, None, gate, timed_out)  # no claim: nothing to settle by key
        task.cancel()
        loop.run_until_complete(asyncio.sleep(0))  # lets the done callback run
    finally:
        loop.close()
    assert gate.finished == []  # cancelled: outcome unknown, nothing booked


def test_fetch_revit_result_needs_the_result_tool(monkeypatch):
    install(monkeypatch, registry=SimpleNamespace(lookup_tool_provider=lambda name: None))
    with pytest.raises(BridgeError, match="not available to follow request req-1"):
        run(mcp_server._fetch_revit_result("req-1"))


def test_provably_read_only_is_false_for_the_approval_provider_itself(monkeypatch):
    provider = Provider()
    monkeypatch.setattr(mcp_server, "registry", SimpleNamespace(
        lookup_tool_provider=lambda name: provider, lookup_tool=lambda name: SimpleNamespace(is_mutating=False)))
    monkeypatch.setattr(mcp_server, "approval_provider", provider)
    assert mcp_server._provably_read_only("some_read", {}, None, True) is False


def test_provably_read_only_is_false_for_a_mutating_tool_and_when_the_check_fails(monkeypatch):
    provider = Provider()
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=Gate()))
    monkeypatch.setattr(mcp_server, "registry", SimpleNamespace(
        lookup_tool_provider=lambda name: provider, lookup_tool=lambda name: SimpleNamespace(is_mutating=True)))
    assert mcp_server._provably_read_only("some_write", {}, None, True) is False

    def boom(name):
        raise RuntimeError("registry broken")

    monkeypatch.setattr(mcp_server, "registry", SimpleNamespace(lookup_tool_provider=boom, lookup_tool=boom))
    assert mcp_server._provably_read_only("some_read", {}, None, True) is False
    assert mcp_server._call_writes("some_read", {}) is True  # unclassifiable counts as a write


# ---- MCP tasks -------------------------------------------------------------------------------------


class TaskBridge:
    def __init__(self, error=None):
        self.error = error
        self.kwargs = None

    async def start(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return "created"


def _task_call(monkeypatch, bridge, gate):
    install(monkeypatch, gate=gate, mutating=True)
    monkeypatch.setattr(mcp_server, "task_bridge", bridge)
    monkeypatch.setattr(mcp_tasks, "session_scope", lambda server: "scope-1")
    claim = {"plan_id": "plan-1", "action_id": "act-1"}
    return run(mcp_server._start_task("revit_export", Provider(), {}, claim, gate, {}, False, object()))


def test_task_cancelled_before_it_starts_books_the_action_as_failed(monkeypatch):
    gate, bridge = Gate(), TaskBridge()
    assert _task_call(monkeypatch, bridge, gate) == "created"
    assert bridge.kwargs["scope"] == "scope-1" and bridge.kwargs["writes"] is True
    bridge.kwargs["on_cancel_before_start"]()
    assert gate.finished == [(False, "Task cancelled before it started; nothing ran.")]


@pytest.mark.parametrize("error,text", [
    (RuntimeError("too many tasks"), "too many tasks"),
    (RuntimeError(""), ""),
])
def test_task_that_cannot_be_queued_fails_the_claimed_action(monkeypatch, error, text):
    gate = Gate()
    result = _task_call(monkeypatch, TaskBridge(error), gate)
    assert kind_of(result) == "execution_error"
    assert "the task could not be started" in result.content[0].text and text in result.content[0].text
    assert gate.finished == [(False, text or "RuntimeError")]


# ---- small helpers ---------------------------------------------------------------------------------


def test_json_object_returns_none_for_text_that_is_not_json():
    assert mcp_server._json_object("{not json") is None
    assert mcp_server._json_object('{"a": 1}') == {"a": 1}


def test_tool_error_redacts_secrets_in_message_and_result():
    result = mcp_server._tool_error("bridge_error", "failed token=private-example-token", result={"k": 1},
                                    details={"retry_after_seconds": 3})
    assert result.structuredContent["error"]["retry_after_seconds"] == 3
    assert result.structuredContent["result"] == {"k": 1}
    assert "private-example-token" not in result.model_dump_json()


# ---- startup and shutdown --------------------------------------------------------------------------


class FakeCounter:
    def __init__(self):
        self.flushed = 0

    def flush(self):
        self.flushed += 1


class FakeJobs:
    def __init__(self):
        self.shutdown_calls = []

    async def shutdown(self, cancel_running=False):
        self.shutdown_calls.append(cancel_running)


class FakeRegistry:
    def __init__(self):
        self.frozen = None
        self.usage_counter = None

    def freeze_tool_profile(self, profile):
        self.frozen = profile


def _start(monkeypatch, app_run, detail="profile detail"):
    """Fake everything main() builds; returns the objects it should touch."""
    profile = SimpleNamespace(detail=detail)
    counter, jobs, registry = FakeCounter(), FakeJobs(), FakeRegistry()
    streams = ("read-stream", "write-stream")

    @contextlib.asynccontextmanager
    async def stdio():
        yield streams

    monkeypatch.setattr(mcp_server, "load_tool_profile", lambda: profile)
    monkeypatch.setattr(usage_counts, "start_counter", lambda workspace: counter)
    monkeypatch.setattr(mcp_server, "build_registry",
                        lambda: (registry, "approval", jobs, "modules", "workspace"))
    monkeypatch.setattr(mcp_server, "stdio_server", stdio)
    monkeypatch.setattr(mcp_server.app, "run", app_run)
    monkeypatch.setattr(mcp_server.app, "create_initialization_options", lambda: "init-options")
    for name in ("registry", "approval_provider", "job_manager", "workspace_monitor"):
        monkeypatch.setattr(mcp_server, name, None)
    return profile, counter, jobs, registry, streams


def test_main_wires_the_registry_runs_over_stdio_and_shuts_down(monkeypatch, caplog):
    ran = []

    async def app_run(read, write, options):
        ran.append((read, write, options))

    profile, counter, jobs, registry, streams = _start(monkeypatch, app_run)
    with caplog.at_level(logging.INFO, logger=mcp_server.logger.name):
        run(mcp_server.main())
    assert ran == [(*streams, "init-options")]
    assert registry.frozen is profile and registry.usage_counter is counter
    assert (mcp_server.registry, mcp_server.approval_provider) == (registry, "approval")
    assert (mcp_server.job_manager, mcp_server.workspace_monitor) == (jobs, "workspace")
    assert counter.flushed == 1 and jobs.shutdown_calls == [True]
    assert any("profile detail" in r.getMessage() for r in caplog.records)


def test_main_skips_the_profile_log_line_when_there_is_no_detail(monkeypatch, caplog):
    async def app_run(read, write, options):
        return None

    _start(monkeypatch, app_run, detail="")
    with caplog.at_level(logging.INFO, logger=mcp_server.logger.name):
        run(mcp_server.main())
    assert not [r for r in caplog.records if r.name == mcp_server.logger.name and r.levelno == logging.INFO]


def test_main_flushes_and_cancels_running_jobs_when_the_server_crashes(monkeypatch):
    async def app_run(read, write, options):
        raise ConnectionError("client vanished")

    _, counter, jobs, _, _ = _start(monkeypatch, app_run)
    with pytest.raises(ConnectionError, match="client vanished"):
        run(mcp_server.main())
    assert counter.flushed == 1 and jobs.shutdown_calls == [True]


def test_main_cleans_up_when_the_run_is_cancelled(monkeypatch):
    async def app_run(read, write, options):
        raise asyncio.CancelledError()

    _, counter, jobs, _, _ = _start(monkeypatch, app_run)
    with pytest.raises(asyncio.CancelledError):
        run(mcp_server.main())
    assert counter.flushed == 1 and jobs.shutdown_calls == [True]


def test_main_does_not_start_jobs_or_flush_when_registry_construction_fails(monkeypatch):
    async def app_run(read, write, options):
        pytest.fail("the server must not run without a registry")

    _, counter, _, _, _ = _start(monkeypatch, app_run)

    def broken():
        raise RuntimeError("provider failed to start")

    monkeypatch.setattr(mcp_server, "build_registry", broken)
    with pytest.raises(RuntimeError, match="provider failed to start"):
        run(mcp_server.main())
    assert counter.flushed == 0


def test_entry_point_runs_the_server_with_no_arguments(monkeypatch):
    calls = []

    async def fake_main():
        calls.append("main")

    monkeypatch.setattr(sys, "argv", ["aec-model-bridge"])
    monkeypatch.setattr(mcp_server, "main", fake_main)
    mcp_server.run_mcp_server()
    assert calls == ["main"]


def test_entry_point_answers_version_without_starting_the_server(monkeypatch, capsys):
    async def fake_main():
        pytest.fail("--version must not start the server")

    monkeypatch.setattr(sys, "argv", ["aec-model-bridge", "--version"])
    monkeypatch.setattr(mcp_server, "main", fake_main)
    with pytest.raises(SystemExit) as exit_info:
        mcp_server.run_mcp_server()
    assert exit_info.value.code == 0
    assert "aec-model-bridge" in capsys.readouterr().out


# ---- gate: a write without an approved plan is refused on every path -------------------------------

WRITE_TOOLS = [
    "revit_render_3d",
    "navisworks_create_viewpoint",
    "rhino_generate_diagrid_tower",
    "navisworks_append_file",
]


@pytest.fixture(scope="module")
def mock_registry(tmp_path_factory):
    return build_registry(WorkspaceMonitor([tmp_path_factory.mktemp("gate-ws")]))


@pytest.fixture
def gated(monkeypatch, mock_registry):
    registry, approval_provider, jobs, _modules, workspace = mock_registry
    gate = approval_provider.gate
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval_provider)
    monkeypatch.setattr(mcp_server, "job_manager", jobs)
    monkeypatch.setattr(mcp_server, "workspace_monitor", workspace)
    previous = gate.approval_mode
    yield gate
    gate.approval_mode = previous


@pytest.mark.parametrize("mode", ["ask_first", "look_only"])
@pytest.mark.parametrize("extra", [{}, {"run_async": True}, {"plan_id": "plan-that-does-not-exist"}])
@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_without_an_approved_plan_is_refused(gated, tool, extra, mode):
    assert mcp_server.registry.lookup_tool(tool).is_mutating
    gated.approval_mode = mode
    result = run(mcp_server.call_tool(tool, dict(extra)))
    assert kind_of(result) == "approval_blocked"
    assert "executed successfully" not in result.content[0].text
