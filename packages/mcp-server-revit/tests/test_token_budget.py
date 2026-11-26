"""scripts/token_budget.py: per-profile catalogue size against a committed baseline (#173)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_token_budget", ROOT / "scripts" / "token_budget.py")
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)


def _measurement(chars, tools=10, calls=(100, 50)):
    return {"tool_count": tools, "catalogue": {"chars": chars, "approx_tokens_chars_div_4": chars / 4},
            "calls": [{"name": f"c{i}", "response": {"chars": c}} for i, c in enumerate(calls)]}


def test_summarize_keeps_catalogue_and_call_sizes():
    row = tb.summarize(_measurement(4000))
    assert row == {"tool_count": 10, "catalogue_chars": 4000, "catalogue_approx_tokens": 1000.0,
                   "calls": {"c0": 100, "c1": 50}}


def test_growth_within_threshold_passes_and_shrinking_passes():
    base = {"threshold_pct": 10, "profiles": {"core": {"catalogue_chars": 1000}}}
    assert tb.compare({"core": {"catalogue_chars": 1100}}, base) == []
    assert tb.compare({"core": {"catalogue_chars": 500}}, base) == []


def test_growth_past_threshold_fails_with_numbers():
    base = {"threshold_pct": 10, "profiles": {"core": {"catalogue_chars": 1000}, "full": {"catalogue_chars": 9000}}}
    failures = tb.compare({"core": {"catalogue_chars": 1101}, "full": {"catalogue_chars": 9000}}, base)
    assert len(failures) == 1 and "core" in failures[0] and "1000" in failures[0] and "1101" in failures[0]


def test_profile_missing_from_baseline_or_measurement_fails():
    base = {"threshold_pct": 10, "profiles": {"core": {"catalogue_chars": 1000}}}
    assert tb.compare({"core": {"catalogue_chars": 1000}, "daily": {"catalogue_chars": 1}}, base)
    assert tb.compare({}, base)


def test_committed_baseline_covers_every_measured_profile():
    base = json.loads((ROOT / "docs" / "mcp-token-baseline.json").read_text(encoding="utf-8"))
    assert set(base["profiles"]) == set(tb.PROFILES)
    assert 0 < base["threshold_pct"] <= 25
    assert all(row["catalogue_chars"] > 0 for row in base["profiles"].values())


def test_release_workflow_runs_the_check_into_release_files():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "scripts/token_budget.py" in text and "dist/release/token-budget.json" in text
    assert text.index("scripts/token_budget.py") < text.index("SHA256SUMS.txt")


@pytest.mark.parametrize("pct", [0, -5, 101])
def test_bad_threshold_is_refused(pct):
    with pytest.raises(ValueError):
        tb.compare({"core": {"catalogue_chars": 1}}, {"threshold_pct": pct, "profiles": {"core": {"catalogue_chars": 1}}})
