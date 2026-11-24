"""Create or update the "AEC Model Bridge" GitHub Project from the repository's issues.

Run on a machine where `gh` is signed in as the project owner with the project scope:

    gh auth refresh -s project
    python scripts/project_board.py            # create or update the board
    python scripts/project_board.py --dry-run  # print what would be set

The script is idempotent. It creates the project and its fields if they are
missing, links the project to the repository, adds every open issue and pull
request, and sets Priority, Size, Area, Owner and Needs Revit from labels.
Labels stay the source of truth; run it again after relabelling.
Views cannot be created through the API; see docs/project-board.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

OWNER = "Sam-AEC"
REPO = "Sam-AEC/aec-model-bridge"
TITLE = "AEC Model Bridge"
DESCRIPTION = "Roadmap and triage for AEC Model Bridge, the Revit MCP server with human-approved plans."
README = (
    "Board for AEC Model Bridge. Fields come from repository labels and are refreshed by "
    "`scripts/project_board.py`. Owner = Maintainer marks work only the maintainer can do. "
    "Needs Revit = Yes marks work that needs a live Revit check. "
    "See docs/project-board.md in the repository."
)

AREAS = [
    "addin", "approval", "ci", "docs", "install", "interop", "mcp",
    "modules", "panel", "qa", "security", "server", "snapshot",
]

FIELDS: dict[str, list[str]] = {
    "Priority": ["P0", "P1", "P2", "P3"],
    "Size": ["S", "M", "L"],
    "Area": AREAS,
    "Owner": ["Maintainer", "Community", "Open"],
    "Needs Revit": ["Yes", "No"],
}


def fields_from_labels(labels: list[str], is_pr: bool = False) -> dict[str, str]:
    """Map repository labels to project field values. Missing values are left unset."""
    names = {label.strip().lower() for label in labels}
    values: dict[str, str] = {}
    for name in names:
        key, _, value = name.partition(":")
        value = value.strip()
        if key == "priority" and value.upper() in FIELDS["Priority"]:
            values["Priority"] = value.upper()
        elif key == "size" and value.upper() in FIELDS["Size"]:
            values["Size"] = value.upper()
        elif key == "area" and value in AREAS:
            # One Area per item; the first in AREAS order wins for a stable result.
            current = values.get("Area")
            if current is None or AREAS.index(value) < AREAS.index(current):
                values["Area"] = value
    if "status: maintainer-only" in names:
        values["Owner"] = "Maintainer"
    elif names & {"good first issue", "help wanted"}:
        values["Owner"] = "Community"
    elif not is_pr:
        values["Owner"] = "Open"
    values["Needs Revit"] = "Yes" if "status: needs-live-verification" in names else "No"
    return values


def fields_to_clear(values: dict[str, str]) -> list[str]:
    """Managed fields with no value from the current labels; their old value is cleared."""
    return [name for name in FIELDS if name not in values]


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        sys.exit(f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def gh_json(*args: str):
    return json.loads(gh(*args) or "null")


def find_or_create_project() -> tuple[int, str]:
    projects = gh_json("project", "list", "--owner", OWNER, "--limit", "100", "--format", "json")
    for project in projects.get("projects", []):
        if project.get("title") == TITLE:
            return project["number"], project["id"]
    created = gh_json("project", "create", "--owner", OWNER, "--title", TITLE, "--format", "json")
    return created["number"], created["id"]


def ensure_fields(number: int) -> dict[str, dict]:
    def load() -> dict[str, dict]:
        data = gh_json("project", "field-list", str(number), "--owner", OWNER, "--limit", "100", "--format", "json")
        return {f["name"]: f for f in data.get("fields", [])}

    fields = load()
    for name, options in FIELDS.items():
        if name not in fields:
            gh("project", "field-create", str(number), "--owner", OWNER, "--name", name,
               "--data-type", "SINGLE_SELECT", "--single-select-options", ",".join(options))
    return load()


def open_items() -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        batch = gh_json("api", f"repos/{REPO}/issues?state=open&per_page=100&page={page}")
        if not batch:
            return items
        items.extend(batch)
        page += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print field values and change nothing")
    args = parser.parse_args(argv)

    issues = open_items()
    if args.dry_run:
        for issue in issues:
            values = fields_from_labels([label["name"] for label in issue["labels"]], "pull_request" in issue)
            print(f"#{issue['number']}: {values}")
        print(f"{len(issues)} open issues and pull requests")
        return 0

    number, project_id = find_or_create_project()
    gh("project", "edit", str(number), "--owner", OWNER, "--description", DESCRIPTION,
       "--readme", README, "--visibility", "PUBLIC")
    subprocess.run(["gh", "project", "link", str(number), "--owner", OWNER, "--repo", REPO],
                   capture_output=True)  # Already linked is fine.
    fields = ensure_fields(number)

    for issue in issues:
        item = gh_json("project", "item-add", str(number), "--owner", OWNER,
                       "--url", issue["html_url"], "--format", "json")
        values = fields_from_labels([label["name"] for label in issue["labels"]], "pull_request" in issue)
        if "pull_request" in issue and "Status" in fields:
            values["Status"] = "In Progress"
        for name, value in values.items():
            field = fields.get(name)
            option = next((o for o in (field or {}).get("options", []) if o["name"] == value), None)
            if option is None:
                continue
            gh("project", "item-edit", "--id", item["id"], "--project-id", project_id,
               "--field-id", field["id"], "--single-select-option-id", option["id"])
        # Labels are the source of truth: clear a managed field whose label was removed.
        for name in fields_to_clear(values):
            if name in fields:
                gh("project", "item-edit", "--id", item["id"], "--project-id", project_id,
                   "--field-id", fields[name]["id"], "--clear")
        print(f"#{issue['number']} {values}")

    print(f"Done: {len(issues)} items on https://github.com/users/{OWNER}/projects/{number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
