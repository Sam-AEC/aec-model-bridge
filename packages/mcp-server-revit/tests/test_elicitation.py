"""MCP elicitation for missing or ambiguous inputs (issue #282).

The server asks the client's user one structured question only when the client
declared the elicitation capability. Otherwise, and on decline, cancel, timeout or
an invalid answer, the call ends with the plain refusal that names the input.
Approval tools can never ask.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from revit_mcp_server import elicitation, mcp_server
from revit_mcp_server.elicitation import (
    APPROVAL_TOOLS,
    ElicitationForbidden,
    InputNeeded,
    client_supports_elicitation,
    elicit_choice,
    elicitation_allowed,
    missing_export_path,
)
from revit_mcp_server.semantic.engine import generate_mock_snapshot
from revit_mcp_server.semantic.models import ElementRecord, ParamVal

SRC = Path(__file__).resolve().parents[1] / "src" / "revit_mcp_server"


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def server(tmp_path, monkeypatch):
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    monitor = WorkspaceMonitor([tmp_path])
    registry, approval, jobs, _, _ = build_registry(monitor)
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "workspace_monitor", monitor)
    snap = generate_mock_snapshot()
    snap.elements.append(ElementRecord(
        uid="level-10-uid", element_id=102, category="OST_Levels", cls="Level", type_name="Level 10",
        params={"Elevation": ParamVal(v=40.0, storage="Double", readonly=True)},
    ))
    folder = tmp_path / "snapshots"
    folder.mkdir()
    (folder / f"{snap.snapshot_id}.json").write_text(snap.model_dump_json(by_alias=True), encoding="utf-8")
    yield SimpleNamespace(root=tmp_path, approval=approval, snapshot_id=snap.snapshot_id)
    asyncio.run(jobs.shutdown(cancel_running=True))


class Asker:
    """An elicitation callback that records each question and answers from a script."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    async def __call__(self, context, params):
        self.asked.append(params)
        action, content = self.answers.pop(0)
        return types.ElicitResult(action=action, content=content)


async def _call(name, arguments, asker=None):
    kwargs = {"elicitation_callback": asker} if asker is not None else {}
    async with create_connected_server_and_client_session(mcp_server.app, **kwargs) as client:
        return await client.call_tool(name, arguments)


def call(name, arguments, asker=None):
    return asyncio.run(_call(name, arguments, asker))


def _result(answer) -> dict:
    assert not answer.isError, answer.content[0].text
    return json.loads(answer.content[0].text.split("Result:\n", 1)[1])


def _refusal(answer) -> str:
    assert answer.isError
    assert answer.structuredContent["error"]["kind"] == "input_needed"
    return answer.structuredContent["error"]["message"]


# ------------------------------------------------- (a) ambiguous level choice


def test_ambiguous_level_is_asked_as_an_enum_and_the_choice_is_used(server):
    asker = Asker(("accept", {"level": "Level 1"}))
    answer = call("snapshot_query", {"snapshot_id": server.snapshot_id,
                                     "filter": {"level": "level 1", "category": "OST_Walls"}}, asker)
    data = _result(answer)
    assert data["matches_count"] == 1
    (question,) = asker.asked
    schema = question.requestedSchema
    assert schema["properties"]["level"]["enum"] == ["Level 1", "Level 10"]
    assert schema["required"] == ["level"]
    assert all(p["type"] in ("string", "number", "integer", "boolean") for p in schema["properties"].values())


def test_ambiguous_level_without_capability_is_the_plain_refusal(server):
    answer = call("snapshot_query", {"snapshot_id": server.snapshot_id, "filter": {"level": "level 1"}})
    message = _refusal(answer)
    assert "'Level 1'" in message and "'Level 10'" in message and "filter.level" in message


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_decline_or_cancel_returns_the_plain_refusal(server, action):
    asker = Asker((action, None))
    answer = call("snapshot_query", {"snapshot_id": server.snapshot_id, "filter": {"level": "level 1"}}, asker)
    assert "matches several levels" in _refusal(answer)
    assert len(asker.asked) == 1


def test_exact_level_name_needs_no_question(server):
    asker = Asker()
    answer = call("snapshot_query", {"snapshot_id": server.snapshot_id,
                                     "filter": {"level": "Level 1", "category": "OST_Doors"}}, asker)
    assert _result(answer)["matches_count"] == 1
    assert asker.asked == []


# ---------------------------------------------- (c) unknown parameter names


def test_unknown_parameter_with_close_names_is_asked(server):
    asker = Asker(("accept", {"parameter": "FireRating"}))
    answer = call("snapshot_query", {"snapshot_id": server.snapshot_id,
                                     "filter": {"parameter": {"name": "Fire Rating", "value": "30"}}}, asker)
    assert _result(answer)["matches_count"] == 1
    assert asker.asked[0].requestedSchema["properties"]["parameter"]["enum"][0] == "FireRating"


def test_unknown_parameter_without_capability_names_the_close_names(server):
    answer = call("snapshot_query", {"snapshot_id": server.snapshot_id,
                                     "filter": {"parameter": {"name": "fireRating"}}})
    message = _refusal(answer)
    assert "'fireRating'" in message and "'FireRating'" in message


def test_unknown_parameter_with_no_close_name_keeps_the_old_behaviour(server):
    answer = call("snapshot_query", {"snapshot_id": server.snapshot_id,
                                     "filter": {"parameter": {"name": "Completely Different", "value": "x"}}})
    assert _result(answer)["matches_count"] == 0


def test_snapshot_compute_parameter_is_replaced_in_every_path(server):
    asker = Asker(("accept", {"parameter": "FireRating"}))
    steps = [{"name": "doors", "where": {"field": "params.Fire Rating", "op": "eq", "value": "30"},
              "select": ["params.Fire Rating", "params.Mark"]}]
    answer = call("snapshot_compute", {"snapshot_id": server.snapshot_id, "steps": steps}, asker)
    data = _result(answer)
    assert data["row_count"] == 1
    assert len(asker.asked) == 1


def test_snapshot_compute_saved_query_runs_inline_after_the_answer(server):
    queries = server.root / "queries"
    queries.mkdir()
    (queries / "rated.json").write_text(json.dumps({"steps": [
        {"name": "rated", "where": {"field": "params.Fire_Rating", "op": "exists"}},
    ]}), encoding="utf-8")
    asker = Asker(("accept", {"parameter": "FireRating"}))
    answer = call("snapshot_compute", {"snapshot_id": server.snapshot_id, "query": "rated"}, asker)
    assert _result(answer)["row_count"] == 1


def test_snapshot_compute_without_capability_refuses(server):
    steps = [{"name": "doors", "where": {"field": "params.Fire Rating", "op": "exists"}}]
    answer = call("snapshot_compute", {"snapshot_id": server.snapshot_id, "steps": steps})
    assert "'FireRating'" in _refusal(answer)


# -------------------------------------------------- (b) export file names


def test_export_without_output_path_is_refused_by_name(server):
    answer = call("revit_export_ifc", {})
    message = _refusal(answer)
    assert "output_path" in message and ".ifc" in message


def test_export_needing_a_plan_never_asks(server):
    # revit_export is gated: an answer would change arguments a person must approve in a plan.
    server.approval.gate.approval_mode = "ask_first"
    asker = Asker(("accept", {"file_name": "model"}))
    answer = call("revit_export", {"format": "ifc"}, asker)
    message = _refusal(answer)
    assert "needs path" in message and ".ifc" in message
    assert asker.asked == []
    assert not mcp_server._may_elicit("revit_export", {"format": "ifc"})
    server.approval.gate.approval_mode = "auto"
    assert mcp_server._may_elicit("revit_export", {"format": "ifc"})


def test_export_asks_for_a_file_name(server, monkeypatch):
    # The revit_export_* tools write a file, not the model, so they run without a plan.
    seen = {}

    async def fake_execute(name, arguments):
        seen["arguments"] = arguments
        return {"status": "success"}

    provider = mcp_server.registry.lookup_tool_provider("revit_export_ifc")
    monkeypatch.setattr(provider, "execute_tool", fake_execute)
    asker = Asker(("accept", {"file_name": "tower"}))
    answer = call("revit_export_ifc", {}, asker)
    assert not answer.isError, answer.content[0].text
    assert Path(seen["arguments"]["output_path"]) == Path(server.root) / "tower.ifc"
    assert asker.asked[0].requestedSchema["properties"]["file_name"]["type"] == "string"


def test_provider_refuses_a_missing_output_path_on_every_path(server):
    # Panel chat, recipes and execute_plan reach the provider without the MCP layer.
    provider = mcp_server.registry.lookup_tool_provider("revit_export_navisworks")
    with pytest.raises(InputNeeded, match="needs output_path"):
        asyncio.run(provider.execute_tool("revit_export_navisworks", {}))


def test_export_file_name_answer_cannot_leave_the_workspace(tmp_path):
    need = missing_export_path("revit_export_dwg", {"view_id": 5}, tmp_path)
    for bad in ("../x", "a/b", "..", "c:\\x", ".hidden"):
        with pytest.raises(InputNeeded):
            need.apply({"view_id": 5}, bad)
    assert need.apply({"view_id": 5}, "plan.dwg")["output_path"] == str(tmp_path / "plan.dwg")


def test_revit_export_uses_the_format_extension_and_skips_a_bad_format(tmp_path):
    need = missing_export_path("revit_export", {"format": "pdf", "all_sheets": True}, tmp_path)
    assert need.apply({"format": "pdf"}, "set")["path"] == str(tmp_path / "set.pdf")
    assert missing_export_path("revit_export", {"format": "xyz"}, tmp_path) is None
    assert missing_export_path("revit_export", {"format": "pdf", "path": "a.pdf"}, tmp_path) is None


# ------------------------------------------------------- the helper itself


def _session(capabilities):
    return SimpleNamespace(client_params=SimpleNamespace(capabilities=capabilities))


@pytest.mark.parametrize("caps, expected", [
    (types.ClientCapabilities(), False),
    (types.ClientCapabilities(elicitation=types.ElicitationCapability()), True),
    (types.ClientCapabilities(elicitation=types.ElicitationCapability(form=types.FormElicitationCapability())), True),
    (types.ClientCapabilities(elicitation=types.ElicitationCapability(url=types.UrlElicitationCapability())), False),
])
def test_capability_detection(caps, expected):
    assert client_supports_elicitation(_session(caps)) is expected
    assert client_supports_elicitation(None) is False


class FakeSession:
    def __init__(self, result=None, delay=0.0):
        self.client_params = SimpleNamespace(capabilities=types.ClientCapabilities(
            elicitation=types.ElicitationCapability(form=types.FormElicitationCapability())))
        self.result, self.delay, self.calls = result, delay, 0

    async def elicit_form(self, message, schema, related_request_id=None):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.result


def test_timeout_returns_none():
    session = FakeSession(types.ElicitResult(action="accept", content={"choice": "a"}), delay=1.0)
    got = asyncio.run(elicit_choice(session, "Pick", ["a", "b"], tool="snapshot_query", timeout=0.05))
    assert got is None and session.calls == 1


def test_answer_outside_the_options_returns_none():
    session = FakeSession(types.ElicitResult(action="accept", content={"choice": "c"}))
    assert asyncio.run(elicit_choice(session, "Pick", ["a", "b"], tool="snapshot_query")) is None


def test_no_capability_sends_nothing():
    session = FakeSession()
    session.client_params = SimpleNamespace(capabilities=types.ClientCapabilities())
    assert asyncio.run(elicit_choice(session, "Pick", ["a"], tool="snapshot_query")) is None
    assert session.calls == 0


# ---------------------------------------------------- never for approval


def test_every_approval_provider_tool_is_forbidden(server):
    names = {t.name for t in mcp_server.registry.get_provider("approval").get_capabilities()}
    assert names and names <= APPROVAL_TOOLS
    for name in names | {"approve_plan", "reject_plan", "rollback_plan", "some_future_plan_tool"}:
        assert not elicitation_allowed(name)
        assert not mcp_server._may_elicit(name, {})
        session = FakeSession(types.ElicitResult(action="accept", content={"choice": "yes"}))
        with pytest.raises(ElicitationForbidden):
            asyncio.run(elicit_choice(session, "Approve?", ["yes"], tool=name))
        assert session.calls == 0


def test_approval_code_cannot_call_the_helper():
    session = FakeSession(types.ElicitResult(action="accept", content={"choice": "a"}))
    for module in sorted(elicitation.FORBIDDEN_CALLER_MODULES):
        scope = {"__name__": module, "elicit_choice": elicit_choice, "session": session}
        exec("async def ask():\n    return await elicit_choice(session, 'Pick', ['a'], tool='snapshot_query')", scope)
        with pytest.raises(ElicitationForbidden):
            asyncio.run(scope["ask"]())
    assert session.calls == 0


def test_approval_sources_never_mention_elicitation():
    for module in elicitation.FORBIDDEN_CALLER_MODULES:
        path = SRC.joinpath(*module.split(".")[1:]).with_suffix(".py")
        assert path.is_file(), path
        assert "elicit" not in path.read_text(encoding="utf-8").lower(), path


def test_a_call_with_a_plan_id_never_asks(server):
    server.approval.gate.approval_mode = "auto"
    assert not mcp_server._may_elicit("revit_export", {"plan_id": "p1"})
    assert not mcp_server._may_elicit("revit_export_ifc", {"plan_id": "p1"})
    assert mcp_server._may_elicit("revit_export", {})
    assert mcp_server._may_elicit("snapshot_query", {})


@pytest.mark.parametrize("field, message", [
    ("password", "Pick"), ("api_key", "Pick"), ("choice", "Enter your access token"),
    ("choice", "What is the secret?"),
])
def test_secrets_are_never_asked_for(field, message):
    session = FakeSession(types.ElicitResult(action="accept", content={field: "x"}))
    with pytest.raises(ElicitationForbidden):
        asyncio.run(elicit_choice(session, message, None, tool="snapshot_query", field=field))
    assert session.calls == 0
