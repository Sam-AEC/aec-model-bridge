# Project board

The GitHub Project "AEC Model Bridge" (owner `Sam-AEC`, public, linked to this repository) shows open issues and pull requests by status, priority and milestone. Labels are the source of truth. `scripts/project_board.py` copies them into project fields.

## Fields

| Field | Values | From |
|---|---|---|
| Status | Todo, In Progress, Done | Built in. Pull requests start as In Progress. Closing or merging sets Done through the built-in workflows. |
| Priority | P0 to P3 | `priority:` label |
| Size | S, M, L | `size:` label |
| Area | addin, approval, ci, docs, install, interop, mcp, modules, panel, qa, security, server, snapshot | `area:` label; the first in this order when an item has several |
| Owner | Maintainer, Community, Open | `status: maintainer-only` gives Maintainer; `good first issue` or `help wanted` gives Community; other issues are Open |
| Needs Revit | Yes, No | `status: needs-live-verification` |
| Milestone | 1.6, Backlog | Built in, from the issue milestone |

## Set up or refresh

Run where `gh` is signed in as `Sam-AEC`:

```bash
gh auth refresh -s project
python scripts/project_board.py --dry-run
python scripts/project_board.py
```

The script is idempotent: it reuses the project, creates missing fields, adds new items and resets field values from labels.

## Views (create by hand once)

The API cannot create views. In the project, add:

1. **Board**: layout Board, group by Status.
2. **1.6**: layout Table, filter `milestone:1.6`, group by Priority, sort by Size.
3. **Maintainer queue**: layout Table, filter `owner:Maintainer is:open`.
4. **Needs Revit**: layout Table, filter `"needs revit":Yes is:open`.
5. **Contributors**: layout Board, filter `owner:Community is:open`, group by Area.
6. **Roadmap**: layout Roadmap, group by Milestone.

## Workflows (turn on once)

In the project, Workflows:

- Auto-add to project: repository `Sam-AEC/aec-model-bridge`, filter `is:issue,pr is:open`.
- Item closed and Pull request merged: set Status to Done (on by default).
- Item reopened: set Status to Todo.

New items get fields on the next script run.
