"""--help and --version must print and exit; they must not start the long-running servers."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

import revit_mcp_server
from revit_mcp_server.mcp_server import run_mcp_server
from revit_mcp_server.panel_server import run_panel_server

ENTRY_POINTS = [
    pytest.param(run_mcp_server, id="mcp_server"),
    pytest.param(run_panel_server, id="panel_server"),
]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_help_exits_without_starting_the_server(entry, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        entry()
    assert exit_info.value.code == 0
    assert "usage:" in capsys.readouterr().out


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_version_flag(entry, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        entry()
    assert exit_info.value.code == 0
    assert revit_mcp_server.__version__ in capsys.readouterr().out


def test_help_subprocess_smoke(tmp_path) -> None:
    """One real `python -m` run: the module entry point exits on --help instead of serving."""
    env = {
        **os.environ,
        "MCP_REVIT_MODE": "mock",
        "MCP_REVIT_WORKSPACE_DIR": str(tmp_path),
        "MCP_REVIT_ALLOWED_DIRECTORIES": str(tmp_path),
    }
    out = subprocess.run(
        [sys.executable, "-m", "revit_mcp_server.mcp_server", "--help"],
        capture_output=True, text=True, env=env, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert out.returncode == 0
    assert "usage:" in out.stdout
