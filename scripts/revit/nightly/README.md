# Nightly live test

Runs on a self-hosted Windows runner with Revit (issue #295). Setup is in `docs/release-checklist.md`, section 8.

Files:

- `run.py`: the test. Without `--run` it prints a plan and makes no call. With `--run --self-approve` it uses the panel hub (`--hub`, default `http://127.0.0.1:8787`) pinned to `--pid`, reads the per-user panel token with the server's reader and never prints it.
- `prepare-scratch.ps1`: copies the canonical model to a scratch file, opens it in a fresh Revit, writes `pid`, `title` and `scratch_file` to `GITHUB_OUTPUT`.
- `cleanup-scratch.ps1`: stops that Revit process without saving and deletes the scratch file.
- `../../bench-addin.ps1`: the read-only benchmark; `run.py` merges its JSON through `--bench-json`.

Run by hand, from `packages/mcp-server-revit`, with Revit open on the scratch copy:

```powershell
uv run python ..\..\scripts\revit\nightly\run.py --run --self-approve --pid <revit pid> --expected-document <scratch title> --expected-guid <model guid> --element-id <id>
```

Safety rules in the code:

- The document must be a project whose title or path contains `scratch`, `disposable`, `acceptance` or `test`. Production and workshared documents are refused. There is no override.
- Approval mode must be Ask me first with Dev off. Auto, Dev and Look only stop the run before any write.
- `--self-approve` is required for any write. Without it the write checks are `NOT_RUN`.
- The unapproved plan must be refused by `execute_plan`. The run fails if it is not.
- If a step fails after the write, the runner tries the revert once and says in the report when the scratch copy still holds the test value.
- The report is written only below `artifacts/revit-nightly/` (ignored by git), redacted and capped at 100 KiB.

Exit codes: 0 for PASS or an offline plan, 1 for FAIL or NOT_RUN of a live run.

UNVERIFIED, live only: starting Revit with a file path, the registry and `/health` shape that `prepare-scratch.ps1` waits for, the add-in starting the panel hub, the exact snapshot comparison counts (one modified element, then none), and element and warning counts staying equal. Unit tests use a fake client (`tests/test_live_nightly.py`).
