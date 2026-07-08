# MVP Execution Plan

Locked decisions (2026-07-08): audience = **normal Revit users first** (dockable panel + approvals); killer workflows = **inspect → validate → fix** (façade roundtrip deferred to Phase-2 flagship); targets = **Revit 2024 (net48) + 2025/26 (net8)**, multi-target already in `RevitBridge.csproj`.

## Build first (in order)

1. **Phase 0 cleanup** — the repo must stop contradicting itself before anything ships (README links, security.md, ports, 260 MB binaries, version drift).
2. **Approval gate + tool metadata** (P4) — the product's core promise; everything else hangs off it.
3. **Snapshot extraction** (P3.3 + P6) — one data layer that all three workflows query.
4. **Three killer workflows** as modules (P7, P10, P9 — in that order: read → validate → write).
5. **Dockable panel** (P16, parallel from step 3 behind fixed endpoint contracts).
6. **Installer** (P19 minimal) — a BIM manager must install without pip knowledge.

## Delay (explicitly)

Façade configurator (P11 — flagship demo *after* MVP proves the layer), RiR/GH components (P12), Speckle/Navisworks workflows beyond provider registration (P13), Power BI live lane, Parquet/DuckDB (P14 partial), orchestrator/recipes (P15), Dynamo, APS, remote MCP, marketplace.

## Do not overbuild

- **Module system:** discovery + manifest + permissions only; no marketplace, no sandboxing beyond the trust-model doc, no hot reload.
- **Panel:** chat + plan cards + findings + log. No dashboards, no settings sprawl, no theming.
- **QA rules:** 15 curated rules that are *right*, not 100 that are noisy.
- **Rollback:** undo + inverse-for-parameters. No general time-travel.
- **Snapshot:** bbox-level geometry refs only; no mesh pipelines in MVP.
- **Auth:** localhost bearer (Contract v2). No user accounts, no cloud.

## First 3 killer workflows

1. **W1 Ask the model** — NL question → snapshot query → answer with clickable element chips.
2. **W7 Model health check** — one click → 15-rule findings report → exportable, trackable (W9-lite issue list).
3. **W5 Batch parameters with approval** — filter → diff grid → approve → apply → rollback.

Demo arc (one sitting, canonical model): *ask "how many doors lack fire ratings?" → run health check, see it as a finding among others → fix all 37 via approved batch-set → re-check shows resolved → export Excel report → hit Undo/rollback to prove safety.*

## First 10 MCP tools (new/changed; the ~170 existing stay)

| # | Tool | Phase |
|---|---|---|
| 1 | `snapshot_take` | P6 |
| 2 | `snapshot_query` | P6 |
| 3 | `snapshot_diff` | P6 |
| 4 | `plan_actions` | P4 |
| 5 | `list_pending_plans` | P4 |
| 6 | `approve_plan` (panel-only surface; agents may not self-approve) | P4 |
| 7 | `rollback_plan` | P4 |
| 8 | `qaqc_run_health_check` | P10 |
| 9 | `qaqc_list_issues` | P10 |
| 10 | `export_excel` | P14.1 (pulled into MVP) |

Plus metadata backfill on all existing tools (P4.1) and `revit.extract_snapshot` on the C# side (P3.3).

## First 5 plugin UI commands (ribbon)

1. **Open Bridge Panel** 2. **Run Health Check** 3. **Review Pending Actions** (badge = pending count) 4. **Inspect Selection** 5. **Export Report**

## First semantic data schema

`amb.snapshot/1` exactly as `SEMANTIC_BIM_DATA_MODEL.md` §2 — ElementRecord + Relations (hosts/bounds/on_level/in_group/on_sheet) + TypeRecord. Delta/zone/variant schemas are frozen on paper but implemented post-MVP.

## First test model

Generator script (P17.1), not a binary: 5 levels, ~200 walls, 60 doors (12 missing FireRating), 40 windows, 25 rooms (3 unplaced, 2 unenclosed), 30 views (6 unnamed, 8 not on sheets), 10 sheets (2 duplicate numbers), 4 model groups, 2 in-place families, seeded warnings. Every seeded defect maps to exactly one core rule → golden findings file.

## First demo scenario

The demo arc above, recorded on the canonical model, driven entirely from the panel (no code visible) — this is also tutorial 2 and the flagship-pitch opener.

## First release checklist (v1.3.0)

- [ ] Phase 0 complete: no doc/code contradictions, versions reconciled, binaries purged (with Sam's approval)
- [ ] Contract v2 default; unauthenticated :3000 requires explicit opt-in
- [ ] All tools metadata-complete; `tools-generated.md` regenerated without "?"
- [ ] Approval gate: mutating call without approved plan is rejected (test-proven)
- [ ] 3 killer workflows green on canonical model goldens (CI or scripted local e2e)
- [ ] Panel drives all 3 workflows; hub-down/no-doc states handled
- [ ] Installer on clean Windows 11 + Revit 2024 and 2025 → tutorial 1 in <15 min
- [ ] Audit ledger records every mutation with plan/action ids; rollback demo passes
- [ ] Docs: quickstart, 3 tutorials, security model rewrite, module authoring stub
- [ ] `LICENSES/` DLL scan green; no `Co-Authored-By` trailers anywhere in release history
- [ ] Sam sign-off on demo recording
