"""The agent eval suite in evals/: task files are valid and the scorer grades the golden transcripts.

No model is called. Golden transcripts are replayed through the mock server
(the real call_tool path and approval gate) and scored.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "evals"


def _load_run_eval():
    spec = importlib.util.spec_from_file_location("agent_eval_run", EVALS / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


ev = _load_run_eval()


@pytest.fixture(scope="module")
def tasks():
    return ev.load_tasks()


@pytest.fixture(scope="module")
def index():
    return ev.load_tool_index()


@pytest.fixture(scope="module")
def golden(tasks, index):
    return ev.run_golden(tasks, index)


def test_thirty_tasks_of_every_kind(tasks):
    assert len(tasks) == 30
    kinds = {t.kind for t in tasks}
    assert kinds == {"read", "write", "discovery"}
    assert sum(t.plan_required for t in tasks) >= 5
    assert any(t.profile == "core" for t in tasks)


def test_task_tools_exist_and_one_option_is_visible_in_the_task_profile(tasks, index):
    problems = [p for task in tasks for p in ev.check_task_tools(task, index)]
    assert problems == []
    for task in tasks:
        visibility = ev.profile_visibility(task, index)
        assert all(profiles for profiles in visibility.values()), task.id


def test_write_tasks_name_a_write_tool_and_reads_name_none(tasks, index):
    for task in tasks:
        writes = {t for option in task.expected_tools for t in option if index[t].mutating}
        assert bool(writes) == task.plan_required, task.id


def test_every_task_forbids_python_and_has_a_good_transcript(tasks):
    for task in tasks:
        assert "revit_execute_python" in task.forbidden_tools, task.id
        assert (ev.TRANSCRIPTS_DIR / task.id / "good.jsonl").is_file(), task.id


def test_golden_transcripts_meet_their_expectations(golden):
    results, problems = golden
    assert problems == []
    good = [r for r in results if Path(r.transcript_path).name == "good.jsonl"]
    bad = [r for r in results if Path(r.transcript_path).name.startswith("bad-")]
    assert len(good) == 30 and all(r.passed and r.score == 100.0 for r in good)
    assert all(r.failed_calls == 0 for r in good), [r.transcript_path for r in good if r.failed_calls]
    assert len(bad) >= 8 and not any(r.passed for r in bad)
    failed = {name for r in bad for name, check in r.checks.items() if check.passed is False}
    assert failed == set(ev.WEIGHTS)  # the bad set exercises every check


def test_every_golden_file_has_an_expectation(tasks):
    for task in tasks:
        for path in ev.golden_files(task):
            meta = ev.load_transcript(path).meta
            assert isinstance(meta.get("expect"), dict) and "passed" in meta["expect"], path


def test_good_transcripts_also_pass_without_replay(tasks, index):
    results = ev.run_replay(tasks, ev.TRANSCRIPTS_DIR, index, replay_calls=False, skip_missing=False)
    assert all(r.passed for r in results)


def _task(**overrides):
    data = {"id": "t", "prompt": "How many doors?", "kind": "read", "expected_tools": [["snapshot_take"]],
            "max_calls": 2, "plan_required": False, "checker": {"type": "number", "value": 1}}
    data.update(overrides)
    return data


@pytest.mark.parametrize("overrides, message", [
    ({"kind": "write"}, "plan_required must be true for write tasks"),
    ({"max_calls": 0}, "max_calls"),
    ({"checker": {"type": "guess"}}, "checker type"),
    ({"checker": {"type": "none"}}, "needs a reason"),
    ({"checker": {"type": "number"}}, "exactly one of"),
    ({"expected_tools": []}, "expected_tools"),
    ({"extra": 1}, "unknown keys"),
    ({"profile": "tiny"}, "profile"),
])
def test_invalid_tasks_are_refused(overrides, message):
    with pytest.raises(ev.EvalError, match=message):
        ev.parse_task(_task(**overrides), "t.yaml")


def test_unknown_tool_and_hidden_profile_are_reported(index):
    task = ev.parse_task(_task(expected_tools=[["no_such_tool"]]), "t.yaml")
    assert "not in the registry" in ev.check_task_tools(task, index)[0]
    task = ev.parse_task(_task(profile="core", expected_tools=[["revit_mep_route"]]), "t.yaml")
    assert "no expected tool set is fully visible in profile 'core'" in ev.check_task_tools(task, index)[0]


@pytest.mark.parametrize("text, message", [
    ('{"tool": "a"}\n', "exactly one answer"),
    ('{"answer": "x"}\n{"tool": "a"}\n', "no tool call may follow"),
    ('{"answer": "x"}\n{"answer": "y"}\n', "exactly one answer"),
    ('{"tool": "a", "arguments": []}\n{"answer": "x"}\n', "arguments must be an object"),
    ('not json\n', "not JSON"),
    ('{"other": 1}\n{"answer": "x"}\n', "needs one of"),
])
def test_invalid_transcripts_are_refused(text, message):
    with pytest.raises(ev.EvalError, match=message):
        ev.parse_transcript(text)


def test_number_checker():
    zero = {"type": "number", "value": 0}
    assert ev.run_checker(zero, "None of them.")[0]
    assert ev.run_checker(zero, "0 doors")[0]
    assert not ev.run_checker(zero, "3 doors")[0]
    area = {"type": "number", "value": 15.5}
    assert ev.run_checker(area, "15.5 m2")[0]
    assert not ev.run_checker(area, "115.5 m2")[0]
    assert not ev.run_checker(area, "15.55 m2")[0]
    assert ev.run_checker({"type": "number", "mock_count": {"category": "OST_Rooms"}}, "2 rooms")[0]
    assert ev.run_checker({"type": "contains_all", "values": ["A", "b"]}, "a and B")[0]
    assert ev.run_checker({"type": "none", "reason": "r"}, "anything")[0] is None
    with pytest.raises(ev.EvalError, match="Unknown mock filter"):
        ev.mock_elements({"colour": "red"})


def test_host_never_approves_and_keeps_the_gate(tmp_path):
    from revit_mcp_server import mcp_server

    before = (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager)
    host = ev.ToolHost("full")
    write = host.call("revit_set_parameters", {"items": [{"id": 300, "params": {"Mark": "X"}}]})
    assert write.status == "error" and "plan_id" in write.result
    assert host.call("approve_plan", {"plan_id": "plan_0123456789ab"}).status == "error"
    plan = host.call("plan_actions", {"actions": [{"tool": "revit_delete_element", "arguments": {"element_id": 400}}]})
    assert plan.status == "ok"
    assert host.call("execute_plan", {"plan_id": "plan_0123456789ab"}).status == "awaits_approval"
    assert host.call("revit_delete_element", {"element_id": 400, "plan_id": "plan_0123456789ab"}).status == "awaits_approval"
    assert (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager) == before
    core = ev.ToolHost("core")
    assert core.call("model_inspector_ask", {"filter": {"category": "OST_Doors"}}).status == "error"
    assert "search_tools" in {tool["name"] for tool in core.list_tools()}


def test_host_dispatches_a_read_that_carries_a_plan_id():
    host = ev.ToolHost("full")
    read = host.call("snapshot_take", {"plan_id": "plan_0123456789ab"})
    assert read.status != "awaits_approval"
    assert host.call("revit_delete_element", {"element_id": 400, "plan_id": "plan_0123456789ab"}).status == "awaits_approval"
    task = ev.Task(id="t", prompt="p", kind="read", profile="full", expected_tools=[["snapshot_take"]],
                   max_calls=3, plan_required=False, forbidden_tools=[], checker=[{"type": "none", "reason": "r"}])
    # A read that is not a write is scored from what the server returned, not as a held write.
    bad = host.call("snapshot_query", {"snapshot_id": "nope", "plan_id": "plan_0123456789ab"})
    assert bad.status == "error"
    result = ev.score_transcript(task, ev.Transcript(calls=[bad], answer="x"), ev.load_tool_index(),
                                 ev.human_only_tools())
    assert result.failed_calls == 1


def test_execute_must_name_a_successfully_drafted_plan(tasks, index):
    """Both modes: executing another plan, or a failed execute, does not satisfy the plan check."""
    picked = [t for t in tasks if t.id in ("delete-unplaced-room", "add-revision")]
    for replay_calls in (True, False):
        results, problems = ev.run_golden(picked, index, replay_calls=replay_calls)
        assert problems == [], (replay_calls, problems)
        bad = {Path(r.transcript_path).name: r for r in results if Path(r.transcript_path).name.startswith("bad-")}
        assert "no earlier successful plan_actions" in bad["bad-executes-other-plan.jsonl"].checks["plan"].detail
        assert bad["bad-failed-execute.jsonl"].checks["plan"].detail == "execute_plan failed"
    task = next(t for t in tasks if t.id == "add-revision")
    draft = {"tool": "plan_actions", "arguments": {"actions": [{"tool": "revit_add_revision", "arguments": {}}]}}
    answer = {"answer": "You approved the plan."}

    def plan_check(*rows):
        text = "\n".join(json.dumps(r) for r in rows)
        return ev.score_transcript(task, ev.parse_transcript(text), index, ev.human_only_tools()).checks["plan"]

    execute = {"tool": "execute_plan", "arguments": {"plan_id": "plan_0123456789ab"}}
    approved = {"event": "human_approved", "plan_id": "plan_0123456789ab"}
    assert plan_check(draft, approved, execute, answer).passed
    assert not plan_check(draft, execute, answer).passed  # the draft's plan id is not known
    assert not plan_check({**draft, "status": "error"}, approved, execute, answer).passed  # failed draft
    assert plan_check({**draft, "plan_id": "plan_0123456789ab"}, execute, answer).passed
    recorded = ev.parse_transcript("\n".join(json.dumps(r) for r in (draft, approved, execute, answer)))
    assert '"plan_id": "plan_0123456789ab"}' in recorded.to_jsonl().splitlines()[0]  # kept for re-scoring


def test_live_mode_records_and_scores(tasks, index, tmp_path):
    task = next(t for t in tasks if t.id == "count-doors")

    class Adapter:
        name = "test"

        def run_task(self, task, host):
            host.call("model_inspector_summarize_model", {})
            return "There is 1 door."

    results = ev.run_live([task], Adapter(), index, tmp_path)
    assert results[0].passed
    recorded = ev.load_transcript(tmp_path / "count-doors.jsonl")
    assert [c.tool for c in recorded.calls] == ["model_inspector_summarize_model"]
    assert recorded.meta == {"adapter": "test"}


def test_stub_adapter_and_adapter_loading(tmp_path, capsys):
    assert ev.main(["--live", "--task", "count-doors"]) == 2
    assert "No agent adapter is configured" in capsys.readouterr().err
    path = tmp_path / "my_adapter.py"
    path.write_text("class A:\n    name = 'a'\n    def run_task(self, task, host):\n        return 'x'\n", encoding="utf-8")
    assert ev.load_adapter(f"{path}:A").name == "a"
    with pytest.raises(ev.EvalError):
        ev.load_adapter("no_colon")


def test_cli_reports(tmp_path):
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    assert ev.main(["--report-json", str(out_json), "--report-md", str(out_md), "--fail-under", "100"]) == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["schema"] == "amb.agent-eval/1"
    overall = report["overall"]
    assert (overall["tasks"], overall["passed"], overall["score"]) == (30, 30, 100.0)
    assert overall["by_check"]["tools"] == 30 and overall["by_check"]["plan"] == 30
    first = report["tasks"][0]
    assert {"checks", "profile_visibility", "call_log", "calls", "max_calls"} <= set(first)
    text = out_md.read_text(encoding="utf-8")
    assert text.startswith("# Agent eval report") and "| Task | Transcript | Score |" in text
    empty = tmp_path / "none"
    empty.mkdir()
    assert ev.main(["--transcripts", str(empty), "--fail-under", "1"]) == 1
    assert ev.main(["--golden", "--task", "count-doors"]) == 0
    assert ev.main(["--task", "no-such-task"]) == 2


def _schemas():
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    import tempfile
    registry, *_ = build_registry(WorkspaceMonitor([Path(tempfile.mkdtemp(prefix="agent-evals-schema-"))]))
    return {t.name: t.input_schema or {} for p in registry.get_all_providers() for t in p.get_capabilities()}


def test_golden_calls_use_only_argument_keys_in_the_tool_schema(tasks):
    """Recorded good calls, and actions drafted in plan_actions, name only keys the tool declares."""
    schemas = _schemas()
    problems = []

    def check(tool, arguments, where):
        schema = schemas.get(tool)
        if schema is None:
            problems.append(f"{where}: unknown tool {tool}")
            return
        props = schema.get("properties")
        if props is None or schema.get("additionalProperties") is True:
            return
        extra = set(arguments) - set(props) - {"plan_id"}
        if extra:
            problems.append(f"{where}: {tool} has unknown argument keys {sorted(extra)}")

    for task in tasks:
        path = ev.TRANSCRIPTS_DIR / task.id / "good.jsonl"
        for call in ev.load_transcript(path).calls:
            check(call.tool, call.arguments, task.id)
            if call.tool == "plan_actions":
                for action in call.arguments.get("actions", []):
                    check(action["tool"], action.get("arguments", {}), f"{task.id} (planned)")
    assert problems == []
