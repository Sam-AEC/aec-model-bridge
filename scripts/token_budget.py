#!/usr/bin/env python
"""Measure the tool catalogue per profile and fail when one grows past the baseline.

  python scripts/token_budget.py --output token-budget.json
  python scripts/token_budget.py --output token-budget.json --update-baseline

Each profile runs scripts/measure_mcp_tokens.py in its own process (mock mode, no Revit).
The baseline is docs/mcp-token-baseline.json; `threshold_pct` is the allowed catalogue growth.
Counts are characters and chars/4, not billed tokens.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "docs" / "mcp-token-baseline.json"
PROFILES = ("core", "daily", "full")


def summarize(measurement: dict) -> dict:
    return {
        "tool_count": measurement["tool_count"],
        "catalogue_chars": measurement["catalogue"]["chars"],
        "catalogue_approx_tokens": measurement["catalogue"]["approx_tokens_chars_div_4"],
        "calls": {c["name"]: c["response"]["chars"] for c in measurement.get("calls", [])},
    }


def compare(current: dict, baseline: dict) -> list:
    pct = baseline.get("threshold_pct")
    if not isinstance(pct, (int, float)) or not 0 < pct <= 100:
        raise ValueError(f"threshold_pct must be a number in (0, 100], got {pct!r}")
    expected = baseline.get("profiles", {})
    failures = [f"profile '{p}' is in the baseline but was not measured" for p in expected if p not in current]
    for profile, row in current.items():
        if profile not in expected:
            failures.append(f"profile '{profile}' has no baseline; run with --update-baseline")
            continue
        before, after = expected[profile]["catalogue_chars"], row["catalogue_chars"]
        if after > before * (1 + pct / 100):
            failures.append(f"profile '{profile}' catalogue grew from {before} to {after} chars "
                            f"(+{(after - before) / before:.1%}, limit {pct}%)")
    return failures


def measure(profile: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "m.json"
        subprocess.run([sys.executable, str(ROOT / "scripts" / "measure_mcp_tokens.py"),
                        "--profile", profile, "--output", str(out)], check=True, stdout=subprocess.DEVNULL)
        return json.loads(out.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()
    current = {p: summarize(measure(p)) for p in PROFILES}
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else {}
    if args.update_baseline:
        baseline = {"threshold_pct": baseline.get("threshold_pct", 10),
                    "profiles": {p: {"tool_count": r["tool_count"], "catalogue_chars": r["catalogue_chars"]}
                                 for p, r in current.items()}}
        args.baseline.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    failures = compare(current, baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"threshold_pct": baseline["threshold_pct"], "profiles": current,
                                       "failures": failures}, indent=2) + "\n", encoding="utf-8")
    for line in failures:
        print("FAIL", line)
    for p, r in current.items():
        print(f"{p}: {r['tool_count']} tools, {r['catalogue_chars']} chars (~{r['catalogue_approx_tokens']:.0f} tokens)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
