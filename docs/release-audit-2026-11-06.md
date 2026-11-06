# Open PR audit and release bundle, 6 November 2026

Repository: [Sam-AEC/aec-model-bridge](https://github.com/Sam-AEC/aec-model-bridge).
The audit processed 19 open pull requests in creation order. There were no open
issues in the repository search. Fourteen PR heads were already in development;
the five unique heads were assessed by their changes rather than merged blindly.
The captured reviews contained 41 threads, 35 still marked unresolved on GitHub.
An unresolved thread's GitHub state is not proof its finding remains in the code.

The bundle includes the preceding MCP token profiles and response optimizations,
the fixes below, and current `main` history. It retains the tested development
implementations where old main patches overlap newer tools or approval handling.
No Revit model writes or add-in deployment were performed during this audit.

## Oldest-to-newest disposition

| PR | Bundle treatment | Evidence and remaining acceptance scope |
| --- | --- | --- |
| [60](https://github.com/Sam-AEC/aec-model-bridge/pull/60) | Integrated with fixes | Correct hub recovery/retry, transport errors, malformed diagnostics, and Codex-only readiness. Browser tests cover setup behavior; live WebView2 acceptance remains. |
| [61](https://github.com/Sam-AEC/aec-model-bridge/pull/61) | Integrated with fixes | Confined verified script/plan reads, strict source decoding, explicit runner failures. The Revit-side pyRevit runner is still absent; discovery/planning do not establish executable runner support. A failed consumed action requires a new approved plan. |
| [64](https://github.com/Sam-AEC/aec-model-bridge/pull/64) | Integrated with fixes | Clears stale previews, uses 64-bit IDs and reacquires the active view after zooming. Compiles; live temporary-isolate/worksharing behavior remains unverified. |
| [65](https://github.com/Sam-AEC/aec-model-bridge/pull/65) | Integrated with fixes | Migrates persisted QA issues to rule-pack scope, preserves colliding rule IDs, refreshes findings and rejects unsupported filter combinations. |
| [71](https://github.com/Sam-AEC/aec-model-bridge/pull/71) | Integrated with fixes | Explicit allowlists are not widened; launcher defaults follow the effective workspace. Fresh-directory handling was already present. |
| [76](https://github.com/Sam-AEC/aec-model-bridge/pull/76) | Integrated with fixes and limitations | Confines snapshot IDs, labels mock data, refuses live synthetic fallback and purge guesses from incomplete captures. Full loaded-type/CAD extraction remains a producer gap. |
| [77](https://github.com/Sam-AEC/aec-model-bridge/pull/77) | Integrated with fixes and limitations | Uses view-side sheet placement and discloses partial captures. Full view population and viewport relationships remain a producer gap. |
| [78](https://github.com/Sam-AEC/aec-model-bridge/pull/78) | Integrated with fixes and limitations | Refuses truncated/dirty/mismatched comparisons; handles raw parameters and mixed location evidence. Producer emits SI point locations, rotation and dirty markers. Unsupported curves remain explicit missing evidence. |
| [81](https://github.com/Sam-AEC/aec-model-bridge/pull/81) | Integrated with fixes and limitations | Avoids inventing missing door-room relationships, resolves room number/UID identity, discloses incomplete Area/capture data. The producer preserves room Area through its SpatialElement exemption; complete door-room relationships still require producer work. |
| [84](https://github.com/Sam-AEC/aec-model-bridge/pull/84) | Integrated with fixes and limitations | Stable names and built-in aliases survive typed serialization; field-specific length errors and incomplete naming coverage are reported. Full model-view population remains incomplete. |
| [92](https://github.com/Sam-AEC/aec-model-bridge/pull/92) | Superseded | Current per-user token authentication plus Host, Origin and content-type validation supersedes the old per-launch-token patch. Retained the newer implementation. |
| [94](https://github.com/Sam-AEC/aec-model-bridge/pull/94) | Already integrated | Shared HTTP clients and lazy provider imports are retained, including during the SDK backport. |
| [96](https://github.com/Sam-AEC/aec-model-bridge/pull/96) | Integrated with fixes | Adds a support-question route and corrects the security support table. Existing contribution/licensing policy remains unchanged. |
| [97](https://github.com/Sam-AEC/aec-model-bridge/pull/97) | Integrated with fixes | Corrects privacy/script-boundary claims, mock/live instructions, VSIX artifact selection and release-driven extension publishing. |
| [100](https://github.com/Sam-AEC/aec-model-bridge/pull/100) | Integrated with fixes | Removes license-text truncation, skips version-mismatched texts and removes local NuGet-cache dependence. Notices regenerated from the updated locked environment. This is an engineering inventory, not legal review. |
| [101](https://github.com/Sam-AEC/aec-model-bridge/pull/101) | Superseded by tested port | Runtime dependencies are installed from the lock; the shipped environment supplies the release SBOM. Exact name/version validation, project-root representation, final checksums and manual-dispatch source matching are covered. |
| [103](https://github.com/Sam-AEC/aec-model-bridge/pull/103) | Superseded by corrected port | Adds current setup, troubleshooting and FAQ pages with human approvals, authenticated diagnostics, shared workspace and uvx instructions. |
| [126](https://github.com/Sam-AEC/aec-model-bridge/pull/126) | Superseded by surgical port | Corrects review-panel and bounded live-validation claims in README and 16 translations. Avoids restoring stale counts and removed documents from the broad historical merge. |
| [131](https://github.com/Sam-AEC/aec-model-bridge/pull/131) | Superseded by port | Includes the requested five action upgrades while retaining newer existing pins and SHA pinning. |

## Verification and release acceptance

- Revit 2024, 2025, 2026 and 2027 compile against published API packages. The local
  installed Revit 2026 API assemblies require a newer framework than this target;
  the successful builds use `UseLocalRevit=false`. Compilation is not a live run.
- VS Code extension: 25 tests passed, TypeScript/bundle compilation passed, VSIX
  packaging passed, and npm audit reported zero known vulnerabilities. Packaging
  dependencies include patched MSAL, minimatch and qs with authentication tests.
- Actual portable Python 3.11.9 bundle: installation, imports and `pip check`
  passed; its MCP stdio smoke tests passed (3 tests). Its CycloneDX inventory
  matched all 70 installed distributions. The audit venv inventory matched 83.
- Release-inventory tests, workflow actionlint, PowerShell syntax, Python 3.11
  source grammar, generated tool catalog and version consistency are checked.
- Focused snapshot tests, browser setup tests and translated README/link tests
  cover the repaired paths. The combined suite and head CI checks provide the
  final integration result. The head must pass checks before merging the bundle.

The earlier live report proves bounded Revit 2024 read-only checks only. It does
not prove model writes, undo/rollback/recovery, every view/worksharing state, or
the other Revit years. These remain explicit acceptance tasks in
[the release checklist](release-checklist.md). No tag or published release is
created by this audit. Publishing remains a separate release operation.

The original checkout's Git index was write-restricted. Release integration was
therefore committed in a separate worktree without altering its ACLs or discarding
the original checkout's prepared changes.
