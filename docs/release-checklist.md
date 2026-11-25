# Release checklist

Ordered list for shipping from `dev` to `main`. Section 2 has no PASS or FAIL recorded. Bounded read-only Revit 2024 checks passed; see [the live validation report](revit-addin-live-validation-2026-10-14.md). Mutating acceptance and other Revit years are UNVERIFIED. Known limits are in section 3 and in [security.md](security.md).

## 1. What CI proves

The workflow in `.github/workflows/ci.yml` runs on every push and pull request, and nightly. Pull requests run Python on Windows 3.11 and Ubuntu 3.13 and build the add-ins only when their C# folders change. Pushes to `main` and `dev`, the nightly run and manual runs use the full matrix (Windows 3.11, 3.12, 3.13; Ubuntu 3.12, 3.13) and every build. It proves:

- Python lint (`ruff check`), the Python test suite with coverage, version consistency (`scripts/version.py check`), `uv.lock` freshness and tool catalog generation.
- Repository metadata validation, wheel and sdist build, `twine check --strict`, and a smoke test of the built wheel in a clean venv.
- The Revit add-in and the Rhino bridge add-in compile (`dotnet build`).
- Workflow files pass `actionlint`.
- The doc tests, including the translated READMEs and install links, pass.

CI does not start Revit. Tests that touch Revit use mock providers.

## 2. Needs a live Revit

Run on a Windows machine with Revit, starting with the write test in section 5. Mark each PASS or FAIL.

1. First real write (for example `revit_set_parameter_value` through an approved plan). A crash here is the most important finding.
2. Undo behaviour. A plan of only parameter writes, moves and rotations runs as one `revit.execute_plan_batch` and should be one Ctrl+Z step named "AEC Model Bridge: <plan title> (<short id>)" (UNVERIFIED). Check it with a plan of two or more actions, check that a plan whose second action fails leaves the model unchanged, and check that other plans still take one Ctrl+Z per action. Check `rollback_plan`, which can skip actions that have no recorded before-value.
3. Two Revits open at once: requests reach the Revit the person means ([ADR 0014](adr/0014-multi-revit-routing.md), the "Several Revits" section of security.md). Also draft a plan in Revit A and run it in Revit B with the same file open: it must be refused as a different Revit process (issue #152, UNVERIFIED). Record the Revit version and commit.
4. The WebView2 panel loads, lists pending plans and approves one. Run `aec-model-bridge-approve show <plan_id>` for the same plan and compare it with what the panel showed.
5. Windows ACL on `%LOCALAPPDATA%\AECModelBridge\panel-hub.token`: only the current user has access. Windows does not re-verify the ACL on read.
6. The Revit 2024 Release build and authenticated panel backend passed on 14 October 2026. Build and run the net8 and net10 targets as well, and repeat the release checks on each supported year.
7. Verify the panel review card and explicit Dev mode (Settings, Dev mode). Dev must stay visibly enabled until switched off, audit its writes, and preserve read-mode guards, filesystem scope and supplied-plan checks.

## 3. Known limits (from security.md)

- Plans do not record the Revit that created them. Until fixed, a plan drafted in Revit A can run against Revit B.
- The client sends the raw token to whatever listens on 127.0.0.1:8787. On a shared machine another user could bind the port first.
- The hub caps request threads at `AEC_PANEL_MAX_THREADS` (default 32) and keeps 2 for `/execute`; over the cap a connection gets 503 with `Retry-After: 1` and no thread. Slow clients can still fill the other slots for up to 30 s per blocking read and delay non-`/execute` panel routes (UNVERIFIED with the live panel). MCP tool calls have per-tool timeouts and rate limits (UNVERIFIED in live Revit; see configuration-reference.md).
- Routed bridge clients: the routing lock no longer covers network calls, and a cached client is dropped when its Revit registry entry is gone or its `/health` fails three times in a row after failed calls. Tested with fakes only; UNVERIFIED with two live Revits.
- The dev panel displays validated plan reviews and blocks approval when a review is malformed, unsupported or too large. These browser checks passed; live plan approval acceptance remains pending. Compare the card with `aec-model-bridge-approve show <plan_id>` before approving.
- The panel Plans view lists pending plans only. `aec-model-bridge-approve show <plan_id>` works for a plan in any state; `proofs/` bundles exist only for plans that were executed or attempted.
- One-step undo covers only plans made of parameter writes, moves and rotations, run through `revit.execute_plan_batch` (UNVERIFIED in live Revit). Other plans undo with Ctrl+Z once per action. A revert plan (`plan_revert`) is approved like any other plan. `rollback_plan` is for people only and has no panel button or command-line command yet.
- Executing a plan costs O(n^2) in its action count; keep plans to a few hundred actions.
- Environment Auto, timed panel Auto and explicit panel Dev skip per-change approval. Dev has no expiry until switched off and applies across sessions sharing the workspace; it does not relax filesystem scope or read-mode guards. An explicitly supplied plan must still be valid and approved.
- The panel's `/execute` endpoint and the approval command line authenticate a local process, not a person. Do not give an AI client a shell on the same account if you rely on the gate.
- Write access to the workspace defeats the hash check.
- `plan_actions` captures a before-value only for `revit_set_parameter_value`.
- Some Navisworks and proxy tools may still be ungated; `revit_calculate_material_quantities` is ungated although the add-in marks it mutating (UNVERIFIED).
- Reject any pending revert plan drafted before upgrading.
- Cerberus is a planned feature inside AEC Model Bridge. It is not built.

## 4. Steps only the maintainer can do

1. Open the pull request from `dev` to `main` and review it. Do not merge until sections 1 and 2 are done or their gaps are accepted in writing.
2. Import the repository rulesets in GitHub settings.
3. Upload `docs/images/readme/social-preview.png` under repository Settings, General, Social preview. Only an admin can set it.
4. Enable the docs site: repository Settings, Pages, Build and deployment, Source: GitHub Actions. `.github/workflows/docs.yml` then deploys the MkDocs site on the next push to `main` that touches `docs/` or `mkdocs.yml` (or run the workflow by hand). Until then the deploy job fails and the site is not published.
5. Enable Discussions and create the categories in [maintainer/discussions.md](maintainer/discussions.md).
6. Have counsel review the licences and the rule packs ([rule-packs.md](rule-packs.md), [LICENSING.md](../LICENSING.md)).
7. Have native speakers review the 16 translated READMEs in `docs/i18n/`, including the Plans view note, approval and undo wording, and the current screenshot alt text. Source corrections do not establish native-language review.
8. Run a pilot with BIM coordinators. None has been run yet.
9. Tag and publish the release ([versioning.md](versioning.md)).

## 5. Minimal safe write test

The first real write against Revit since the `CreateTransaction` fix (#95). Builds without that fix could recurse until Revit crashed. Save other Revit sessions first. Use a scratch copy of a small model, never a project file.

1. Open the copy, close other Revit documents, and take a snapshot (`revit_extract_snapshot`).
2. Pick one element with an editable text parameter, for example a door's `Comments`. Note its element id and value.
3. Ask the assistant to plan exactly one `revit_set_parameter_value` (parameter `Comments`, value `dev-test-1`) with `plan_actions`. Do not let it execute. Dev and timed Auto must be off; approval mode must be `ask_first`.
4. In the Revit panel, check the arguments match what you asked for, then Approve. (Or `aec-model-bridge-approve`.)
5. Ask the assistant to run `execute_plan`.
6. Read the parameter in the Properties palette. Pass: value is `dev-test-1` and Revit did not hang or crash. Fail: freeze, close, a panel error, or an unchanged value.
7. Press Ctrl+Z once and read it again. Pass: the original value is back. If it took more steps, note how many. A one-action plan is one step either way; repeat with a two-action plan to check the one-step plan undo.
8. Record pass or fail for the write and for undo, any message text, and the lines in `%APPDATA%\AECModelBridge\Logs\bridge.jsonl` around that time.

Stop and report if step 5 or 6 fails.

## 6. Known limits of the dev drop

Accepted for now. Check they behave as described; do not report them as new findings. Limits already in section 3 are not repeated.

- The panel hub token authenticates a process, not a person. Any program running as your Windows user can read `panel-hub.token` and call `/execute`, including to approve a plan. The Host and Origin checks only stop browser pages.
- Approvals are not bound to a document or a view and never expire. A plan approved on one model can run after you switch documents if the element ids and arguments still match. Reject plans you no longer want.
- An action can stay `running` if the submit to Revit fails part-way or the process dies. It is consumed and will not rerun. After checking in Revit what it changed, abandon it with `aec-model-bridge-approve recover <plan_id> --reason "..."` and ask for a new plan.
- Navisworks and proxy tools: #105 gated five tools, not every mutating one.
- The add-in snapshot extractor does not fill every field, so several checks report "not enough data".
- The command line does not authenticate who is typing. A program that can run shell commands as you can run `aec-model-bridge-approve approve <id> --yes`.
- One hub serves all Revits. A plan drafted in one can be executed against another.
- Rollback can skip actions and only handles parameter writes.

## 7. Registries and stores

Nothing here is automated except the workflows named. Account steps belong to the maintainer.

| Target | How | State |
|---|---|---|
| Official MCP Registry | `server.json` is the source. `.github/workflows/publish-mcp.yml` publishes with GitHub OIDC when a release is published or on manual dispatch. Manual: `mcp-publisher login github`, `mcp-publisher publish`, after `mcp-publisher validate`. | Configured. Update `server.json` version, artifact URL and SHA-256 when the `.mcpb` changes. |
| PyPI | `.github/workflows/publish-pypi.yml` builds the wheel and sdist from the stable tag and publishes with Trusted Publishing (OIDC, no token) in the `pypi` environment. `release.yml` dispatches it after it creates a non-prerelease release; it also runs on `release: published` and by hand (`workflow_dispatch` with `tag`). Pre-release tags are refused. One-time setup is in [PyPI trusted publisher](#pypi-trusted-publisher). The `mcp-name` marker is in `packages/mcp-server-revit/README.md`. | Not published. Build, `twine check --strict` and a clean-venv install passed. |
| VS Code Marketplace, Open VSX | `.github/workflows/vscode-extension.yml` publishes when a non-pre-release GitHub release tag equals the extension version. Secrets: `VSCE_PAT`, `OVSX_PAT`. A store with no secret is skipped. Publisher and namespace `Sam-AEC` must exist. | Not published. Edit the extension README section "Build and install locally" before the first release. |
| winget | Templates in `packaging/winget/manifests/`, filled by `packaging/winget/fill_manifests.py <version>` from the published installer and `SHA256SUMS.txt`. The maintainer submits with `wingetcreate`; see [winget.md](winget.md). | Not submitted. |
| GitHub MCP Registry, VS Code gallery | Read from the official registry. `.vscode/mcp.json` gives a workspace install. | Follows the official registry. |
| Claude Code plugin | `.claude-plugin/marketplace.json` and `packages/claude-plugin/`. Users run `/plugin marketplace add Sam-AEC/aec-model-bridge`, then `/plugin install aec-model-bridge@aec-model-bridge`. Schema UNVERIFIED against `claude plugin validate`. | In the repository only. |
| Anthropic directory | Local `.mcpb` listings are reported as no longer accepted (UNVERIFIED); a local server goes in as a plugin through the developer portal. Needs the privacy policy in `privacy.md` (referenced from `manifest.json`). | Not submitted. |
| Glama | `glama.json` at the repository root on `main`; claim ownership while signed in as `Sam-AEC`. Re-claim after changing the file. The file lists maintainers only; the listing text is reported to come from the repository About text and README (UNVERIFIED), so those must say mock mode runs without Revit and live use needs Windows, Revit 2024 to 2027 and the add-in. | Not claimed. |
| Smithery | `smithery.yaml` builds the root `Dockerfile` in mock mode only. Its config description says mock mode runs without Revit and live use needs Windows, Revit 2024 to 2027 and the add-in. | Not listed. |
| Cline marketplace | Issue in the Cline marketplace repository with a 400x400 logo (none in the repo). Process UNVERIFIED. | Not submitted. |
| Other directories (PulseMCP, MCP.Directory, MCP.so) | Submit the repository URL; they read the README and registry data. | Not submitted. |

### PyPI trusted publisher

Do once, signed in to pypi.org and GitHub as the maintainer. Nothing in the repository can do these steps.

1. On GitHub: Settings, Environments, New environment, name `pypi`. Under deployment branches and tags, choose "Selected branches and tags" and add the tag rule `v*`. Optional: add yourself as a required reviewer, so each upload waits for a click.
2. On pypi.org: Account settings, Publishing, "Add a new pending publisher" (the project does not exist yet), GitHub tab. Enter PyPI project name `aec-model-bridge`, owner `Sam-AEC`, repository `aec-model-bridge`, workflow name `publish-pypi.yml`, environment name `pypi`. After the first upload the pending publisher becomes a normal trusted publisher on the project.
3. Check: run `publish-pypi.yml` by hand with the latest stable tag, or wait for the next stable release. A wrong environment or workflow name fails at the upload step with `invalid-publisher`.

The environment name on PyPI and in the workflow must match. If an older pending publisher exists with no environment, delete it and add the one above.

### OpenSSF Scorecard

`.github/workflows/scorecard.yml` runs weekly and on pushes to `main`, uploads results to code scanning and publishes them to the Scorecard API for the README badge. The badge shows "invalid" until the first run on `main` completes.

claude.ai on the web and phones accepts only remote HTTPS connectors, so it cannot reach a local Revit.

Release steps: attach the `.mcpb` and installer to the GitHub release (`scripts/version.py` keeps plugin and marketplace versions in step), update `server.json`, run `mcp-publisher validate`, publish, then check discovery through the registry API.

GitHub releases and tags v0.1.0 to v1.1.0 were deleted on 2026-10-09. The code stays in git history, and the MCP Registry still lists 1.0.1, 1.0.2 and 1.1.0 with dead download links. Releases v1.2.1 to v1.3.3 carry GPL-3.0 licence files in tag, wheel and `.mcpb`.
