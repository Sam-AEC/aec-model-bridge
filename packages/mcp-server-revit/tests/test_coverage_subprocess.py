"""Child processes must report coverage (issue #235).

Tests that run `python -m revit_mcp_server...` execute code in a child process. The coverage
settings in pyproject.toml make coverage follow children and combine their data files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]


def _coverage_run_settings() -> dict:
    data = tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["coverage"]["run"]


def test_pyproject_follows_subprocesses() -> None:
    run = _coverage_run_settings()
    assert run["parallel"] is True
    assert "subprocess" in run["patch"]


def test_child_process_lines_are_measured(tmp_path: Path) -> None:
    """Run a child under coverage with the project's settings; its lines must reach the report."""
    run = _coverage_run_settings()
    rcfile = tmp_path / "coveragerc.toml"
    rcfile.write_text(
        "[run]\n"
        f"parallel = {str(run['parallel']).lower()}\n"
        f"patch = {json.dumps(run['patch'])}\n"
        f"source = [{json.dumps(str(PACKAGE_DIR / 'src' / 'revit_mcp_server'))}]\n"
        f"data_file = {json.dumps(str(tmp_path / '.coverage'))}\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-m', 'revit_mcp_server', '--version'], check=True)\n",
        encoding="utf-8",
    )
    cmd = [sys.executable, "-m", "coverage"]
    # Keep the outer --cov run (CI) out of this nested run: no inherited data file or start hook.
    env = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE")}
    env["COVERAGE_FILE"] = str(tmp_path / ".coverage")
    subprocess.run([*cmd, "run", f"--rcfile={rcfile}", str(parent)], check=True, timeout=120,
                   capture_output=True, cwd=tmp_path, env=env)
    subprocess.run([*cmd, "combine", f"--rcfile={rcfile}"], check=True, timeout=60,
                   capture_output=True, cwd=tmp_path, env=env)
    report = tmp_path / "report.json"
    subprocess.run([*cmd, "json", f"--rcfile={rcfile}", "-o", str(report)], check=True,
                   timeout=60, capture_output=True, cwd=tmp_path, env=env)
    files = json.loads(report.read_text(encoding="utf-8"))["files"]
    measured = {Path(name).name: info["summary"]["covered_lines"] for name, info in files.items()}
    assert measured.get("__main__.py", 0) > 0, measured
    assert measured.get("cli_flags.py", 0) > 0, measured
