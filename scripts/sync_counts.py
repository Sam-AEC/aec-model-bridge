#!/usr/bin/env python
"""Rewrite every tool count claim from the real count (scripts/count_tools.py).

Covers what packages/mcp-server-revit/tests/test_tool_count_claims.py checks:
README.md (first screen, table, "N tools are listed"), docs/i18n/README.*.md
(table and the sentence under it), llms.txt and the header of
docs/mcp-token-budget.md.

Usage:  python scripts/sync_counts.py [--check]

Run it after adding or removing a tool, then run scripts/make_llms_full.py.
--check changes nothing and exits 1 when a claim is out of date.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

ROW_RE = re.compile(r"^\| [^|]+ \| (\d+) \|", re.MULTILINE)
NUMBER_RE = re.compile(r"(?<![\d.])\d{2,4}(?![\d.])")
HEAD_RE = re.compile(r"(?<![\d.])(\d{2,4}) tools\b")
LLMS_RE = re.compile(r"(Tools: )\d+( in the default setup.*?Revit has )\d+( of them)", re.DOTALL)
BUDGET_RE = re.compile(r"(exposes \*\*)\d+(\*\* tools)")


class SyncError(Exception):
    pass


def compute_counts() -> dict:
    import count_tools

    return count_tools.count_tools()


def table_values(counts: dict) -> list[int]:
    p = counts["by_provider"]
    named = [p["revit"], p["approval"], p["module"], p["rhino"], p["speckle"], p["navisworks"], p["ifc"]]
    return [*named, counts["tools"] - sum(named)]


def _table(rel: str, text: str, counts: dict) -> str:
    values = table_values(counts)
    if len(ROW_RE.findall(text)) != len(values):
        raise SyncError(f"{rel}: expected {len(values)} table rows '| name | count | ...', found {len(ROW_RE.findall(text))}")
    rows = iter(values)
    text = ROW_RE.sub(lambda m: m.group(0).replace(m.group(1), str(next(rows)), 1), text)
    last = list(ROW_RE.finditer(text))[-1]
    rest = text[last.end() :]
    line_end = rest.find("\n")
    pos = last.end() + (line_end if line_end >= 0 else len(rest))
    tail = text[pos:]
    m = re.search(r"(?m)^(?!\s*$)(?!\|)(.*)$", tail)
    if not m or not NUMBER_RE.search(m.group(1)):
        raise SyncError(f"{rel}: no sentence with the tool count under the table")
    line = NUMBER_RE.sub(str(counts["tools"]), m.group(1), count=1)
    return text[:pos] + tail[: m.start()] + line + tail[m.end() :]


def _readme(rel: str, text: str, counts: dict) -> str:
    cut = text.find("\n## ")
    head, body = (text, "") if cut < 0 else (text[:cut], text[cut:])
    if not HEAD_RE.search(head):
        raise SyncError(f"{rel}: first screen no longer states the tool count")
    head = HEAD_RE.sub(f"{counts['tools']} tools", head)
    return _table(rel, head + body, counts)


def _regex(rel: str, text: str, counts: dict, pattern: re.Pattern, repl: str) -> str:
    if not pattern.search(text):
        raise SyncError(f"{rel}: no longer states the tool count in the expected form")
    return pattern.sub(repl, text, count=1)


def _llms(rel: str, text: str, counts: dict) -> str:
    n, revit = counts["tools"], counts["by_provider"]["revit"]
    return _regex(rel, text, counts, LLMS_RE, rf"\g<1>{n}\g<2>{revit}\g<3>")


def _budget(rel: str, text: str, counts: dict) -> str:
    return _regex(rel, text, counts, BUDGET_RE, rf"\g<1>{counts['tools']}\g<2>")


def targets(root: Path) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = [("README.md", _readme)]
    found += [(p.relative_to(root).as_posix(), _table) for p in sorted((root / "docs" / "i18n").glob("README.*.md"))]
    found += [("llms.txt", _llms), ("docs/mcp-token-budget.md", _budget)]
    return found


def sync(root: Path, counts: dict, write: bool) -> list[str]:
    """Return the files whose claims differ from counts; rewrite them when write is true."""
    drift: list[str] = []
    for rel, fn in targets(root):
        path = root / rel
        if not path.is_file():
            raise SyncError(f"{rel}: file not found")
        raw = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        old = raw.replace("\r\n", "\n")
        new = fn(rel, old, counts)
        if new != old:
            drift.append(rel)
            if write:
                path.write_bytes((new.replace("\n", "\r\n") if crlf else new).encode("utf-8"))
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if a count claim is out of date")
    args = parser.parse_args(argv)
    try:
        counts = compute_counts()
        drift = sync(ROOT, counts, write=not args.check)
    except SyncError as exc:
        print(f"sync_counts: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if drift:
            print(f"Tool count claims are out of date (real count: {counts['tools']}):", file=sys.stderr)
            for rel in drift:
                print(f"  - {rel}", file=sys.stderr)
            print(
                "Fix: run `python scripts/sync_counts.py` (then `python scripts/make_llms_full.py`) and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: tool count claims match {counts['tools']}")
        return 0
    print(f"tools: {counts['tools']}; updated: {', '.join(drift) if drift else 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
