#!/usr/bin/env python
"""Changelog fragments: each change adds changes/<issue-or-branch>.md instead of editing CHANGELOG.md.

A fragment holds one or more bullet lines ("- ..."), written the way a CHANGELOG
line is. Two pull requests never touch the same file, so the changelog does not
conflict.

  python scripts/changelog.py check
      Fragments are well formed (CI runs this).
  python scripts/changelog.py build --version X.Y.Z
      Moves every fragment, plus any lines still under "## Unreleased", into a new
      "## X.Y.Z - <date>" section at the top of CHANGELOG.md and deletes the
      fragments. Run it at release time, before scripts/version.py.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
UNRELEASED_RE = re.compile(r"(?ms)^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)")
IGNORED = {"README.md", ".gitkeep"}


class ChangelogError(Exception):
    pass


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def fragment_files(root: Path) -> list[Path]:
    folder = root / "changes"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix == ".md" and p.name not in IGNORED)


def fragment_problems(name: str, body: str) -> list[str]:
    if not body.strip():
        return [f"changes/{name}: empty"]
    problems: list[str] = []
    seen_bullet = False
    for number, line in enumerate(body.split("\n"), 1):
        if not line.strip():
            continue
        if line.startswith("- "):
            seen_bullet = True
        elif seen_bullet and line[0] in " \t":
            continue
        else:
            problems.append(f"changes/{name}:{number}: lines must start with '- ' (got {line[:40]!r})")
    return problems


def check(root: Path) -> list[str]:
    folder = root / "changes"
    if not folder.is_dir():
        return []
    problems: list[str] = []
    for path in sorted(folder.iterdir()):
        if path.name in IGNORED or not path.is_file():
            continue
        if not NAME_RE.match(path.name):
            problems.append(f"changes/{path.name}: name must be letters, digits, '.', '_' or '-' and end in .md")
            continue
        problems.extend(fragment_problems(path.name, read(path)))
    return problems


def build(root: Path, version: str, today: str) -> str:
    if not VERSION_RE.match(version):
        raise ChangelogError(f"version {version!r} is not X.Y.Z")
    changelog = root / "CHANGELOG.md"
    text = read(changelog)
    if re.search(rf"(?m)^## {re.escape(version)}\b", text):
        raise ChangelogError(f"CHANGELOG.md already has a section for {version}")
    problems = check(root)
    if problems:
        raise ChangelogError("fragments are malformed:\n  " + "\n  ".join(problems))
    files = fragment_files(root)
    match = UNRELEASED_RE.search(text)
    parts = [match.group(1).strip("\n")] if match and match.group(1).strip() else []
    parts += [read(path).strip("\n") for path in files]
    if not parts:
        raise ChangelogError("nothing to release: no fragments in changes/ and nothing under '## Unreleased'")
    section = f"## Unreleased\n\n## {version} - {today}\n\n" + "\n".join(parts) + "\n\n"
    if match:
        text = text[: match.start()] + section + text[match.end() :]
    else:
        first = re.search(r"(?m)^## ", text)
        at = first.start() if first else len(text)
        text = text[:at] + section + text[at:]
    changelog.write_text(text, encoding="utf-8", newline="\n")
    for path in files:
        path.unlink()
    return f"CHANGELOG.md: {len(files)} fragment(s) and Unreleased lines moved to {version} - {today}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="fragments in changes/ are well formed")
    b = sub.add_parser("build", help="fold fragments into a new release section")
    b.add_argument("--version", required=True, help="release version, X.Y.Z")
    args = parser.parse_args(argv)
    if args.cmd == "check":
        problems = check(ROOT)
        if problems:
            print("Changelog fragments are malformed:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            print(
                "Fix: put one or more lines starting with '- ' in changes/<name>.md "
                "(see changes/README.md). Do not edit CHANGELOG.md for a new change.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {len(fragment_files(ROOT))} changelog fragment(s)")
        return 0
    try:
        print(build(ROOT, args.version, datetime.date.today().isoformat()))
    except ChangelogError as exc:
        print(f"changelog: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
