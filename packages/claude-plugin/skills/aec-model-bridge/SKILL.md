---
name: aec-model-bridge
description: How to operate the AEC Model Bridge Revit MCP server with few calls and small results. Use at the start of any task that reads or changes a Revit model through AEC Model Bridge tools. Covers context and approval mode, tool profiles, finding tools, snapshot queries, compact output, plans and error kinds.
---

# Operate AEC Model Bridge efficiently

AEC Model Bridge exposes a Revit model through MCP tools. Writes go through
plans that a person approves. This skill keeps calls few and results small.
For the review and approval steps in detail, also use the `revit-review` skill
when it is installed.

## 1. Read context once

Call `revit_get_context` once at the start of a task. Read from `server`:

- `server.dev_mode`: when true, the person enabled Dev mode for this session.
  Write tools are called directly, with no plan. Stay inside the scope the
  person gave and verify every change.
- `server.approval_mode`: `look_only` allows reads only. `ask_first` needs a
  plan that a person approves before any write. `auto` is a time-limited window
  that a person opened in the panel.
- `server.plans_required`, when present: when true, every write needs a plan,
  whatever the other fields say.

Do not call it again unless the person says Revit, the document or the mode
changed. If it reports `mock: true`, the data is sample data. Say so in every
report.

## 2. Know the profile

The server starts with one tool profile: `core` (smallest), `daily` or
`full` (all tools). A tool that the profile hides is not listed and is refused
with kind `tool_profile_blocked`. Only the person can change the profile and
restart the server.

Call `context_report` when you need the active profile, the listed tool count
or the context cost of the tool list. It also gives tips to use less.

## 3. Search before you guess

Do not guess tool names. Call `search_tools` with a few words, for example
`{"query": "door fire rating", "limit": 5, "include_schema": false}`. Each
match says whether the current profile shows it and, if not, which profile
does. Ask for schemas only for the tool you will call.

## 4. One snapshot, then compute

For any question about more than a few elements:

1. Call `snapshot_take` once. Scope it with `categories` on large models.
2. Answer with `snapshot_compute`: a pipeline of steps (join, where,
   group_by, aggregate, sort, select, limit) that returns only the result.
3. Reuse the same `snapshot_id` for follow-up questions. Take a new snapshot
   only after the model changed.

Use `snapshot_diff` to compare two snapshots. Do not read elements one at a
time with `revit_get_element_parameters` in a loop. The pipeline syntax is in
`docs/snapshot-compute.md`.

## 5. Ask for less

- On list reads such as `revit_list_elements`, pass `limit`, `offset` or
  `count_only`.
- Where the schema offers `response_options`, pass `fields` to keep only the
  paths you need. Read results are compact by default.
- In `snapshot_compute`, end with `select` and `limit`, and set `max_rows`.
- A result marked `truncated: true` was trimmed. Narrow the call; do not
  repeat it unchanged.

## 6. One plan per change set

When writes need a plan:

1. Collect every change for one purpose, then call `plan_actions` once with all
   actions. Do not make one plan per element.
2. Show the person the preview: elements, old values, new values, and the
   blast radius.
3. Stop. Ask the person to approve the plan in the AEC Bridge panel or with
   the `aec-model-bridge-approve` command. Never approve, reject or roll back a
   plan yourself. Those tools are not available to clients, and a call returns
   kind `human_only`.
4. After the person approves, call `execute_plan`. Use `list_pending_plans` to
   check plan state.
5. Confirm the change from the result, or read the values back. Never say a
   change was made until a result confirms it.

## 7. Read the error kind

A failed call returns `isError: true` and `structuredContent.error.kind`. A
module tool returns `ok: false` with `kind`, `message` and `hint`. Look the
kind up in `docs/error-catalogue.md`, which says when it happens and what to do.
The common ones:

- `approval_blocked`: no matching approved plan. Make a plan with
  `plan_actions` and ask the person to approve it. Do not retry unchanged.
- `tool_profile_blocked`: the profile hides the tool. Use a listed tool, or ask
  the person to switch the profile.
- `unknown_tool`: wrong name. Call `search_tools`.
- `bridge_error`: Revit is not reachable or the command failed. Call
  `revit_health` and tell the person.
- `human_only`: stop and ask the person.

## Install in other clients

The skill folder follows the Agent Skills format (a folder with `SKILL.md`).
Copy the `aec-model-bridge` folder:

- Claude Code: install the plugin with `/plugin marketplace add Sam-AEC/aec-model-bridge`
  and `/plugin install aec-model-bridge@aec-model-bridge`. The skill loads from
  the plugin. Or copy the folder to `.claude/skills/` in a project.
- Codex: copy the folder to `.agents/skills/` in the repository or to
  `~/.agents/skills/` for every repository. Older Codex docs name
  `.codex/skills/`. UNVERIFIED: check with `/skills` in Codex.
- Cursor: copy the folder to `.cursor/skills/` in the project. Cursor
  documents that it also reads `.claude/skills/` and `.codex/skills/`.
  UNVERIFIED in a live Cursor session.
