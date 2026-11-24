"""examples/mock-tour.ipynb runs top to bottom in mock mode and stops at approval.

The code cells are executed in order as plain Python in a child process (no Jupyter
dependency), the way a kernel would: top-level ``await`` is allowed and every cell
shares one namespace and one event loop.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NOTEBOOK = ROOT / "examples" / "mock-tour.ipynb"
TOUR = (
    "revit_get_context",
    "search_tools",
    "snapshot_take",
    "snapshot_query",
    "snapshot_compute",
    "plan_actions",
)

RUNNER = r"""
import ast, asyncio, inspect, json, sys

cells = [c for c in json.load(open(sys.argv[1], encoding="utf-8"))["cells"] if c["cell_type"] == "code"]
namespace = {"__name__": "__main__"}
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
for index, cell in enumerate(cells):
    code = compile("".join(cell["source"]), f"<cell {index}>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    result = eval(code, namespace)
    if inspect.iscoroutine(result):
        loop.run_until_complete(result)
    print(f"--- cell {index} ok", flush=True)
plan = namespace["plan"]
print("PLAN " + json.dumps({"state": plan["state"], "plan_id": plan["plan_id"]}))
"""


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _code(nb: dict) -> str:
    return "\n".join(
        "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"
    )


def test_notebook_is_small_clean_and_walks_the_tour_in_order():
    nb = _notebook()
    assert nb["nbformat"] == 4
    assert 6 <= len(nb["cells"]) <= 12
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None, (
                "commit the notebook without outputs"
            )
    code = _code(nb)
    positions = [code.index(f'call("{name}"') for name in TOUR]
    assert positions == sorted(positions), "tour steps are out of order"


def test_notebook_never_approves_or_executes():
    code = _code(_notebook())
    for forbidden in (
        "execute_plan",
        "approve_plan",
        "approve_action",
        "MCP_REVIT_APPROVAL_MODE",
        "dev_mode",
    ):
        assert not re.search(rf'call\("{forbidden}', code) and forbidden not in code, (
            forbidden
        )


def test_notebook_code_cells_run_in_mock_mode(tmp_path):
    env = {
        k: v for k, v in os.environ.items() if not k.upper().startswith("MCP_REVIT_")
    }
    env.update(
        {
            "MCP_REVIT_MODE": "mock",
            "TMPDIR": str(tmp_path),
            "TEMP": str(tmp_path),
            "TMP": str(tmp_path),
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", RUNNER, str(NOTEBOOK)],
        env=env,
        cwd=ROOT / "packages" / "mcp-server-revit",
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-4000:]
    code_cells = sum(c["cell_type"] == "code" for c in _notebook()["cells"])
    assert proc.stdout.count("--- cell ") == code_cells
    plan = json.loads(proc.stdout.split("PLAN ", 1)[1])
    assert plan["state"] == "pending"
    workspaces = list(tmp_path.glob("aec-mock-tour-*"))
    assert len(workspaces) == 1  # the tour wrote only to its own temporary workspace
