#!/usr/bin/env python3
"""Single source of truth for the AEC Model Bridge version.

The root VERSION file holds the release version (SemVer 2.0.0). This script
keeps every package manifest in step with it and gives CI and the release
workflow one thing to ask.

  python scripts/version.py show
  python scripts/version.py check [--tag v1.3.0]
  python scripts/version.py set 1.3.0
  python scripts/version.py bump minor        # major | minor | patch
  python scripts/version.py notes [1.3.0]     # changelog section for release notes

`set` and `bump` rewrite all manifests and turn the "## Unreleased" changelog
section into "## <version> - <today>". `check` exits 1 on any drift, so it can
gate CI and the tag-triggered release.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def numeric(version: str) -> str:
    """Four-part numeric form .NET needs for AssemblyVersion/FileVersion."""
    return ".".join(version.split("-")[0].split(".")) + ".0"


def _tag_url(v: str) -> str:
    return (
        "https://github.com/Sam-AEC/aec-model-bridge/releases/download/"
        f"v{v}/aec-model-bridge-{v}.mcpb"
    )


# (file, regex with the version in group "v", how to render the version)
# A pattern may match several times (server.json has two "version" keys).
TARGETS: list[tuple[str, str, object]] = [
    ("packages/mcp-server-revit/pyproject.toml", r'(?m)^version = "(?P<v>[^"]+)"', str),
    ("packages/mcp-server-revit/manifest.json", r'(?m)^  "version": "(?P<v>[^"]+)"', str),
    ("server.json", r'(?m)^    "version":  "(?P<v>[^"]+)"', str),
    ("server.json", r'(?m)^ +"version":  "(?P<v>[^"]+)",\s*\n\s*"transport"', str),
    ("server.json", r"releases/download/v(?P<v>[^/]+)/aec-model-bridge-", str),
    ("server.json", r"aec-model-bridge-(?P<v>[^/]+)\.mcpb", str),
    ("scripts/installer/AECModelBridge.iss", r"(?m)^AppVersion=(?P<v>.+?)\s*$", str),
    ("packages/revit-bridge-addin/RevitBridge.csproj", r"<Version>(?P<v>[^<]+)</Version>", str),
    ("packages/revit-bridge-addin/RevitBridge.csproj", r"<AssemblyVersion>(?P<v>[^<]+)</AssemblyVersion>", numeric),
    ("packages/revit-bridge-addin/RevitBridge.csproj", r"<FileVersion>(?P<v>[^<]+)</FileVersion>", numeric),
    ("packages/revit-bridge-addin/RevitBridge.csproj", r"<InformationalVersion>(?P<v>[^<]+)</InformationalVersion>", str),
    ("packages/navisworks-bridge-addin/NavisworksBridge.csproj", r"<Version>(?P<v>[^<]+)</Version>", str),
    ("packages/rhino-bridge-addin/RhinoBridge.csproj", r"<Version>(?P<v>[^<]+)</Version>", str),
    ("packages/powerbi-bridge-tool/PowerBIBridge.csproj", r"<Version>(?P<v>[^<]+)</Version>", str),
]


def read(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def current() -> str:
    version = read(VERSION_FILE).strip()
    if not SEMVER.match(version):
        sys.exit(f"VERSION '{version}' is not SemVer (MAJOR.MINOR.PATCH[-prerelease])")
    return version


def expected(render, version: str) -> str:
    return render(version)


def scan(version: str) -> list[str]:
    """Return one message per place that disagrees with `version`."""
    problems: list[str] = []
    for rel, pattern, render in TARGETS:
        text = read(ROOT / rel)
        matches = list(re.finditer(pattern, text))
        if not matches:
            problems.append(f"{rel}: pattern not found ({pattern[:40]}...)")
            continue
        for m in matches:
            want = expected(render, version)
            if m.group("v") != want:
                problems.append(f"{rel}: found {m.group('v')}, want {want}")
    for rel in ("server.json", "packages/mcp-server-revit/manifest.json"):
        json.loads(read(ROOT / rel))  # still valid JSON after edits
    return problems


def apply(version: str) -> None:
    for rel, pattern, render in TARGETS:
        path = ROOT / rel
        text = read(path)
        want = expected(render, version)
        text = re.sub(
            pattern,
            lambda m: m.group(0).replace(m.group("v"), want, 1),
            text,
        )
        write(path, text)
    write(VERSION_FILE, version + "\n")


def changelog_section(version: str) -> str | None:
    text = read(CHANGELOG)
    m = re.search(rf"(?ms)^## {re.escape(version)}\b[^\n]*\n(.*?)(?=^## |\Z)", text)
    return m.group(1).strip() if m else None


def roll_changelog(version: str) -> str:
    text = read(CHANGELOG)
    if changelog_section(version) is not None:
        return "changelog already has a section for this version"
    m = re.search(r"(?ms)^## Unreleased\s*\n(.*?)(?=^## |\Z)", text)
    if not m or not m.group(1).strip():
        return "changelog 'Unreleased' is empty - add release notes before tagging"
    today = datetime.date.today().isoformat()
    body = m.group(1).strip("\n")
    new = f"## Unreleased\n\n## {version} - {today}\n\n{body}\n\n"
    write(CHANGELOG, text[: m.start()] + new + text[m.end():])
    return f"changelog: Unreleased -> {version} - {today}"


def cmd_show(_: argparse.Namespace) -> int:
    print(current())
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    version = current()
    problems = scan(version)
    if args.tag and args.tag != f"v{version}":
        problems.append(f"tag {args.tag} does not match VERSION v{version}")
    if args.tag and changelog_section(version) is None:
        problems.append(f"CHANGELOG.md has no '## {version}' section for this release")
    if problems:
        print(f"Version drift against VERSION={version}:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("Fix with: python scripts/version.py set " + version, file=sys.stderr)
        return 1
    print(f"OK: all manifests at {version}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    if not SEMVER.match(args.version):
        sys.exit(f"'{args.version}' is not SemVer (MAJOR.MINOR.PATCH[-prerelease])")
    apply(args.version)
    print(f"Set {args.version} in {len({t[0] for t in TARGETS})} files + VERSION")
    if not args.no_changelog:
        print(roll_changelog(args.version))
    print("server.json fileSha256 is refreshed by build-release.ps1 -UpdateServerMetadata")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    major, minor, patch, _pre = SEMVER.match(current()).groups()
    major, minor, patch = int(major), int(minor), int(patch)
    if args.part == "major":
        major, minor, patch = major + 1, 0, 0
    elif args.part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    args.version = f"{major}.{minor}.{patch}"
    return cmd_set(args)


def cmd_notes(args: argparse.Namespace) -> int:
    version = args.version or current()
    body = changelog_section(version)
    if body is None:
        print(f"No CHANGELOG section for {version}", file=sys.stderr)
        return 1
    print(body)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show").set_defaults(func=cmd_show)
    p = sub.add_parser("check")
    p.add_argument("--tag", help="release tag to validate, e.g. v1.3.0")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("set")
    p.add_argument("version")
    p.add_argument("--no-changelog", action="store_true")
    p.set_defaults(func=cmd_set)
    p = sub.add_parser("bump")
    p.add_argument("part", choices=["major", "minor", "patch"])
    p.add_argument("--no-changelog", action="store_true")
    p.set_defaults(func=cmd_bump)
    p = sub.add_parser("notes")
    p.add_argument("version", nargs="?")
    p.set_defaults(func=cmd_notes)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
