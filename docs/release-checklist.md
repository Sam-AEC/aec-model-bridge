# Release checklist

Status: on the dev branch, not yet released.

An ordered list for shipping from `dev` to `main`. It reflects the dev branch as it is today. Nothing in this product has run in a live Revit session yet, so every Revit behaviour below is UNVERIFIED until a person checks it. Known limits are copied from [security.md](security.md) and [dev-test-plan.md](dev-test-plan.md).

## 1. What CI proves

The workflow in `.github/workflows/ci.yml` runs on every push and pull request. It proves:

- Python lint (`ruff check`), the Python test suite with coverage, version consistency (`scripts/version.py check`), `uv.lock` freshness and tool catalog generation.
- Repository metadata validation, wheel and sdist build, `twine check --strict`, and a smoke test of the built wheel in a clean venv.
- The Revit add-in and the Rhino bridge add-in compile (`dotnet build`).
- Workflow files pass `actionlint`.
- The doc tests, including the translated READMEs and install links, pass.

CI does not start Revit. Tests that touch Revit use mock providers.

## 2. Needs a live Revit

Run on a Windows machine with Revit, following [dev-test-plan.md](dev-test-plan.md). Mark each PASS or FAIL.

1. First real write (for example `revit_set_parameter_value` through an approved plan). A crash here is the most important finding.
2. Undo behaviour. The add-in names one transaction per action, so undoing a plan takes one Ctrl+Z per action. Check this, and check `rollback_plan`, which can skip actions that have no recorded before-value.
3. Two Revits open at once: requests reach the Revit the person means ([ADR 0014](0014-multi-revit-routing.md), the "Several Revits" section of security.md).
4. The WebView2 panel loads, lists pending plans and approves one. Run `aec-model-bridge-approve show <plan_id>` for the same plan and compare it with what the panel showed.
5. Windows ACL on `%LOCALAPPDATA%\AECModelBridge\panel-hub.token`: only the current user has access. Windows does not re-verify the ACL on read.
6. The C# in the recent routing and token work has not been compiled for net48, net8 and net10 together or run; build and run all three.

## 3. Known limits (from security.md and dev-test-plan.md)

- Plans do not record the Revit that created them. Until fixed, a plan drafted in Revit A can run against Revit B.
- The client sends the raw token to whatever listens on 127.0.0.1:8787. On a shared machine another user could bind the port first.
- No socket timeout or thread cap on the hub handler, so a slow unauthenticated body can hold a thread.
- The routed-bridge lock is held during a network initialise, and cached clients for dead Revits are not evicted.
- The panel approves review-bearing plans without showing the review. The panel plan-review card is in an unmerged pull request (#121) and is not shipped. Use `aec-model-bridge-approve show <plan_id>`, the place to see the full review, before approving from the panel.
- The panel Plans view lists pending plans only. `aec-model-bridge-approve show <plan_id>` works for a plan in any state; `proofs/` bundles exist only for plans that were executed or attempted.
- There is no one-step undo for a whole plan. Undo is Ctrl+Z once per action, or a revert plan (`plan_revert`) that is approved like any other plan. `rollback_plan` is for people only and has no panel button or command-line command yet.
- Executing a plan costs O(n^2) in its action count; keep plans to a few hundred actions.
- `MCP_REVIT_APPROVAL_MODE=auto` turns the approval gate off.
- The panel's `/execute` endpoint and the approval command line authenticate a local process, not a person. Do not give an AI client a shell on the same account if you rely on the gate.
- Write access to the workspace defeats the hash check.
- `plan_actions` captures a before-value only for `revit_set_parameter_value`.
- Some Navisworks and proxy tools may still be ungated; `revit_calculate_material_quantities` is ungated although the add-in marks it mutating (UNVERIFIED).
- Reject any pending revert plan drafted before upgrading.
- Cerberus ([ADR 0016](0016-cerberus-multi-agent-review.md)) is a planned feature inside AEC Model Bridge. It is Proposed and not built.

## 4. Steps only the maintainer can do

1. Open the pull request from `dev` to `main` and review it. Do not merge until sections 1 and 2 are done or their gaps are accepted in writing.
2. Import the repository rulesets in GitHub settings.
3. Upload `docs/images/readme/social-preview.png` under repository Settings, General, Social preview. Only an admin can set it.
4. Have counsel review the licences and the rule packs ([rule-packs.md](rule-packs.md), [LICENSING.md](../LICENSING.md)).
5. Have native speakers review the 16 translated READMEs in `docs/i18n/`, including the Plans view note. Only their tool-count numbers were updated; their approval paragraph still presents `rollback_plan` as something a person can run, which is not yet true, and none of the translations has been re-reviewed.
6. Run the pilot with BIM coordinators ([pilot-validation-plan.md](pilot-validation-plan.md)).
7. Tag and publish the release ([versioning.md](versioning.md)).
