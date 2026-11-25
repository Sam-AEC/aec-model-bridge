"""The opt-in `amb` helper library for revit_execute_python (helpers=true).

Checks: the helper source stays inside the syntax that IronPython 2.7 and 3.4 both accept, the read part passes the
read-mode rules of both the server and the add-in, the prelude is added only when asked, and read mode still
refuses write calls with helpers on. Nothing here runs Revit; live behaviour is UNVERIFIED.
"""
from __future__ import annotations

import ast
import asyncio
import io
import re
import tokenize
from pathlib import Path

import pytest

from revit_mcp_server import mcp_server, python_helpers
from revit_mcp_server.modules.revit_recipes import module as recipes
from revit_mcp_server.providers.revit_jobs import RevitJobProvider
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.gating import requires_approval
from revit_mcp_server.security.read_mode import (
    ReadModeViolation,
    execute_python_payload,
    find_violations,
    is_read_mode_call,
)
from revit_mcp_server.security.workspace import WorkspaceMonitor

REPO_ROOT = Path(__file__).resolve().parents[3]
READ_MODE_RULES_CS = REPO_ROOT / "packages" / "revit-bridge-addin" / "src" / "Bridge" / "ReadModeRules.cs"
CSPROJ = REPO_ROOT / "packages" / "revit-bridge-addin" / "RevitBridge.csproj"
HELPER_FILES = [python_helpers.READ_HELPERS, python_helpers.WRITE_HELPERS]

READ_SCRIPT = "print(amb.count(amb.instances('Walls')))"
WRITE_ONLY_NAMES = ("run", "batch", "group", "try_sub", "set", "regenerate", "start", "commit")


# --------------------------------------------------------------------------- #
# Syntax level: IronPython 2.7 (Revit 2024) and 3.4 (Revit 2025+)
# --------------------------------------------------------------------------- #
def test_addin_ships_ironpython_27_and_34():
    """The syntax rules below assume these two engines; revisit them when the add-in changes engine."""
    text = CSPROJ.read_text(encoding="utf-8")
    assert re.search(r'Include="IronPython" Version="2\.7\.\d+"', text)
    assert re.search(r'Include="IronPython" Version="3\.4\.\d+"', text)


# Names that exist in only one of the two engines.
_ONE_ENGINE_NAMES = {"long", "basestring", "unicode", "xrange", "raw_input", "unichr", "execfile", "reduce", "cmp"}


def _syntax_problems(source: str) -> list[str]:
    """Constructs CPython 3 parses that IronPython 2.7 or 3.4 would reject or run differently."""
    problems = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        where = f"line {getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.JoinedStr):
            problems.append(f"{where}: f-string")
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr, ast.Nonlocal, ast.YieldFrom, ast.Await)):
            problems.append(f"{where}: {type(node).__name__} is not in IronPython 2.7")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)):
            problems.append(f"{where}: async")
        elif isinstance(node, ast.Raise) and node.cause is not None:
            problems.append(f"{where}: raise ... from")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult):
            problems.append(f"{where}: @ operator")
        elif isinstance(node, ast.Dict) and any(k is None for k in node.keys):
            problems.append(f"{where}: dict unpacking")
        elif isinstance(node, (ast.FunctionDef, ast.Lambda)):
            a = node.args
            if a.kwonlyargs or a.posonlyargs:
                problems.append(f"{where}: keyword-only or positional-only argument")
            if any(x.annotation is not None for x in a.args + a.kwonlyargs):
                problems.append(f"{where}: annotation")
            if isinstance(node, ast.FunctionDef) and node.returns is not None:
                problems.append(f"{where}: return annotation")
        elif isinstance(node, (ast.Assign, ast.For)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(n, ast.Starred) for t in targets for n in ast.walk(t)):
                problems.append(f"{where}: starred assignment")
        elif isinstance(node, ast.Call):
            if sum(isinstance(a, ast.Starred) for a in node.args) > 1 or sum(k.arg is None for k in node.keywords) > 1:
                problems.append(f"{where}: more than one * or ** in a call")
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                problems.append(f"{where}: print (a statement in 2.7, a function in 3.4)")
            if isinstance(node.func, ast.Name) and node.func.id == "super" and not node.args:
                problems.append(f"{where}: super() without arguments")
        elif isinstance(node, ast.Name) and node.id in _ONE_ENGINE_NAMES:
            problems.append(f"{where}: {node.id} exists in only one IronPython version")
        elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
            problems.append(f"{where}: from __future__ (the caller's script follows the helpers)")
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.NUMBER and "_" in tok.string:
            problems.append(f"line {tok.start[0]}: underscore in a number literal")
        if tok.type == tokenize.STRING and re.match(r"(?i)^(rb|f|fr|rf)", tok.string):
            problems.append(f"line {tok.start[0]}: string prefix {tok.string[:2]!r}")
    return problems


@pytest.mark.parametrize("path", HELPER_FILES, ids=lambda p: p.name)
def test_helper_source_compiles_and_stays_in_the_shared_ironpython_subset(path):
    source = path.read_text(encoding="utf-8")
    compile(source, path.name, "exec")
    assert _syntax_problems(source) == []
    assert source.isascii(), "keep the helpers ASCII: IronPython 2.7 reads source without an encoding line"


def test_syntax_checker_catches_what_it_claims():
    bad = (
        "x = f'{1}'\n"
        "def g(a, *, b): pass\n"
        "def h(a: int): pass\n"
        "a, *b = [1, 2]\n"
        "print(1, 2)\n"
        "y = long(3)\n"
        "z = 1_000\n"
        "w = {**{}}\n"
        "class C(object):\n    def m(self):\n        return super().m()\n"
    )
    found = "\n".join(_syntax_problems(bad))
    for what in ("f-string", "keyword-only", "annotation", "starred assignment", "print", "long", "underscore", "dict unpacking", "super()"):
        assert what in found, what


def test_combined_text_compiles_in_both_modes():
    for mode in ("read", "write"):
        compile(python_helpers.with_helpers(READ_SCRIPT, mode), mode, "exec")


# --------------------------------------------------------------------------- #
# Read-mode rules: server and add-in
# --------------------------------------------------------------------------- #
def _addin_rules() -> list[tuple[str, re.Pattern[str]]]:
    source = READ_MODE_RULES_CS.read_text(encoding="utf-8")
    rules = [(m.group(1), re.compile(m.group(2).replace('""', '"'))) for m in re.finditer(r'\("([^"]+)",\s*new Regex\(@"((?:[^"]|"")*)"', source)]
    assert len(rules) >= 12
    return rules


def test_read_helpers_pass_the_server_and_addin_read_rules():
    text = python_helpers.helper_source("read")
    assert find_violations(text) == []
    assert [name for name, pattern in _addin_rules() if pattern.search(text)] == []


def test_write_helpers_would_fail_read_mode_so_they_are_never_sent_there():
    hits = find_violations(python_helpers.WRITE_HELPERS.read_text(encoding="utf-8"))
    assert {"Transaction", "SubTransaction", "TransactionGroup"} <= set(hits)


def test_read_part_defines_no_write_helpers():
    text = python_helpers.helper_source("read")
    for name in WRITE_ONLY_NAMES:
        assert not re.search(rf"^amb\.{name}\s*=", text, re.M), name
    assert "amb_transaction" not in text


# --------------------------------------------------------------------------- #
# The prelude is only added when asked
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("flag", [None, False])
@pytest.mark.parametrize("mode", ["read", "write"])
def test_no_prelude_without_the_flag(flag, mode):
    args = {"script": READ_SCRIPT, "mode": mode}
    if flag is not None:
        args["helpers"] = flag
    assert execute_python_payload(args) == {"script": READ_SCRIPT, "mode": mode}


def test_read_mode_gets_only_the_read_part():
    payload = execute_python_payload({"script": READ_SCRIPT, "mode": "read", "helpers": True})
    assert payload["mode"] == "read"
    assert payload["script"] == python_helpers.helper_source("read") + python_helpers.END_MARKER + "\n" + READ_SCRIPT
    assert "_amb_batch" not in payload["script"]
    assert find_violations(payload["script"]) == []


def test_write_mode_gets_both_parts_and_the_script_unchanged_at_the_end():
    payload = execute_python_payload({"script": READ_SCRIPT, "helpers": True})
    assert payload["mode"] == "write"
    assert payload["script"].startswith(python_helpers.READ_HELPERS.read_text(encoding="utf-8").splitlines()[0])
    assert "def _amb_batch(" in payload["script"]
    assert payload["script"].endswith(python_helpers.END_MARKER + "\n" + READ_SCRIPT)
    lines = payload["script"].split("\n")
    assert lines[python_helpers.helper_line_count("write")] == READ_SCRIPT


@pytest.mark.parametrize("bad", ["yes", 1, "true", [], {}])
def test_helpers_flag_must_be_a_boolean(bad):
    with pytest.raises(ValueError, match="helpers must be true or false"):
        execute_python_payload({"script": READ_SCRIPT, "mode": "read", "helpers": bad})


def test_future_import_is_refused_with_helpers_only():
    script = "from __future__ import print_function\nprint(doc.Title)"
    assert execute_python_payload({"script": script})["script"] == script
    with pytest.raises(ValueError, match="__future__"):
        execute_python_payload({"script": script, "helpers": True})


def test_helper_hashes_differ_by_mode():
    assert python_helpers.helper_sha256("read") != python_helpers.helper_sha256("write")
    with pytest.raises(ValueError):
        python_helpers.helper_source("other")


# --------------------------------------------------------------------------- #
# Read mode still refuses write calls with helpers on
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "script",
    [
        "t = Transaction(doc, 'x')\nt.Start()",
        "g = TransactionGroup(doc, 'x')",
        "s = SubTransaction(doc)",
        "doc.Save()",
        "exec('x = 1')",
        "fh = open('C:/x.txt', 'w')",
    ],
)
def test_read_mode_with_helpers_still_rejects_write_calls(script):
    args = {"script": script, "mode": "read", "helpers": True}
    with pytest.raises(ReadModeViolation):
        is_read_mode_call(args)
    with pytest.raises(ReadModeViolation):
        execute_python_payload(args)


def test_read_mode_combined_text_is_checked_again(monkeypatch):
    """A helper text that broke read mode would be refused, not sent."""
    monkeypatch.setattr("revit_mcp_server.security.read_mode.with_helpers", lambda script, mode: "Transaction\n" + script)
    with pytest.raises(ReadModeViolation):
        execute_python_payload({"script": READ_SCRIPT, "mode": "read", "helpers": True})


@pytest.fixture
def stack(tmp_path):
    registry, approval, job_manager, _modules, _ws = build_registry(WorkspaceMonitor([tmp_path]))
    approval.gate.approval_mode = "required"
    previous = (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager)
    mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = registry, approval, job_manager
    try:
        yield registry, approval
    finally:
        mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = previous


def _call(name, arguments):
    result = asyncio.run(mcp_server.call_tool(name, arguments))
    content = result.content if hasattr(result, "content") else result
    return content[0].text


def test_gate_with_helpers(stack):
    registry, approval = stack
    tool = registry.lookup_tool("revit_execute_python")
    assert "helpers" in tool.input_schema["properties"]
    assert tool.input_schema["properties"]["helpers"]["type"] == "boolean"
    read = {"script": READ_SCRIPT, "mode": "read", "helpers": True}
    assert requires_approval(registry, "revit_execute_python", tool, read) is False
    assert "executed successfully" in _call("revit_execute_python", read)
    write = {"script": READ_SCRIPT, "helpers": True}
    assert requires_approval(registry, "revit_execute_python", tool, write) is True
    assert _call("revit_execute_python", write).startswith("Approval Gate Blocked")
    refused = _call("revit_execute_python", {"script": "Transaction(doc, 'x')", "mode": "read", "helpers": True})
    assert "Read mode refuses" in refused and "executed successfully" not in refused
    assert approval.gate.list_pending_plans() == []


def test_run_job_passes_the_flag_only_when_set(stack):
    registry, _ = stack
    jobs = registry.lookup_tool_provider("revit_run_job")
    assert isinstance(jobs, RevitJobProvider)
    assert jobs._resolve({"script": READ_SCRIPT, "mode": "read", "helpers": True})[1] == {"script": READ_SCRIPT, "mode": "read", "helpers": True}
    assert "helpers" not in jobs._resolve({"script": READ_SCRIPT, "mode": "read"})[1]
    with pytest.raises(ValueError):
        jobs._resolve({"script": READ_SCRIPT, "helpers": "yes"})


# --------------------------------------------------------------------------- #
# Recipes get the read part, and the write part only for a write run
# --------------------------------------------------------------------------- #
def test_recipe_scripts_carry_the_helpers_by_run_mode():
    read = recipes.build_script("x = 1\n", "{}")
    write = recipes.build_script("x = 1\n", "{}", "write")
    assert python_helpers.helper_source("read") in read and "def _amb_batch(" not in read
    assert python_helpers.helper_source("write") in write
    assert find_violations(read) == []
