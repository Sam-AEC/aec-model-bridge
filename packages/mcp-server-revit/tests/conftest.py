import os
from pathlib import Path

# Ensure environment variables exist before other modules import config.
workspace = Path(__file__).resolve().parent
os.environ.setdefault("MCP_REVIT_WORKSPACE_DIR", str(workspace))
os.environ.setdefault("MCP_REVIT_ALLOWED_DIRECTORIES", str(workspace))
os.environ.setdefault("MCP_REVIT_MODE", "mock")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_panel_token_file(tmp_path, monkeypatch):
    """Never touch the real per-user panel token file from a test."""
    monkeypatch.setenv("MCP_PANEL_TOKEN_FILE", str(tmp_path / "panel-hub.token"))
