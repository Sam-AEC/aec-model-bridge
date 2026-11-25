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


def test_snapshot_compute_parameter_path_with_record_suffix(server):
    # A known parameter read through a record field asks nothing.
    steps = [{"name": "doors", "where": {"field": "params.FireRating.v", "op": "eq", "value": "30"},
              "select": ["params.FireRating.storage"]}]
    asker = Asker()
    data = _result(call("snapshot_compute", {"snapshot_id": server.snapshot_id, "steps": steps}, asker))
    assert data["row_count"] == 1 and asker.asked == []
    # An unknown name is matched on its segment only, and the suffix is kept in the correction.
    steps = [{"name": "doors", "where": {"field": "params.Fire Rating.v", "op": "eq", "value": "30"}}]
    asker = Asker(("accept", {"parameter": "FireRating"}))
    data = _result(call("snapshot_compute", {"snapshot_id": server.snapshot_id, "steps": steps}, asker))
    assert data["row_count"] == 1 and len(asker.asked) == 1
    assert "'Fire Rating'" in asker.asked[0].message


def test_parameter_path_segments():
    from revit_mcp_server.providers.semantic_provider import _param_refs, _replace_param

    paths = ["params.FireRating.v", "params.Long Name.storage", "type.params.Mark", "params.Mark"]
    assert _param_refs(paths) == ["FireRating", "Long Name", "Mark"]
    assert _replace_param(paths, "Long Name", "LongName") == [
        "params.FireRating.v", "params.LongName.storage", "type.params.Mark", "params.Mark"]
    assert _replace_param(["type.params.Mark.v"], "Mark", "Tag") == ["type.params.Tag.v"]


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
    need = missing_export_path("revit_export_ifc", {}, tmp_path)
    for bad in ("../x", "a/b", "..", "c:\\x", ".hidden"):
        with pytest.raises(InputNeeded):
            need.apply({"view_id": 5}, bad)
    assert need.apply({}, "plan.ifc")["output_path"] == str(tmp_path / "plan.ifc")


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


# ------------------------------------------------ (c) view and sheet names

VIEWS = [{"kind": "view", "id": 11, "name": "Level 1", "type": "FloorPlan"},
         {"kind": "view", "id": 12, "name": "Level 10", "type": "FloorPlan"},
         {"kind": "view", "id": 21, "name": "Section A", "type": "Section"},
         {"kind": "view", "id": 22, "name": "Section A", "type": "Detail"}]
SHEETS = [{"kind": "sheet", "id": 101, "name": "Plans", "number": "A101"},
          {"kind": "sheet", "id": 102, "name": "Sections", "number": "A102"}]


@pytest.fixture
def docs(server, monkeypatch):
    """Auto mode (no plan needed), a fake view/sheet list and a recording revit_docs provider."""
    server.approval.gate.approval_mode = "auto"
    state = SimpleNamespace(views=list(VIEWS), sheets=list(SHEETS), listed=[], executed=[])

    async def fake_list(kind, needle):
        state.listed.append((kind, needle))
        rows = state.views if kind == "view" else state.sheets
        low = needle.lower()
        hits = [r for r in rows if low in r["name"].lower() or low in r.get("number", "").lower()]
        return hits, len(hits)

    async def fake_execute(name, arguments):
        state.executed.append((name, arguments))
        return {"ok": True, "tool": name, "summary": "done"}

    monkeypatch.setattr(mcp_server, "_list_views_or_sheets", fake_list)
    provider = mcp_server.registry.lookup_tool_provider("revit_place_views")
    monkeypatch.setattr(provider, "execute_tool", fake_execute)
    return state


def test_ambiguous_view_name_is_asked_and_the_answer_sets_view_id(docs):
    asker = Asker(("accept", {"view": "Level 1"}))
    answer = call("revit_place_views", {"sheet": "A101", "views": [{"view_name": "level 1"}]}, asker)
    assert not answer.isError, answer.content[0].text
    (question,) = asker.asked
    assert question.requestedSchema["properties"]["view"]["enum"] == ["Level 1", "Level 10"]
    assert "views[0].view_name" in question.message
    ((name, arguments),) = docs.executed
    assert name == "revit_place_views"
    assert arguments["views"] == [{"view_id": 11}] and arguments["sheet"] == "A101"


def test_ambiguous_view_name_without_capability_is_the_plain_refusal(docs):
    message = _refusal(call("revit_make_view_template", {"view": {"view_name": "level"}, "name": "T"}))
    assert "'Level 1'" in message and "'Level 10'" in message and "view.view_name" in message
    assert "view_id" in message
    assert docs.executed == []


def test_two_views_with_the_exact_name_are_labelled_by_id(docs):
    asker = Asker(("accept", {"view": "Section A [id 22]"}))
    answer = call("revit_add_revision_clouds", {"revision_id": 5, "view": {"view_name": "Section A"},
                                                "element_ids": [1]}, asker)
    assert not answer.isError, answer.content[0].text
    enum = asker.asked[0].requestedSchema["properties"]["view"]["enum"]
    assert enum == ["Section A [id 21]", "Section A [id 22]"]
    assert "matches several views" in asker.asked[0].message
    assert docs.executed[0][1]["view"] == {"view_id": 22}


def test_exact_view_and_sheet_need_no_question(docs):
    asker = Asker()
    answer = call("revit_place_views", {"sheet": "A101", "views": [{"view_name": "Level 10"}]}, asker)
    assert not answer.isError, answer.content[0].text
    assert asker.asked == []
    assert docs.executed[0][1]["views"] == [{"view_name": "Level 10"}]


def test_sheet_number_matched_by_name_or_case_is_asked(docs):
    asker = Asker(("accept", {"sheet": "A102 - Sections"}))
    answer = call("revit_issue_revision", {"revision_id": 5, "sheets": ["A101", "sections"]}, asker)
    assert not answer.isError, answer.content[0].text
    (question,) = asker.asked
    assert question.requestedSchema["properties"]["sheet"]["enum"] == ["A102 - Sections"]
    assert "sheets[1]" in question.message
    assert docs.executed[0][1]["sheets"] == ["A101", "A102"]


def test_nested_sheet_number_in_a_table(docs):
    asker = Asker(("accept", {"sheet": "A101 - Plans"}))
    answer = call("revit_update_sheets", {"sheets": [{"number": "a101", "new_name": "Ground"}]}, asker)
    assert not answer.isError, answer.content[0].text
    assert docs.executed[0][1]["sheets"] == [{"number": "A101", "new_name": "Ground"}]


def test_a_misspelt_name_offers_close_names_from_the_full_list(docs):
    asker = Asker(("accept", {"view": "Level 1"}))
    answer = call("revit_set_view_templates", {"template_id": 3, "views": [{"view_name": "Levl 1"}]}, asker)
    assert not answer.isError, answer.content[0].text
    assert docs.listed == [("view", "Levl 1"), ("view", "")]
    assert "Level 1" in asker.asked[0].requestedSchema["properties"]["view"]["enum"]


def test_no_close_name_keeps_the_old_behaviour(docs):
    asker = Asker()
    answer = call("revit_make_view_template", {"view": {"view_name": "Roof terrace"}, "name": "T"}, asker)
    assert not answer.isError, answer.content[0].text
    assert asker.asked == []
    assert docs.executed[0][1]["view"] == {"view_name": "Roof terrace"}


def test_more_than_25_candidates_are_capped_and_counted(docs):
    docs.views = [{"kind": "view", "id": 100 + i, "name": f"View {i}", "type": "FloorPlan"} for i in range(30)]
    asker = Asker(("decline", None))
    message = _refusal(call("revit_make_view_template", {"view": {"view_name": "view"}, "name": "T"}, asker))
    (question,) = asker.asked
    assert len(question.requestedSchema["properties"]["view"]["enum"]) == elicitation.MAX_OPTIONS
    assert "+5 more" in question.message and "+5 more" in message


def test_at_most_three_questions_per_call(docs):
    asker = Asker(*[("accept", {"view": "Level 1"})] * 3)
    views = [{"view_name": "level"} for _ in range(4)]
    message = _refusal(call("revit_set_view_templates", {"template_id": 3, "views": views}, asker))
    assert len(asker.asked) == elicitation.MAX_ROUNDS
    assert "views[3].view_name" in message
    assert docs.executed == []


def test_view_names_are_never_checked_when_a_plan_is_needed(docs):
    args = {"sheet": "a101", "views": [{"view_name": "level"}]}
    mcp_server.approval_provider.gate.approval_mode = "ask_first"
    asker = Asker(("accept", {"view": "Level 1"}))
    answer = call("revit_place_views", args, asker)
    assert answer.isError and "Approval Gate Blocked" in answer.content[0].text
    assert asker.asked == [] and docs.listed == [] and docs.executed == []
    # A call with a plan_id keeps its approved arguments, in any mode.
    mcp_server.approval_provider.gate.approval_mode = "auto"
    assert not mcp_server._may_elicit("revit_place_views", {**args, "plan_id": "plan_000000000001"})


def test_the_name_check_does_nothing_in_mock_mode(server):
    # The real list tool answers "mock" with no rows, so nothing is asked or refused.
    assert asyncio.run(mcp_server._list_views_or_sheets("view", "level")) is None


def test_name_paths_and_answers_on_nested_arguments():
    args = {"reference": {"view_name": "A"}, "views": [{"view_id": 4}, {"view_name": " B "}], "sheets": ["X", 3, ""]}
    assert elicitation._name_refs(args, "reference.view_name") == [("reference.view_name", "A")]
    assert elicitation._name_refs(args, "views[].view_name") == [("views[1].view_name", "B")]
    assert elicitation._name_refs(args, "sheets[]") == [("sheets[0]", "X")]
    assert elicitation._name_refs(args, "sheet.number") == []
    need = elicitation.ambiguous_view_or_sheet(
        "revit_align_crop", "views[1].view_name", "view", "B", [{"id": 7, "name": "B1"}, {"id": 8, "name": "B2"}])
    new = need.apply(args, "B2")
    assert new["views"][1] == {"view_id": 8} and args["views"][1] == {"view_name": " B "}
    assert elicitation.ambiguous_view_or_sheet("t", "sheet", "sheet", "A1", [{"id": 1, "number": "A1"}]) is None


def test_every_view_sheet_tool_takes_the_listed_path(server):
    for tool, refs in elicitation.VIEW_SHEET_REFS.items():
        schema = mcp_server.registry.lookup_tool(tool).input_schema
        for path, _kind in refs:
            node = schema
            for part in path.split("."):
                key = part[:-2] if part.endswith("[]") else part
                node = node["properties"][key]
                if part.endswith("[]"):
                    node = node["items"]
            assert node.get("type") == "string", (tool, path)


def test_view_sheet_check_skips_a_truncated_list_without_an_exact_match():
    """#331 review: with more rows than the list returned and no exact match among them, the exact
    reference may exist beyond the page, so the check neither asks nor refuses."""
    import asyncio

    from revit_mcp_server.elicitation import VIEW_SHEET_REFS, check_view_sheet_names

    tool, (path, kind) = next((t, refs[0]) for t, refs in VIEW_SHEET_REFS.items() if refs[0][1] == "sheet")
    calls = []

    async def lister(k, needle):
        calls.append(needle)
        rows = [{"id": i, "number": f"A101.{i}", "name": f"S{i}", "kind": "sheet"} for i in range(500)]
        return rows, 900

    args = {}
    container = args
    parts = path.replace("[]", "").split(".")
    for part in parts[:-1]:
        container[part] = [{}] if path.split(part, 1)[1].startswith("[]") else {}
        container = container[part][0] if isinstance(container[part], list) else container[part]
    container[parts[-1]] = "A101"
    assert asyncio.run(check_view_sheet_names(tool, args, lister)) is None
    assert calls == ["A101"], "no fallback listing either"
