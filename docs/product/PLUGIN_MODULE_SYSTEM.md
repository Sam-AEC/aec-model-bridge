# Plugin Module System

A **module** is the unit of product functionality: a manifest + a Python class in the hub that composes existing MCP tools into user-facing commands, plus optional UI cards and QA rules. C# changes are needed only when a module requires a new host-side primitive.

## 1. Discovery

Three sources, merged by the **ModuleRegistry** (new hub component, sibling of `ProviderRegistry`):

1. **Built-in:** `revit_mcp_server/modules/<name>/` shipped with the wheel.
2. **User/firm:** `%LOCALAPPDATA%\AECModelBridge\modules\<name>\` (workspace-sandbox rules apply).
3. **Entry points:** `[project.entry-points."aec_model_bridge.modules"]` for pip-installed third-party modules.

Load order: built-in → entry points → user (user wins on id collision, with a logged warning). A module = directory with `module.json` + `module.py` (+ `rules/*.yaml`, `ui/*.html`, `templates/`).

## 2. Manifest format (`module.json`)

```json
{
  "id": "qaqc_checker",
  "name": "QA/QC Checker",
  "version": "0.3.0",
  "schema_version": 1,
  "min_hub_version": "1.3.0",
  "description": "Rule-based model health checks and issue tracking.",
  "author": "AEC Model Bridge",
  "license": "GPL-3.0-or-later",
  "requires_providers": ["revit", "graph"],
  "requires_tools": ["revit_get_warnings", "graph_audit_disconnected"],
  "permissions": ["model.read", "workspace.write"],
  "commands": [
    {
      "id": "run_health_check",
      "title": "Run Health Check",
      "surface": ["ribbon", "panel", "mcp"],
      "mcp_tool": "qaqc_run_health_check",
      "execution_mode": "async",
      "is_mutating": false,
      "destructive": false,
      "input_schema": {
        "type": "object",
        "properties": {
          "ruleset": {"type": "string", "default": "core"},
          "categories": {"type": "array", "items": {"type": "string"}}
        }
      },
      "output_schema": {"$ref": "schemas/findings.json"}
    },
    {
      "id": "apply_fixes",
      "title": "Apply Suggested Fixes",
      "surface": ["panel", "mcp"],
      "mcp_tool": "qaqc_apply_fixes",
      "execution_mode": "async",
      "is_mutating": true,
      "destructive": false,
      "requires_plan": true,
      "permissions": ["model.write"]
    }
  ],
  "ui": {"panel_card": "ui/findings_card.html", "icon": "assets/icon.svg"},
  "hooks": {"validate": "module:QaqcModule.validate", "on_result": "module:QaqcModule.log_summary"}
}
```

## 3. Command exposure

- **To users:** `surface: ["ribbon"|"panel"]` → the add-in queries the hub's `module_list_commands` at panel startup and renders buttons/cards. Ribbon slots are limited; modules mark at most one command `ribbon_priority`.
- **To MCP:** every command with `"mcp"` surface registers as tool `<module_id>_<command_id>` through a `ModuleProvider` adapter, indistinguishable from provider tools and carrying the same metadata (`is_mutating`, `destructive`, `execution_mode`, `permissions`).

## 4. Permissions

Declared in manifest, enforced by the hub at call time; the panel shows them at install/enable time (consent screen).

| Permission | Grants |
|---|---|
| `model.read` | read-only provider tools |
| `model.write` | mutating tools — **always through ActionPlan gate** |
| `model.delete` | destructive-flagged tools (separate consent) |
| `workspace.write` | file output inside workspace sandbox (exists) |
| `net.local` | other local switches (rhino/navis/pbi) |
| `net.cloud` | speckle/aps/graph-API tools |
| `python.host` | `revit_execute_python` / `rhino_run_python` escape hatches — expert-mode only, off by default |

No permission → tool call rejected with a structured error naming the missing grant.

## 5. I/O schema, validation & logging hooks

- **Schemas:** JSON Schema per command (inline or `schemas/*.json`). Hub validates input before dispatch and output before return — a module that returns off-schema fails loudly in CI (contract test iterates all modules, same pattern as `test_provider_contract.py`).
- **`validate` hook:** runs at plan time — semantic checks beyond schema (e.g. "sheet numbers unique"). Returns `ok | warnings[] | blockers[]`; blockers stop the plan before approval.
- **`on_result` hook:** post-execution — audit summary lines, issue-store updates, notifications. Hooks are sync, budgeted (fail-open with logged warning on timeout).

## 6. Rollback strategy

Modules never implement rollback themselves. They declare per command:

- `reversible: "undo"` — single named transaction; Revit undo suffices (default).
- `reversible: "inverse"` — module's `build_inverse(plan, before_state)` produces a counter-plan (e.g. parameter restore).
- `reversible: "none"` — irreversible (file exports are trivially none; model deletes need `model.delete` + explicit confirm).

The approval gate persists `before_state` captured at plan time for inverse-capable commands.

## 7. Versioning

- Module semver + `schema_version` (manifest format) + `min_hub_version` gate.
- Hub refuses to load incompatible modules with a clear panel message, never a crash.
- Command input schemas are append-only within a major version (add optional fields only) — same discipline as switch Contract v2 (ADR 0002).

## 8. Example modules (target roster)

| id | Tier | Composes | New host primitives needed |
|---|---|---|---|
| `model_inspector` | MVP | snapshot query, `revit_list_*`, `revit_get_element_*` | `revit.extract_snapshot` (C#) |
| `selection_tools` | MVP | `revit_get/set_selection`, filters, save/restore selections | — |
| `parameter_manager` | MVP | `revit_batch_set_parameters*`, diff grid, CSV roundtrip | — |
| `qaqc_checker` | MVP | rules → findings → issue store → fix plans | — |
| `report_generator` | MVP | `exporter_*`, `export_excel`, templates | — |
| `viewsheet_automator` | MVP | 10 existing sheet/view tools | — |
| `familytype_mapper` | P1 | family audit, `revit_replace_family_type` mapping tables | family metadata extraction |
| `facade_configurator` | P1 | zone spec → placement plans, variant mgmt | adaptive-component batch placement |
| `rhino_bridge` | P1 | 19 `rhino_*` tools, spec import | — |
| `speckle_ifc_bridge` | P1 | `speckle_*`, `ifc_*`, mapper | — |
| `data_exporter` | P1 | SQLite/Excel/Parquet lanes | — |
| `agent_reviewer` | P2 | second-model review of pending ActionPlans (flags risky plans before human sees them) | — |

## 9. QA rule format (used by `qaqc_checker`)

```yaml
# rules/core/rooms.yaml
- id: room.unplaced
  title: Unplaced rooms
  severity: warning          # info | warning | error
  category: Rooms
  query: { source: snapshot, filter: { category: "OST_Rooms", placed: false } }
  message: "{count} unplaced room(s)"
  fix: null                  # or a command ref: { command: "qaqc.apply_fixes", args_template: {...} }

- id: door.no_fire_rating
  title: Doors missing fire rating
  severity: error
  category: Doors
  query:
    source: snapshot
    filter: { category: "OST_Doors", parameter: { name: "FireRating", empty: true } }
  fix:
    command: parameter_manager.batch_set
    args_template: { parameter: "FireRating", value_prompt: true }
```

Rule packs are versioned directories (`core`, firm packs under user modules dir); a rule that fails to evaluate is reported as `rule_error`, never crashes the run (cf. W7 failure cases).
