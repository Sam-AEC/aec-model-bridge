#!/usr/bin/env python
"""Generate docs/error-catalogue.md from the server source.

What is catalogued:

- mcp kinds: the first argument of ``_tool_error(...)``, the ``error.kind`` the MCP layer sets.
- classes: public exception classes (not starting with ``_``) that derive from
  Exception, ValueError or RuntimeError, directly or through another such class.
- result kinds: the ``kind`` of an ``ok: false`` tool result. Found as the second
  argument of ``error_result(...)``, the first argument of ``RecipeError(...)``,
  and the keys of any module level ``*_HINTS`` dict.

Kinds that only a Revit script (.ipy) names are not found. Keep those out of the
catalogue until a Python module also names them.

The "when" and "what to do" text is hand written in scripts/error_catalogue_notes.json
(keys are ``mcp/<kind>``, ``class/<Name>``, ``kind/<kind>``). The script merges it with
what it finds in the source and fails if a code has no note or a note has no code.

Usage:  python scripts/make_error_catalogue.py [--check]
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "packages" / "mcp-server-revit" / "src" / "revit_mcp_server"
NOTES = ROOT / "scripts" / "error_catalogue_notes.json"
OUT = ROOT / "docs" / "error-catalogue.md"

BASE_EXCEPTIONS = {"Exception", "ValueError", "RuntimeError"}

SECTIONS = (
    ("mcp", "Tool error kinds", "Set by the MCP layer as `structuredContent.error.kind` when a call fails with `isError`."),
    ("kind", "Result kinds", "Set by module tools as `kind` in an `ok: false` result, next to `message`, `element_ids` and `hint`. Many tools share one kind."),
    ("class", "Exception classes", "Raised inside the server. The MCP layer turns most of them into one of the tool error kinds above, with the class message as text."),
)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def collect(src: Path = SRC) -> dict[str, list[str]]:
    """Return ``{"<section>/<code>": [source files]}`` for everything the source returns."""
    found: dict[str, set[str]] = {}
    classes: dict[str, tuple[set[str], str]] = {}

    def add(key: str, path: Path) -> None:
        found.setdefault(key, set()).add(_rel(path))

    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                bases = {b.id for b in node.bases if isinstance(b, ast.Name)} | {
                    b.attr for b in node.bases if isinstance(b, ast.Attribute)
                }
                classes[node.name] = (bases, _rel(path))
            elif isinstance(node, ast.Call):
                name = _call_name(node)
                args = node.args
                if name == "_tool_error" and args and _literal(args[0]):
                    add("mcp/" + str(_literal(args[0])), path)
                elif name == "error_result" and len(args) > 1 and _literal(args[1]):
                    add("kind/" + str(_literal(args[1])), path)
                elif name == "RecipeError" and args and _literal(args[0]):
                    add("kind/" + str(_literal(args[0])), path)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                if any(isinstance(t, ast.Name) and t.id.endswith("_HINTS") for t in node.targets):
                    for key in node.value.keys:
                        if key is not None and _literal(key):
                            add("kind/" + str(_literal(key)), path)

    exceptions = set(BASE_EXCEPTIONS)
    changed = True
    while changed:
        changed = False
        for name, (bases, _) in classes.items():
            if name not in exceptions and bases & exceptions:
                exceptions.add(name)
                changed = True
    for name in exceptions - BASE_EXCEPTIONS:
        found.setdefault("class/" + name, set()).add(classes[name][1])
    return {key: sorted(paths) for key, paths in sorted(found.items())}


def load_notes(path: Path = NOTES) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def problems(found: dict[str, list[str]], notes: dict[str, dict[str, str]]) -> list[str]:
    out = [f"{key}: found in source but has no entry in {NOTES.name}" for key in found if key not in notes]
    out += [f"{key}: entry in {NOTES.name} but no longer in source" for key in notes if key not in found]
    for key, note in notes.items():
        if not (note.get("when") and note.get("do")):
            out.append(f"{key}: entry needs both 'when' and 'do'")
    return out


def render(found: dict[str, list[str]], notes: dict[str, dict[str, str]]) -> str:
    lines = [
        "# Error catalogue",
        "",
        "Errors and refusals that the AEC Model Bridge server returns to clients, with what to do about each.",
        "This file is generated by `scripts/make_error_catalogue.py` from the source and from",
        "`scripts/error_catalogue_notes.json`. Do not edit it by hand.",
        "",
        "A tool failure reaches an MCP client in one of two shapes:",
        "",
        "- The MCP layer refused or failed the call. The reply has `isError: true` and `structuredContent.error.kind` is a tool error kind.",
        "- A module tool ran and returned `ok: false` with a result kind in `kind`, a `message` and a `hint`.",
        "",
        "Refusals never change the model. A refused write needs a new plan that a person approves.",
        "For logs and connection problems see [troubleshooting](troubleshooting.md).",
        "",
        f"Entries: {len(found)}.",
        "",
    ]
    for prefix, title, intro in SECTIONS:
        keys = [k for k in found if k.startswith(prefix + "/")]
        lines += [f"## {title}", "", f"{intro} Entries: {len(keys)}.", ""]
        for key in keys:
            note = notes[key]
            lines += [
                f"### `{key.split('/', 1)[1]}`",
                "",
                f"- When: {note['when']}",
                f"- What to do: {note['do']}",
                "- Source: " + ", ".join(f"`{p}`" for p in found[key]),
                "",
            ]
    return "\n".join(lines).rstrip("\n") + "\n"


def build() -> str:
    found = collect()
    notes = load_notes()
    bad = problems(found, notes)
    if bad:
        raise SystemExit("error catalogue is out of step:\n  " + "\n  ".join(bad))
    return render(found, notes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if docs/error-catalogue.md is out of date")
    args = parser.parse_args(argv)
    text = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("docs/error-catalogue.md is out of date. Run: python scripts/make_error_catalogue.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
