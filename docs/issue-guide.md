# Issue guide

How issues in this repository are titled, labelled, scheduled and closed. Written for contributors and coding agents that file or rewrite issues.

The forms live in `.github/ISSUE_TEMPLATE/`. The label list, with colours and descriptions, is `.github/labels.yml`.

## Forms

| Form | Use it for | Default labels |
| --- | --- | --- |
| Bug report | A tool, the add-in, the panel or the installer does not behave as documented. | `type: bug`, `status: triage` |
| Feature request | A task you cannot do today. Problem first, then the proposed behaviour. | `type: feature`, `status: triage` |
| Documentation | A page that is wrong, missing, out of date or unclear. | `type: docs`, `area: docs`, `status: triage` |
| Live Revit verification | Maintainers only. A run sheet for checks that need Windows and a live Revit. | `type: task`, `status: needs-live-verification` |

Security problems never go in a public issue. Use private reporting (see `SECURITY.md`).

## Titles

Format: `<area>: <what is wrong or what is added>`, in sentence case, without a trailing full stop.

- A bug title states the observed fault and the condition: `snapshot: sheet_view_audit reports 0 views because views are not captured`.
- A feature title states the capability in plain words, not the implementation: `qa: check door fire rating against the host wall rating`.
- A task title starts with a verb: `security: route the remaining snapshot_id path joins through safe_child`.
- A tracking issue starts with `Tracking:` and names the outcome: `Tracking: MCP protocol features for 1.7`.
- A live check starts with `verify:` and names the scope and Revit version: `verify: 1.6 release on Revit 2024 and 2026`.
- Use the tool, file or setting name in backticks when it is the subject. Do not put type, priority or version in the title; labels and milestones carry them.
- Avoid one or two word titles such as `IFC diff`. A reader of the issue list should know what changes without opening it.

## Body

Every issue body uses these sections, in this order. Leave a section out only when it has nothing true to say.

1. **Context**: what exists today and who is affected. One short paragraph.
2. **Problem** or **Motivation**: what fails, or what task is blocked. For a bug, quote the error and give steps.
3. **Evidence**: file paths with line numbers, commands and their output, live results with Revit version. Only facts that were observed. Mark anything not observed as UNVERIFIED.
4. **Proposed approach**: the change, the files it touches, and the tests that cover it. If there are two real options, list both with the recommended one first and the reason.
5. **Acceptance criteria**: a checklist (see below).
6. **Out of scope**: what this issue does not do, so reviewers can hold the line.
7. **Related**: links to issues, PRs, ADRs and docs.

Do not write "ask the owner" or "needs a decision" in the body. If the approach is not settled, state the options and the recommendation, and add `status: needs-design`. The discussion happens in the comments; the outcome goes into the body or an ADR.

## Acceptance criteria

- Write them as a Markdown checklist, one observable result per line.
- Each line can be checked by a named test, a command, or a single live run. "Works well" is not a criterion; "returns `complete=true` on the canonical fixture" is.
- State the negative case where it matters: what must still be refused, what old files must still load.
- Every behaviour change carries two standing criteria from `AGENTS.md`: a test, and one line under `## Unreleased` in `CHANGELOG.md`. A change to tools also regenerates `docs/tools-generated.md`.
- Every change that touches model writes carries: no write path skips `plan_actions`, human approval and `execute_plan`.
- If a criterion needs a live Revit, say so on that line. Code can merge with that line open; the issue then gets `status: needs-live-verification` and stays open until the check is recorded.

## Labels

Each issue has exactly one `type:` label, one or more `area:` labels and, once accepted, one `priority:` label. `size:` is optional. `status:` labels say what the issue waits on and are removed when the wait ends.

| Group | Labels | Meaning |
| --- | --- | --- |
| `type:` | `bug`, `feature`, `docs`, `task`, `tech-debt`, `tracking` | Kind of work. `task` covers review, verification and maintenance. `tracking` groups other issues. |
| `area:` | `approval`, `security`, `server`, `mcp`, `addin`, `panel`, `snapshot`, `qa`, `interop`, `modules`, `install`, `ci`, `docs` | Part of the system. All areas share one colour so they read as a group. |
| `priority:` | `P0`, `P1`, `P2`, `P3` | P0: a wrong result shown as correct, a security exposure or data loss. P1: blocks the milestone. P2: planned. P3: not planned. |
| `size:` | `S`, `M`, `L` | About a day, a few days, a week or more. `L` usually needs a design note first. |
| `status:` | `triage`, `needs-info`, `needs-repro`, `needs-design`, `blocked`, `in-progress`, `needs-live-verification`, `verified-live` | What the issue waits on. |
| contributor | `good first issue`, `help wanted` | See below. |
| `resolution:` | `duplicate`, `wontfix`, `invalid`, `as-designed` | Why an issue closed without a change. Add a comment with the reason. |
| `pr:` | `needs-review`, `ready-to-merge`, `conflicts`, `tests`, `refactor` | Pull requests only. |

Dependabot applies `dependencies`, `python`, `python:uv`, `.NET`, `github_actions` and `javascript` to its pull requests. Do not use them on issues.

## Good first issue

Apply `good first issue` only when all of these hold:

- It can be built and tested in mock mode on Linux, without Windows or Revit.
- The body names the files to change and the test file to extend.
- It touches one module or one doc, and does not change the approval gate.
- The acceptance criteria are complete; a newcomer does not need to make a design choice.

`help wanted` means the issue is accepted and open to outside contributors. Contributors comment on the issue before starting; see `CONTRIBUTING.md` for the licensing note on code contributions.

## Milestones

- A version milestone (for example `1.6`) holds the issues that must close, or be explicitly moved, before that release.
- `Backlog` holds accepted issues with no release planned.
- An issue without a milestone has not been triaged.
- At release time, open issues in the version milestone are either finished, moved with a comment, or block the release.

## Tracking issues

Open a tracking issue (`type: tracking`) when:

- a goal needs three or more issues, or spans the server, the add-in and the panel, or
- a release needs a set of live checks across several features.

A tracking issue states the goal, lists the child issues as a task list (`- [ ] #123`), and gives the exit criteria for the whole group. Child issues stay small and self-contained; the tracking issue holds no implementation detail. Close it when every item is done or moved out with a comment.

## Live verification

Behaviour that depends on Revit cannot be proven in CI. When code merges with a live check outstanding:

1. Keep the issue open with `status: needs-live-verification`, or list the check in the release's live verification issue.
2. Record the result with Revit version, model type and commit.
3. On PASS, replace the label with `status: verified-live` and remove UNVERIFIED from the affected docs. On FAIL, open a bug and link it.

`docs/release-checklist.md` section 2 lists the standing live checks.

## Closing

- Close through a pull request with `Fixes #N` in the description or commit.
- When closing without a change, add one `resolution:` label and a comment with the reason.
- `status: needs-info` issues close after 14 days without the requested information. They can be reopened when it arrives.
