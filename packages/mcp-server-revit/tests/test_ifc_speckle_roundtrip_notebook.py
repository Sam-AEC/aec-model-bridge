"""examples/ifc-speckle-roundtrip.ipynb runs top to bottom in mock mode.

The code cells run in order as plain Python in a child process (no Jupyter
dependency), the same way tests/test_mock_tour_notebook.py runs the mock tour.
A second run blocks ``ifcopenshell`` with a ``sitecustomize`` import hook to check
that the notebook skips its IFC steps cleanly when the package is missing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NOTEBOOK = ROOT / "examples" / "ifc-speckle-roundtrip.ipynb"
DOC = ROOT / "docs" / "ifc-speckle-roundtrip.md"
STEPS = (
    "snapshot_take",
    "snapshot_compute",
    "plan_actions",
    "ifc_get_metadata",
    "ifc_validate",
    "ids_validator_validate_ifc",
    "ifc_query_elements",
    "ifc_get_properties",
    "revit_ifc_check",
    "speckle_auth_status",
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
print("REPORT " + json.dumps(namespace["report"], default=str))
"""

BLOCK_IFC = """
import sys

class _BlockIfc:
    def find_spec(self, name, path=None, target=None):
        if name == "ifcopenshell" or name.startswith("ifcopenshell.") or name == "ifctester":
            raise ModuleNotFoundError(f"No module named {name!r} (blocked by the test)")
        return None

sys.meta_path.insert(0, _BlockIfc())
"""


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _code(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")


def _run(tmp_path: Path, extra_env: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("MCP_REVIT_", "SPECKLE_"))}
    env.update({"MCP_REVIT_MODE": "mock", "TMPDIR": str(tmp_path), "TEMP": str(tmp_path), "TMP": str(tmp_path)})
    env.update(extra_env or {})
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
    assert len(list(tmp_path.glob("aec-roundtrip-*"))) == 1  # only its own temporary workspace
    return {"stdout": proc.stdout, "report": json.loads(proc.stdout.split("REPORT ", 1)[1])}


def test_notebook_is_small_clean_and_runs_the_steps_in_order():
    nb = _notebook()
    assert nb["nbformat"] == 4
    assert 6 <= len(nb["cells"]) <= 14
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None, "commit the notebook without outputs"
    code = _code(nb)
    positions = [code.index(f'call("{name}"') for name in STEPS]
    assert positions == sorted(positions), "round-trip steps are out of order"


def test_notebook_never_approves_executes_or_receives():
    code = _code(_notebook())
    for forbidden in ("execute_plan", "approve_plan", "approve_action", "MCP_REVIT_APPROVAL_MODE", "dev_mode"):
        assert forbidden not in code, forbidden
    # Network-backed Speckle tools are only ever drafted into a plan, never called.
    for network_tool in ("speckle_send_object", "speckle_receive_object", "speckle_health", "speckle_list_projects"):
        assert not re.search(rf'call\("{network_tool}"', code), network_tool


def test_doc_marks_live_paths_unverified_and_names_the_notebook():
    text = DOC.read_text(encoding="utf-8")
    assert "examples/ifc-speckle-roundtrip.ipynb" in text
    assert "UNVERIFIED" in text
    assert "ifc-speckle-roundtrip.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def test_notebook_runs_in_mock_mode(tmp_path):
    result = _run(tmp_path)
    report = result["report"]
    assert report["snapshot_elements"] > 0
    assert report["speckle_send"] == "pending"
    assert report["speckle_receive"] == "skipped"
    assert "SKIPPED (requires a Speckle server)" in result["stdout"]
    if importlib.util.find_spec("ifcopenshell") is None:
        assert report["ifc"] == "skipped"
        return
    ifc = report["ifc"]
    assert ifc["schema"] == "IFC4"
    by_class = {row["ifc_class"]: row for row in ifc["comparison"]}
    assert by_class["IfcWall"]["ifc"] == 3 and by_class["IfcDoor"]["ifc"] == 1
    assert by_class["IfcDoor"]["match"] is True  # the mock model has one door too
    assert ifc["fire_rating"]["ifc"] == ["EI60", None, None]
    if importlib.util.find_spec("ifctester") is not None:
        assert report["ids"] == {"passed": 1, "total": 2}


def test_notebook_skips_ifc_steps_without_ifcopenshell(tmp_path):
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(BLOCK_IFC, encoding="utf-8")
    pythonpath = os.pathsep.join(filter(None, [str(hook), os.environ.get("PYTHONPATH")]))
    work = tmp_path / "work"
    work.mkdir()
    result = _run(work, {"PYTHONPATH": pythonpath})
    report = result["report"]
    assert report["ifc"] == "skipped" and report["ids"] == "skipped"
    assert report["speckle_send"] == "pending"
    assert "SKIPPED: IFC steps need ifcopenshell" in result["stdout"]
    assert "send plan:" in result["stdout"]
