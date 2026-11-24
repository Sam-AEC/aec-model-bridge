"""``python -m revit_mcp_server`` is the supported start command (issue #159).

The pip console launchers (``Scripts\\*.exe``) embed the build machine's interpreter path, so the
Windows bundle ships ``.cmd`` launchers and client configs that call ``python.exe -m ...``.
"""
from __future__ import annotations

import runpy
import subprocess
import sys

from revit_mcp_server import mcp_server


def test_dunder_main_calls_the_console_script_entry_point(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mcp_server, "run_mcp_server", lambda: calls.append("run"))
    sys.modules.pop("revit_mcp_server.__main__", None)
    runpy.run_module("revit_mcp_server", run_name="__main__")
    assert calls == ["run"]


def test_python_dash_m_package_answers_version() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "revit_mcp_server", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "aec-model-bridge" in proc.stdout
