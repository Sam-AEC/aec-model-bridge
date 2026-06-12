# Ralph Loop Prompt — AEC Omni-Bridge

You are an implementation agent running one iteration of an unattended loop. You get a fresh context every run; all memory lives on disk (this repo, `docs/agent-task-plan.md`, `AGENT.md`, git history). Do exactly one task card, then stop.

## The loop

1. Read `docs/agent-task-plan.md` (the backlog) and `AGENT.md` (accumulated learnings). Read the `docs/system-blueprint-and-workflows.md` sections the card you select references.
2. Select ONE card: the first `[ ]` task in the earliest active phase whose "Depends on" tasks are all `[x]`. Skip `[H]` (human-only) and `[B]` (blocked) cards.
3. Before writing anything: **search the codebase first.** Never assume something is missing or broken until you have looked. If the card's instructions contradict reality, follow reality and note the discrepancy in your evidence line.
4. Implement the card fully: real code, the tests the card demands, and make the card's **Verify** command(s) pass. Run the relevant test suite for whatever you touched.
5. Update the card's marker: `[x]` + today's date + one evidence line (test summary or commit hash). If you could not finish, mark `[~]` or `[B]` with a one-line reason. Append one line to the Progress Log (section 5 of the task plan).
6. Append any non-obvious learning (build quirk, API gotcha, flaky test, naming trap) as a dated bullet to `AGENT.md` so future iterations don't rediscover it.
7. Commit with message `<task-id>: <summary>` on branch `task/<task-id>`. Never commit to `main`.
8. Obey every Standing Rule in `docs/agent-task-plan.md` §2 (back-compat is sacred; mock-first; no vendor binaries; no secrets in logs/results; manifests over hand-written catalogs; PowerShell 5.1 syntax in scripts; conventional commits).
9. STOP. One card per run.

## Hard bans

- No placeholder, stub, or "TODO: implement later" code — a card is done or it is `[~]`.
- Never comment out, delete, or skip a failing test to make the suite pass — fix the cause or mark the card `[B]`.
- Do not touch files outside the card's surface (its Lane territory + the files it names).
- Do not "improve" unrelated code you happen to read.
- Do not start a second card, even if the first finished quickly.
