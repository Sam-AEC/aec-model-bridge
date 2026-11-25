import os
from pathlib import Path

# Ensure environment variables exist before other modules import config.
workspace = Path(__file__).resolve().parent
os.environ.setdefault("MCP_REVIT_WORKSPACE_DIR", str(workspace))
os.environ.setdefault("MCP_REVIT_ALLOWED_DIRECTORIES", str(workspace))
os.environ.setdefault("MCP_REVIT_MODE", "mock")


import pytest  # noqa: E402

try:  # Hypothesis is in the dev extra; the stdio smoke test may run without it.
    from hypothesis import HealthCheck, settings  # noqa: E402
except ImportError:  # pragma: no cover
    settings = None

if settings is not None:
    # Property tests (tests/test_property_*.py). "default" keeps the full suite fast and
    # repeatable; "slow" searches much deeper. Select with AEC_HYPOTHESIS_PROFILE=slow.
    _common = dict(suppress_health_check=[HealthCheck.too_slow], print_blob=True)
    # No per-example deadline: wall-clock limits fail on slow CI runners (Windows file system calls)
    # without finding a bug. max_examples keeps the run short.
    settings.register_profile("default", max_examples=30, deadline=None, derandomize=True,
                              database=None, **_common)
    settings.register_profile("slow", max_examples=2000, deadline=None, stateful_step_count=80, **_common)
    settings.load_profile(os.environ.get("AEC_HYPOTHESIS_PROFILE", "default"))


@pytest.fixture(autouse=True)
def _isolated_panel_token_file(tmp_path, monkeypatch):
    """Never touch the real per-user panel token file from a test."""
    monkeypatch.setenv("MCP_PANEL_TOKEN_FILE", str(tmp_path / "panel-hub.token"))
    # A developer's own recording setting must never make the suite write cassettes.
    monkeypatch.delenv("MCP_REVIT_RECORD", raising=False)


@pytest.fixture
def cassette_replay(tmp_path, monkeypatch):
    """Run a recorded cassette as a regression test: ``cassette_replay(path)``. See cassette_replay.py."""
    from cassette_replay import replay_cassette

    def run(path, compare: bool = True):
        monkeypatch.setenv("MCP_REVIT_CASSETTE", str(path))
        return replay_cassette(path, tmp_path, compare=compare)

    return run
