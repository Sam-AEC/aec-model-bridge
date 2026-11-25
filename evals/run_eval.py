#!/usr/bin/env python
"""Score how well an AI agent picks AEC Model Bridge tools, without calling a model.

Each task in evals/tasks/*.yaml is a request a person might type. A transcript is
the list of tool calls an agent made for it (JSONL) plus its final answer. The
scorer checks five things per task: the right tools, the number of calls, the
plan flow for writes, forbidden tools, and the final answer where the mock data
makes it deterministic.

Modes:
  replay (default)  Replay recorded transcripts through the mock server
                    (MCP_REVIT_MODE=mock, the real call_tool path and approval
                    gate) and score them. No model is called. This is the CI mode.
  --golden          Replay every golden transcript in evals/transcripts/<task>/
                    and check it meets the expectation in its meta line.
  --no-replay       Score the transcripts as recorded, without the mock server.
  --live            Drive an agent through an adapter (see AgentAdapter). Opt-in,
                    never run in CI. The repository ships only a stub adapter.

Run from the repository root:
  uv run --project packages/mcp-server-revit python evals/run_eval.py --report-md evals/out/report.md

See docs/agent-evals.md.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

import yaml

EVALS_DIR = Path(__file__).resolve().parent
ROOT = EVALS_DIR.parent
TASKS_DIR = EVALS_DIR / "tasks"
TRANSCRIPTS_DIR = EVALS_DIR / "transcripts"
SRC = ROOT / "packages" / "mcp-server-revit" / "src"

PROFILES = ("full", "daily", "core")
TASK_KINDS = ("read", "write", "discovery")
CHECKER_TYPES = ("number", "contains_all", "contains_any", "none")
# Check weights for the 0-100 task score. A check that does not apply is left out
# and the other weights are scaled up.
WEIGHTS = {"tools": 30, "plan": 20, "forbidden": 20, "calls": 15, "answer": 15}
# Keys a task file may have.
TASK_KEYS = {"id", "prompt", "kind", "profile", "expected_tools", "max_calls",
             "plan_required", "forbidden_tools", "checker", "notes"}
# Arguments that carry an id produced by an earlier call in the same session.
SESSION_ID_KEYS = ("snapshot_id", "plan_id")
SESSION_ID_PRODUCERS = {"snapshot_id": ("snapshot_take", "revit_extract_snapshot"),
                        "plan_id": ("plan_actions",)}
EXECUTE_TOOLS = ("execute_plan",)
PLAN_TOOL = "plan_actions"


class EvalError(ValueError):
    """A task file, transcript or argument is invalid."""


# --------------------------------------------------------------------------- server

def _prepare_environment() -> None:
    """Point the server at mock mode and a temporary workspace before it is imported."""
    if "revit_mcp_server" in sys.modules:
        return  # already configured by the caller (for example pytest's conftest)
    workspace = tempfile.mkdtemp(prefix="agent-evals-")
    os.environ["MCP_REVIT_MODE"] = "mock"
    os.environ.setdefault("MCP_REVIT_WORKSPACE_DIR", workspace)
    os.environ.setdefault("MCP_REVIT_ALLOWED_DIRECTORIES", os.environ["MCP_REVIT_WORKSPACE_DIR"])
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))


@dataclass(frozen=True)
class ToolInfo:
    name: str
    provider: str
    module_id: str | None
    mutating: bool
    profiles: tuple[str, ...]


def load_tool_index() -> dict[str, ToolInfo]:
    """Every registered tool, whether it writes, and which built-in profiles show it."""
    _prepare_environment()
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor
    from revit_mcp_server.tool_profiles import load_tool_profile

    workspace = Path(tempfile.mkdtemp(prefix="agent-evals-index-"))
    registry, *_ = build_registry(WorkspaceMonitor([workspace]))
    profiles = {name: load_tool_profile({"MCP_REVIT_TOOL_PROFILE": name}) for name in PROFILES}
    index: dict[str, ToolInfo] = {}
    for provider in registry.get_all_providers():
        pid = provider.get_identity()
        for tool in provider.get_capabilities():
            shown = tuple(name for name, profile in profiles.items()
                          if profile.allows(pid, tool.module_id, tool.name))
            index[tool.name] = ToolInfo(tool.name, pid, tool.module_id, bool(tool.is_mutating), shown)
    return index


def human_only_tools() -> frozenset[str]:
    _prepare_environment()
    from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS

    return frozenset(HUMAN_ONLY_TOOLS)


@dataclass
class Call:
    tool: str
    arguments: dict[str, Any]
    status: str = "ok"  # ok, error, awaits_approval
    result: str = ""


@dataclass
class Transcript:
    calls: list[Call] = field(default_factory=list)
    answer: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    replayed: bool = False

    def to_jsonl(self) -> str:
        lines = []
        if self.meta:
            lines.append(json.dumps({"meta": self.meta}, ensure_ascii=False))
        for call in self.calls:
            row: dict[str, Any] = {"tool": call.tool, "arguments": call.arguments}
            if call.status != "ok":
                row["status"] = call.status
            lines.append(json.dumps(row, ensure_ascii=False))
        lines.append(json.dumps({"answer": self.answer}, ensure_ascii=False))
        return "\n".join(lines) + "\n"


class ToolHost:
    """The mock server as an agent sees it: list tools, call a tool.

    Calls go through ``mcp_server.call_tool``, so the approval gate, profile and
    human-only refusals behave as in a real session. The host never approves a
    plan: ``execute_plan`` and any call that carries a ``plan_id`` are recorded
    with status ``awaits_approval`` and not dispatched. Every call is recorded.
    """

    def __init__(self, profile: str = "full", substitute_session_ids: bool = False) -> None:
        if profile not in PROFILES:
            raise EvalError(f"Unknown profile '{profile}'. Use one of: {', '.join(PROFILES)}.")
        _prepare_environment()
        from revit_mcp_server.config import BridgeMode, config

        if config.mode != BridgeMode.mock:
            raise EvalError("The eval host runs only against the mock server (MCP_REVIT_MODE=mock).")
        from revit_mcp_server.registry_factory import build_registry
        from revit_mcp_server.security.workspace import WorkspaceMonitor
        from revit_mcp_server.tool_profiles import load_tool_profile

        self.profile = profile
        self.workspace = Path(tempfile.mkdtemp(prefix="agent-evals-host-"))
        registry, approval, jobs, _modules, _ws = build_registry(WorkspaceMonitor([self.workspace]))
        registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": profile}))
        # Tasks are written for ask-first mode: every write needs an approved plan.
        approval.gate.approval_mode = "ask_first"
        if approval.gate.approval_mode != "ask_first":
            raise EvalError("The eval host could not put its approval gate in ask-first mode.")
        self._state = (registry, approval, jobs)
        self.substitute_session_ids = substitute_session_ids
        self._human_only = human_only_tools()  # always sent, so call_tool refuses them as in a real session
        self.calls: list[Call] = []
        self._produced: dict[str, list[str]] = {key: [] for key in SESSION_ID_KEYS}

    def reset(self) -> None:
        self.calls = []
        self._produced = {key: [] for key in SESSION_ID_KEYS}

    @contextlib.contextmanager
    def _server(self):
        from revit_mcp_server import mcp_server

        saved = (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager)
        mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = self._state
        try:
            yield mcp_server
        finally:
            mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = saved

    def list_tools(self) -> list[dict[str, Any]]:
        """The tools/list reply for this profile, as plain dicts (name, description, inputSchema)."""
        with self._server() as server:
            tools = asyncio.run(server.list_tools())
        return [tool.model_dump(exclude_none=True) for tool in tools]

    def _substitute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # A recorded transcript names ids from the session it was recorded in. Swap an id
        # this replay has not produced for the latest one it has, so later calls still work.
        out = dict(arguments)
        for key in SESSION_ID_KEYS:
            value = out.get(key)
            produced = self._produced[key]
            if isinstance(value, str) and produced and value not in produced:
                out[key] = produced[-1]
        return out

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> Call:
        arguments = dict(arguments or {})
        sent = self._substitute(arguments) if self.substitute_session_ids else arguments
        if tool not in self._human_only and (tool in EXECUTE_TOOLS or "plan_id" in sent):
            call = Call(tool, arguments, "awaits_approval",
                        "Not run: the eval host never approves plans. The plan flow is scored from the transcript.")
            self.calls.append(call)
            return call
        with self._server() as server:
            reply = asyncio.run(server.call_tool(tool, sent))
        if isinstance(reply, list):
            status, text = "ok", "\n".join(getattr(part, "text", "") for part in reply)
        else:
            status = "error" if reply.isError else "ok"
            text = "\n".join(getattr(part, "text", "") for part in reply.content)
        for key, producers in SESSION_ID_PRODUCERS.items():
            if status == "ok" and tool in producers:
                match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text)
                if match:
                    self._produced[key].append(match.group(1))
        call = Call(tool, arguments, status, text)
        self.calls.append(call)
        return call


# --------------------------------------------------------------------------- adapters

class AgentAdapter(Protocol):
    """Plug a real agent into --live mode.

    ``run_task`` gets the task (use ``task.prompt`` as the user message) and a
    ToolHost. Offer the model ``host.list_tools()``, send each tool call the model
    makes to ``host.call(name, arguments)`` and hand the model the returned
    ``Call.result``. Return the model's final answer as text. The host records
    every call; the harness scores the record.
    """

    name: str

    def run_task(self, task: "Task", host: ToolHost) -> str: ...


class StubAdapter:
    """The default --live adapter. It calls no model and explains how to add one."""

    name = "stub"

    def run_task(self, task: "Task", host: ToolHost) -> str:
        raise NotImplementedError(
            "No agent adapter is configured. Write a class with a run_task(task, host) method that "
            "drives your MCP client or model API, and pass it with --adapter path/to/file.py:ClassName. "
            "See docs/agent-evals.md."
        )


class ScriptedAdapter:
    """Replays a recorded transcript through the host. Used by replay mode and the tests."""

    name = "scripted"

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript

    def run_task(self, task: "Task", host: ToolHost) -> str:
        for call in self.transcript.calls:
            host.call(call.tool, call.arguments)
        return self.transcript.answer


def load_adapter(spec: str) -> AgentAdapter:
    """Load ``module:Class`` or ``path/to/file.py:Class`` and instantiate it with no arguments."""
    target, _, attr = spec.rpartition(":")
    if not target or not attr:
        raise EvalError("--adapter needs module:ClassName or path/to/file.py:ClassName.")
    if target.endswith(".py"):
        module_spec = importlib.util.spec_from_file_location("eval_adapter", target)
        if module_spec is None or module_spec.loader is None:
            raise EvalError(f"Cannot load adapter file {target}.")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    adapter = getattr(module, attr)()
    if not callable(getattr(adapter, "run_task", None)):
        raise EvalError(f"{spec} has no run_task(task, host) method.")
    return adapter


# --------------------------------------------------------------------------- tasks

@dataclass
class Task:
    id: str
    prompt: str
    kind: str
    profile: str
    expected_tools: list[list[str]]
    max_calls: int
    plan_required: bool
    forbidden_tools: list[str]
    checker: list[dict[str, Any]]
    notes: str = ""
    path: Path | None = None


def _require(condition: bool, where: str, message: str) -> None:
    if not condition:
        raise EvalError(f"{where}: {message}")


def _validate_checker(checker: Any, where: str) -> None:
    _require(isinstance(checker, dict), where, "each checker must be a mapping")
    kind = checker.get("type")
    _require(kind in CHECKER_TYPES, where, f"checker type must be one of {', '.join(CHECKER_TYPES)}")
    if kind == "number":
        sources = [key for key in ("value", "mock_count", "mock_sum") if key in checker]
        _require(len(sources) == 1, where, "a number checker needs exactly one of value, mock_count, mock_sum")
        if "mock_sum" in checker:
            _require(isinstance(checker["mock_sum"], dict) and "parameter" in checker["mock_sum"],
                     where, "mock_sum needs a parameter")
    elif kind in ("contains_all", "contains_any"):
        values = checker.get("values")
        _require(isinstance(values, list) and values and all(isinstance(v, str) and v for v in values),
                 where, f"{kind} needs a non-empty list of strings in 'values'")
    else:
        _require(isinstance(checker.get("reason"), str) and checker["reason"].strip(),
                 where, "a 'none' checker needs a reason (why the answer is not deterministic)")


def parse_task(data: Any, where: str) -> Task:
    _require(isinstance(data, dict), where, "a task file must be a mapping")
    unknown = set(data) - TASK_KEYS
    _require(not unknown, where, f"unknown keys: {', '.join(sorted(unknown))}")
    for key in ("id", "prompt", "kind", "expected_tools", "max_calls", "plan_required", "checker"):
        _require(key in data, where, f"missing '{key}'")
    _require(isinstance(data["id"], str) and re.fullmatch(r"[a-z0-9][a-z0-9-]*", data["id"]) is not None,
             where, "id must be lower-case words joined by hyphens")
    _require(isinstance(data["prompt"], str) and data["prompt"].strip(), where, "prompt must be text")
    _require(data["kind"] in TASK_KINDS, where, f"kind must be one of {', '.join(TASK_KINDS)}")
    profile = data.get("profile", "full")
    _require(profile in PROFILES, where, f"profile must be one of {', '.join(PROFILES)}")
    expected = data["expected_tools"]
    _require(isinstance(expected, list) and expected, where, "expected_tools must be a non-empty list of tool sets")
    for option in expected:
        _require(isinstance(option, list) and option and all(isinstance(t, str) for t in option),
                 where, "each entry of expected_tools must be a non-empty list of tool names")
    _require(isinstance(data["max_calls"], int) and not isinstance(data["max_calls"], bool)
             and data["max_calls"] >= 1, where, "max_calls must be a positive integer")
    _require(isinstance(data["plan_required"], bool), where, "plan_required must be true or false")
    _require(data["plan_required"] == (data["kind"] == "write"), where,
             "plan_required must be true for write tasks and false otherwise (tasks run in ask-first mode)")
    forbidden = data.get("forbidden_tools", [])
    _require(isinstance(forbidden, list) and all(isinstance(t, str) for t in forbidden),
             where, "forbidden_tools must be a list of tool names")
    checkers = data["checker"] if isinstance(data["checker"], list) else [data["checker"]]
    _require(bool(checkers), where, "checker must not be empty")
    for checker in checkers:
        _validate_checker(checker, where)
    return Task(id=data["id"], prompt=data["prompt"].strip(), kind=data["kind"], profile=profile,
                expected_tools=[list(option) for option in expected], max_calls=data["max_calls"],
                plan_required=data["plan_required"], forbidden_tools=list(forbidden),
                checker=checkers, notes=str(data.get("notes", "")).strip())


def load_tasks(directory: Path = TASKS_DIR) -> list[Task]:
    tasks = []
    for path in sorted(directory.glob("*.yaml")):
        task = parse_task(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)
        _require(path.stem == task.id, path.name, f"file name must be {task.id}.yaml")
        task.path = path
        tasks.append(task)
    ids = [task.id for task in tasks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise EvalError(f"Duplicate task ids: {', '.join(duplicates)}")
    return tasks


def check_task_tools(task: Task, index: dict[str, ToolInfo]) -> list[str]:
    """Problems with the tool names in a task: unknown names, or no option visible in its profile."""
    problems = []
    names = {t for option in task.expected_tools for t in option} | set(task.forbidden_tools)
    for name in sorted(names):
        if name not in index:
            problems.append(f"{task.id}: tool '{name}' is not in the registry")
    if problems:
        return problems
    visible = [option for option in task.expected_tools
               if all(task.profile in index[t].profiles for t in option)]
    if not visible:
        problems.append(f"{task.id}: no expected tool set is fully visible in profile '{task.profile}'")
    if task.plan_required:
        writes = [t for option in task.expected_tools for t in option if index[t].mutating]
        if not writes:
            problems.append(f"{task.id}: a write task needs at least one write tool in expected_tools")
    return problems


def profile_visibility(task: Task, index: dict[str, ToolInfo]) -> dict[str, list[str]]:
    names = sorted({t for option in task.expected_tools for t in option})
    return {name: list(index[name].profiles) if name in index else [] for name in names}


# --------------------------------------------------------------------------- transcripts

def parse_transcript(text: str, where: str = "transcript") -> Transcript:
    transcript = Transcript()
    answers = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        at = f"{where}:{number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(f"{at}: not JSON ({exc.msg})") from exc
        _require(isinstance(row, dict), at, "each line must be a JSON object")
        if "meta" in row:
            _require(number == 1 or not (transcript.calls or answers), at, "meta must be the first line")
            _require(isinstance(row["meta"], dict), at, "meta must be an object")
            transcript.meta = row["meta"]
        elif "tool" in row:
            _require(answers == 0, at, "no tool call may follow the answer")
            _require(isinstance(row["tool"], str) and row["tool"], at, "tool must be a name")
            arguments = row.get("arguments", {})
            _require(isinstance(arguments, dict), at, "arguments must be an object")
            status = row.get("status", "error" if row.get("error") else "ok")
            _require(status in ("ok", "error", "awaits_approval"), at, "status must be ok, error or awaits_approval")
            transcript.calls.append(Call(row["tool"], arguments, status))
        elif "answer" in row:
            _require(isinstance(row["answer"], str), at, "answer must be text")
            answers += 1
            transcript.answer = row["answer"]
        elif "event" in row:
            continue  # notes such as {"event": "human_approved"}; not scored
        else:
            raise EvalError(f"{at}: a line needs one of meta, tool, answer or event")
    _require(answers == 1, where, "a transcript needs exactly one answer line")
    return transcript


def load_transcript(path: Path) -> Transcript:
    return parse_transcript(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))


def replay(task: Task, transcript: Transcript, host: ToolHost) -> Transcript:
    host.reset()
    answer = ScriptedAdapter(transcript).run_task(task, host)
    return Transcript(calls=list(host.calls), answer=answer, meta=transcript.meta, replayed=True)


# --------------------------------------------------------------------------- answer checkers

_MOCK_SNAPSHOT = None


def mock_snapshot():
    global _MOCK_SNAPSHOT
    if _MOCK_SNAPSHOT is None:
        _prepare_environment()
        from revit_mcp_server.semantic.engine import generate_mock_snapshot

        _MOCK_SNAPSHOT = generate_mock_snapshot()
    return _MOCK_SNAPSHOT


def _param(element: Any, name: str) -> Any:
    value = element.params.get(name)
    return None if value is None else value.v


def mock_elements(filter_: dict[str, Any]) -> list[Any]:
    """Elements of the mock snapshot that match a small filter.

    Keys: category, level (level name), placed (true/false), parameter_empty
    (parameter name), parameter_equals ({name: value}).
    """
    allowed = {"category", "level", "placed", "parameter_empty", "parameter_equals", "parameter"}
    unknown = set(filter_) - allowed
    if unknown:
        raise EvalError(f"Unknown mock filter keys: {', '.join(sorted(unknown))}")
    snapshot = mock_snapshot()
    levels = {el.uid: el.type_name for el in snapshot.elements if el.category == "OST_Levels"}
    out = []
    for el in snapshot.elements:
        if "category" in filter_ and el.category != filter_["category"]:
            continue
        if "level" in filter_ and levels.get(el.level_uid or "") != filter_["level"]:
            continue
        if "placed" in filter_ and bool(el.level_uid) != bool(filter_["placed"]):
            continue
        if "parameter_empty" in filter_ and _param(el, filter_["parameter_empty"]) not in (None, ""):
            continue
        if any(str(_param(el, k)) != str(v) for k, v in (filter_.get("parameter_equals") or {}).items()):
            continue
        out.append(el)
    return out


def expected_number(checker: dict[str, Any]) -> float:
    if "value" in checker:
        return float(checker["value"])
    if "mock_count" in checker:
        return float(len(mock_elements(checker["mock_count"])))
    spec = dict(checker["mock_sum"])
    parameter = spec.pop("parameter")
    return float(sum(float(_param(el, parameter) or 0) for el in mock_elements(spec)))


def _number_text(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def run_checker(checker: dict[str, Any], answer: str) -> tuple[bool | None, str]:
    """(passed, detail). passed is None when the checker does not apply."""
    kind = checker["type"]
    text = answer.lower()
    if kind == "none":
        return None, f"not deterministic: {checker['reason']}"
    if kind == "contains_all":
        missing = [v for v in checker["values"] if v.lower() not in text]
        return (not missing, "all found" if not missing else f"missing: {', '.join(missing)}")
    if kind == "contains_any":
        found = [v for v in checker["values"] if v.lower() in text]
        return (bool(found), f"found: {found[0]}" if found else f"none of: {', '.join(checker['values'])}")
    value = expected_number(checker)
    shown = _number_text(value)
    pattern = rf"(?<![\d.]){re.escape(shown)}(?![\d]|\.\d)"
    if value == 0:
        pattern += r"|\bzero\b|\bnone\b|\bno\b"
    found = re.search(pattern, text) is not None
    return found, f"expected {shown}" + ("" if found else " (not in the answer)")


# --------------------------------------------------------------------------- scoring

@dataclass
class CheckResult:
    passed: bool | None  # None = not applicable
    score: float  # 0..1
    detail: str


@dataclass
class TaskResult:
    task: Task
    transcript_path: str
    calls: int
    failed_calls: int
    checks: dict[str, CheckResult]
    score: float
    passed: bool
    tools_used: list[str]
    call_log: list[dict[str, str]]
    replayed: bool
    visibility: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.task.id,
            "prompt": self.task.prompt,
            "kind": self.task.kind,
            "profile": self.task.profile,
            "transcript": self.transcript_path,
            "replayed": self.replayed,
            "score": round(self.score, 1),
            "passed": self.passed,
            "calls": self.calls,
            "max_calls": self.task.max_calls,
            "failed_calls": self.failed_calls,
            "tools_used": self.tools_used,
            "call_log": self.call_log,
            "profile_visibility": self.visibility,
            "checks": {name: {"passed": c.passed, "score": round(c.score, 3), "detail": c.detail}
                       for name, c in self.checks.items()},
        }


def _planned_tools(call: Call) -> list[str]:
    actions = call.arguments.get("actions")
    if call.tool != PLAN_TOOL or not isinstance(actions, list):
        return []
    return [a.get("tool") for a in actions if isinstance(a, dict) and isinstance(a.get("tool"), str)]


def _log_entry(call: Call) -> dict[str, str]:
    entry = {"tool": call.tool, "status": call.status}
    if call.status != "ok" and call.result:
        entry["message"] = call.result.strip().splitlines()[0][:300]
    return entry


def score_transcript(task: Task, transcript: Transcript, index: dict[str, ToolInfo],
                     human_only: Iterable[str], transcript_path: str = "") -> TaskResult:
    calls = transcript.calls
    human_only = frozenset(human_only)
    checks: dict[str, CheckResult] = {}

    # Tools: some expected set is fully covered by successful calls (or planned writes).
    used = {c.tool for c in calls if c.status in ("ok", "awaits_approval")}
    planned = {t for c in calls if c.status == "ok" for t in _planned_tools(c)}
    covered = used | planned
    unknown = sorted({c.tool for c in calls if c.tool not in index} | {t for c in calls for t in _planned_tools(c)
                                                                        if t not in index})
    best = max(task.expected_tools, key=lambda option: sum(t in covered for t in option) / len(option))
    hit = sum(t in covered for t in best) / len(best)
    detail = f"used {', '.join(t for t in best if t in covered) or 'none'} of {' + '.join(best)}"
    if hit < 1:
        detail += f"; missing {', '.join(t for t in best if t not in covered)}"
    if unknown:
        detail += f"; unknown tools: {', '.join(unknown)}"
    checks["tools"] = CheckResult(hit == 1 and not unknown, hit if not unknown else hit / 2, detail)

    # Calls: at most max_calls.
    count = len(calls)
    checks["calls"] = CheckResult(count <= task.max_calls, min(1.0, task.max_calls / count) if count else 0.0,
                                  f"{count} call(s), at most {task.max_calls}")

    # Plan: writes only through plan_actions then execute_plan; no plan for a read.
    plan_problems = []
    plan_indexes = [i for i, c in enumerate(calls) if c.tool == PLAN_TOOL]
    writes_direct = [(i, c) for i, c in enumerate(calls) if c.tool in index and index[c.tool].mutating]
    if task.plan_required:
        expected_writes = {t for option in task.expected_tools for t in option if t in index and index[t].mutating}
        good_plans = [i for i in plan_indexes if expected_writes & set(_planned_tools(calls[i]))]
        if not good_plans:
            plan_problems.append("no plan_actions call drafts the expected write")
        for i, call in writes_direct:
            if "plan_id" not in call.arguments:
                plan_problems.append(f"{call.tool} was called directly without a plan")
            elif not plan_indexes or i < plan_indexes[0]:
                plan_problems.append(f"{call.tool} ran with a plan_id before any plan was drafted")
        executed = [i for i, c in enumerate(calls)
                    if c.tool in EXECUTE_TOOLS or (c.tool in index and index[c.tool].mutating and "plan_id" in c.arguments)]
        if good_plans and not any(i > good_plans[0] for i in executed):
            plan_problems.append("the plan was never executed after approval")
    else:
        if plan_indexes:
            plan_problems.append("a plan was drafted for a request that changes nothing")
        if any(c.tool in EXECUTE_TOOLS for c in calls):
            plan_problems.append("execute_plan was called for a request that changes nothing")
        for _, call in writes_direct:
            plan_problems.append(f"write tool {call.tool} was called for a request that changes nothing")
    checks["plan"] = CheckResult(not plan_problems, 0.0 if plan_problems else 1.0,
                                 "; ".join(plan_problems) or ("plan drafted, then executed after approval"
                                                              if task.plan_required else "no writes, no plan"))

    # Forbidden: task list plus the human-only approval tools, called or planned.
    forbidden = set(task.forbidden_tools) | human_only
    hits = sorted({c.tool for c in calls if c.tool in forbidden}
                  | {t for c in calls for t in _planned_tools(c) if t in forbidden})
    checks["forbidden"] = CheckResult(not hits, 0.0 if hits else 1.0,
                                      f"used {', '.join(hits)}" if hits else "none used")

    # Answer.
    results = [run_checker(checker, transcript.answer) for checker in task.checker]
    applied = [r for r in results if r[0] is not None]
    if applied:
        ok = all(r[0] for r in applied)
        checks["answer"] = CheckResult(ok, sum(1.0 for r in applied if r[0]) / len(applied),
                                       "; ".join(r[1] for r in results))
    else:
        checks["answer"] = CheckResult(None, 0.0, "; ".join(r[1] for r in results))

    weight = sum(WEIGHTS[name] for name, c in checks.items() if c.passed is not None)
    score = 100.0 * sum(WEIGHTS[name] * c.score for name, c in checks.items() if c.passed is not None) / weight
    passed = all(c.passed for c in checks.values() if c.passed is not None)
    return TaskResult(task=task, transcript_path=transcript_path, calls=count,
                      failed_calls=sum(c.status == "error" for c in calls), checks=checks,
                      score=score, passed=passed, tools_used=[c.tool for c in calls],
                      call_log=[_log_entry(c) for c in calls],
                      replayed=transcript.replayed, visibility=profile_visibility(task, index))


def missing_result(task: Task, index: dict[str, ToolInfo]) -> TaskResult:
    check = CheckResult(False, 0.0, "no transcript")
    return TaskResult(task=task, transcript_path="", calls=0, failed_calls=0,
                      checks={name: check for name in WEIGHTS}, score=0.0, passed=False,
                      tools_used=[], call_log=[], replayed=False, visibility=profile_visibility(task, index))


# --------------------------------------------------------------------------- reports

def summary(results: list[TaskResult]) -> dict[str, Any]:
    total = len(results)
    return {
        "tasks": total,
        "passed": sum(r.passed for r in results),
        "score": round(sum(r.score for r in results) / total, 1) if total else 0.0,
        "by_check": {name: sum(1 for r in results if r.checks[name].passed) for name in WEIGHTS},
    }


def report_json(results: list[TaskResult], mode: str) -> dict[str, Any]:
    return {"schema": "amb.agent-eval/1", "mode": mode, "overall": summary(results),
            "weights": WEIGHTS, "tasks": [r.to_dict() for r in results]}


def _mark(check: CheckResult) -> str:
    return "n/a" if check.passed is None else ("pass" if check.passed else "FAIL")


def report_markdown(results: list[TaskResult], mode: str) -> str:
    overall = summary(results)
    lines = [
        "# Agent eval report",
        "",
        f"Mode: {mode}. Tasks: {overall['tasks']}. Passed: {overall['passed']}. "
        f"Overall score: {overall['score']} / 100.",
        "",
        "| Task | Transcript | Score | Calls | Tools | Calls check | Plan | Forbidden | Answer |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        c = r.checks
        lines.append(f"| {r.task.id} | {Path(r.transcript_path).name or '-'} | {r.score:.1f} | {r.calls}/{r.task.max_calls} | {_mark(c['tools'])} | "
                     f"{_mark(c['calls'])} | {_mark(c['plan'])} | {_mark(c['forbidden'])} | {_mark(c['answer'])} |")
    failing = [r for r in results if not r.passed]
    if failing:
        lines += ["", "## Failed checks", ""]
        for r in failing:
            for name, check in r.checks.items():
                if check.passed is False:
                    lines.append(f"- {r.task.id} ({Path(r.transcript_path).name or 'no transcript'}) / {name}: "
                                 f"{check.detail}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- runners

def transcript_for(task: Task, directory: Path) -> Path | None:
    for path in (directory / f"{task.id}.jsonl", directory / task.id / "good.jsonl"):
        if path.is_file():
            return path
    return None


class HostPool:
    """One ToolHost per profile, built on first use."""

    def __init__(self, substitute_session_ids: bool) -> None:
        self.substitute = substitute_session_ids
        self.hosts: dict[str, ToolHost] = {}

    def get(self, profile: str) -> ToolHost:
        if profile not in self.hosts:
            self.hosts[profile] = ToolHost(profile, substitute_session_ids=self.substitute)
        return self.hosts[profile]


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def score_file(task: Task, path: Path, index: dict[str, ToolInfo], human_only: frozenset[str],
               pool: HostPool | None) -> TaskResult:
    transcript = load_transcript(path)
    if pool is not None:
        transcript = replay(task, transcript, pool.get(task.profile))
    return score_transcript(task, transcript, index, human_only, _rel(path))


def run_replay(tasks: list[Task], directory: Path, index: dict[str, ToolInfo], replay_calls: bool,
               skip_missing: bool) -> list[TaskResult]:
    human_only = human_only_tools()
    pool = HostPool(substitute_session_ids=True) if replay_calls else None
    results = []
    for task in tasks:
        path = transcript_for(task, directory)
        if path is None:
            if not skip_missing:
                results.append(missing_result(task, index))
            continue
        results.append(score_file(task, path, index, human_only, pool))
    return results


def golden_files(task: Task, directory: Path = TRANSCRIPTS_DIR) -> list[Path]:
    folder = directory / task.id
    return sorted(folder.glob("*.jsonl")) if folder.is_dir() else []


def golden_mismatches(result: TaskResult, meta: dict[str, Any]) -> list[str]:
    """Differences between a scored golden transcript and the expectation in its meta line."""
    expect = meta.get("expect")
    if not isinstance(expect, dict) or "passed" not in expect:
        return [f"{result.transcript_path}: meta.expect.passed is missing"]
    problems = []
    if bool(expect["passed"]) != result.passed:
        problems.append(f"{result.transcript_path}: expected passed={expect['passed']}, got {result.passed} "
                        f"({'; '.join(f'{n}: {c.detail}' for n, c in result.checks.items() if c.passed is False)})")
    for name in expect.get("failed_checks", []):
        if name not in result.checks or result.checks[name].passed is not False:
            problems.append(f"{result.transcript_path}: expected check '{name}' to fail")
    return problems


def run_golden(tasks: list[Task], index: dict[str, ToolInfo], replay_calls: bool = True,
               directory: Path = TRANSCRIPTS_DIR) -> tuple[list[TaskResult], list[str]]:
    human_only = human_only_tools()
    pool = HostPool(substitute_session_ids=True) if replay_calls else None
    results, problems = [], []
    for task in tasks:
        for path in golden_files(task, directory):
            result = score_file(task, path, index, human_only, pool)
            results.append(result)
            problems += golden_mismatches(result, load_transcript(path).meta)
    return results, problems


def run_live(tasks: list[Task], adapter: AgentAdapter, index: dict[str, ToolInfo],
             record_dir: Path | None) -> list[TaskResult]:
    human_only = human_only_tools()
    pool = HostPool(substitute_session_ids=False)
    results = []
    for task in tasks:
        host = pool.get(task.profile)
        host.reset()
        answer = adapter.run_task(task, host)
        transcript = Transcript(calls=list(host.calls), answer=str(answer or ""),
                                meta={"adapter": getattr(adapter, "name", type(adapter).__name__)}, replayed=True)
        path = ""
        if record_dir is not None:
            record_dir.mkdir(parents=True, exist_ok=True)
            target = record_dir / f"{task.id}.jsonl"
            target.write_text(transcript.to_jsonl(), encoding="utf-8")
            path = _rel(target)
        results.append(score_transcript(task, transcript, index, human_only, path))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tasks", type=Path, default=TASKS_DIR, help="folder of task YAML files")
    parser.add_argument("--transcripts", type=Path, default=TRANSCRIPTS_DIR,
                        help="folder with <task_id>.jsonl or <task_id>/good.jsonl (default: the golden set)")
    parser.add_argument("--task", action="append", default=[], help="only this task id (repeatable)")
    parser.add_argument("--golden", action="store_true", help="check every golden transcript against its meta line")
    parser.add_argument("--no-replay", action="store_true", help="score transcripts as recorded, no mock server")
    parser.add_argument("--skip-missing", action="store_true", help="leave out tasks that have no transcript")
    parser.add_argument("--live", action="store_true", help="drive an agent through --adapter (not for CI)")
    parser.add_argument("--adapter", default="", help="module:Class or file.py:Class for --live")
    parser.add_argument("--record", type=Path, help="with --live: write each transcript here as JSONL")
    parser.add_argument("--report-json", type=Path, help="write the JSON report here")
    parser.add_argument("--report-md", type=Path, help="write the Markdown report here")
    parser.add_argument("--fail-under", type=float, default=None, help="exit 1 when the overall score is lower")
    args = parser.parse_args(argv)

    try:
        tasks = load_tasks(args.tasks)
        if args.task:
            unknown = sorted(set(args.task) - {t.id for t in tasks})
            if unknown:
                raise EvalError(f"Unknown task id(s): {', '.join(unknown)}")
            tasks = [t for t in tasks if t.id in args.task]
        index = load_tool_index()
        problems = [p for task in tasks for p in check_task_tools(task, index)]
        if problems:
            raise EvalError("Invalid tasks:\n  " + "\n  ".join(problems))
        if args.live:
            adapter = load_adapter(args.adapter) if args.adapter else StubAdapter()
            mode = f"live ({getattr(adapter, 'name', type(adapter).__name__)})"
            results = run_live(tasks, adapter, index, args.record)
        elif args.golden:
            mode = "golden"
            results, problems = run_golden(tasks, index, replay_calls=not args.no_replay)
        else:
            mode = "static" if args.no_replay else "replay"
            results = run_replay(tasks, args.transcripts, index, not args.no_replay, args.skip_missing)
    except (EvalError, NotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report_json(results, mode), indent=2) + "\n", encoding="utf-8")
    markdown = report_markdown(results, mode)
    if args.report_md:
        args.report_md.parent.mkdir(parents=True, exist_ok=True)
        args.report_md.write_text(markdown, encoding="utf-8")
    overall = summary(results)
    print(f"{mode}: {overall['passed']}/{overall['tasks']} passed, score {overall['score']}")
    if problems:
        print("Golden transcripts that do not meet their expectation:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    if args.fail_under is not None and overall["score"] < args.fail_under:
        print(f"Score {overall['score']} is under --fail-under {args.fail_under}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
