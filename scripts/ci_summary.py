#!/usr/bin/env python3
"""Render a pytest JUnit file and a coverage.py XML report as GitHub step-summary markdown.

Usage: ci_summary.py --title "Python 3.11 on windows-latest" --junit junit.xml --coverage coverage.xml

Writes to $GITHUB_STEP_SUMMARY when set, otherwise to stdout. Never fails the build:
missing or malformed reports are reported in the summary instead.
"""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def junit_section(path: Path) -> list[str]:
    if not path.is_file():
        return ["_No JUnit report was produced (the test step did not run to completion)._"]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"_JUnit report is unreadable: {exc}_"]
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    seconds = sum(float(s.get("time", 0)) for s in suites)
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    lines = [
        "| Tests | Passed | Failed | Errors | Skipped | Time |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {totals['tests']} | {passed} | {totals['failures']} | {totals['errors']} | {totals['skipped']} | {seconds:.1f}s |",
    ]
    bad = [
        case
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    ]
    if bad:
        lines += ["", "**Failing tests**", ""]
        lines += [f"- `{c.get('classname', '')}::{c.get('name', '')}`" for c in bad[:25]]
        if len(bad) > 25:
            lines.append(f"- ... and {len(bad) - 25} more")
    return lines


def coverage_section(path: Path) -> list[str]:
    if not path.is_file():
        return ["_No coverage report was produced._"]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"_Coverage report is unreadable: {exc}_"]
    line_rate = float(root.get("line-rate", 0)) * 100
    branch_rate = float(root.get("branch-rate", 0)) * 100
    covered = int(root.get("lines-covered", 0)) + int(root.get("branches-covered", 0))
    valid = int(root.get("lines-valid", 0)) + int(root.get("branches-valid", 0))
    total = 100 * covered / valid if valid else 0.0
    lines = [
        "| Total (the gated number) | Line | Branch |",
        "| ---: | ---: | ---: |",
        f"| {total:.1f}% | {line_rate:.1f}% | {branch_rate:.1f}% |",
    ]
    weakest = []
    for cls in root.iter("class"):
        rate = float(cls.get("line-rate", 1)) * 100
        weakest.append((rate, cls.get("filename", "?")))
    weakest = [w for w in sorted(weakest)[:5] if w[0] < 100]
    if weakest:
        lines += ["", "<details><summary>Least covered files</summary>", ""]
        lines += [f"- `{name}`: {rate:.0f}%" for rate, name in weakest]
        lines += ["", "</details>"]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    args = parser.parse_args()

    out = [f"### {args.title}", "", "#### Tests", ""]
    out += junit_section(args.junit)
    out += ["", "#### Coverage (the floor is `fail_under` in packages/mcp-server-revit/pyproject.toml)", ""]
    out += coverage_section(args.coverage)
    text = "\n".join(out) + "\n\n"

    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
