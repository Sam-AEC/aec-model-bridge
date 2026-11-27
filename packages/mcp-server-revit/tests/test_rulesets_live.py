"""The ruleset files in .github/rulesets match the rulesets live on GitHub.

The shape test always runs. The drift test needs GH_TOKEN (read access to the
repository's rulesets) and AMB_LIVE_RULESETS=1; the rulesets-drift workflow sets both.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RULESET_DIR = ROOT / ".github" / "rulesets"
REPO = "Sam-AEC/aec-model-bridge"
KEYS = ["name", "target", "enforcement", "conditions", "rules", "bypass_actors"]
VOLATILE = {
    "id",
    "node_id",
    "source",
    "source_type",
    "created_at",
    "updated_at",
    "current_user_can_bypass",
    "_links",
}


def _files() -> dict[str, dict]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(RULESET_DIR.glob("*.json"))}


def _normalise(value):
    """Drop API-only fields, sort rules by type and lists by their JSON form."""
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        items = [_normalise(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    return value


def _normalise_ruleset(ruleset: dict) -> dict:
    out = _normalise({k: v for k, v in ruleset.items() if k in KEYS})
    out["rules"] = sorted(out["rules"], key=lambda r: r["type"])
    return out


def test_ruleset_files_are_valid():
    files = _files()
    assert set(files) == {"protect-main.json", "protect-dev.json", "protect-tags.json"}
    for name, data in files.items():
        assert list(data) == KEYS, f"{name}: keys must be exactly {KEYS} in that order"
        assert data["target"] in {"branch", "tag"}
        assert data["enforcement"] in {"active", "evaluate", "disabled"}
        assert data["rules"], f"{name}: no rules"
        assert all("type" in r for r in data["rules"])
        assert set(data["conditions"]["ref_name"]) == {"include", "exclude"}


def _get(path: str, token: str):
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ruleset-drift-check",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https host)
        return json.load(resp)


@pytest.mark.skipif(
    not (os.environ.get("GH_TOKEN") and os.environ.get("AMB_LIVE_RULESETS") == "1"),
    reason="set GH_TOKEN and AMB_LIVE_RULESETS=1 to compare with the live rulesets",
)
def test_ruleset_files_match_live():
    token = os.environ["GH_TOKEN"]
    live = {}
    for item in _get(f"repos/{REPO}/rulesets", token):
        full = _get(f"repos/{REPO}/rulesets/{item['id']}", token)
        live[full["name"]] = _normalise_ruleset(full)
    files = {d["name"]: _normalise_ruleset(d) for d in _files().values()}
    assert set(live) == set(files), "ruleset names differ between GitHub and .github/rulesets"
    for name, expected in files.items():
        assert live[name] == expected, f"ruleset '{name}' drifted from its file"
