# ADR 0020: One definition per add-in command (single contract)

## Status

Proposed (issue #42). Step 1 is implemented: `tests/test_addin_command_references.py`.

## Context

Each Revit command is defined twice:

- C#: a method with `[BridgeCommand("revit.name", IsMutating = ...)]` in `packages/revit-bridge-addin/src/Bridge/*.cs`. `BridgeCommandFactory` builds the catalog by reflection. The payload is read by hand from a `JsonElement` in each method.
- Python: a `ProviderTool` with a JSON schema in `providers/revit.py`, an entry in `RevitProvider._tool_mapping` (tool name to command name plus a payload builder), and sometimes a module that names the command in `revit_raw_command` calls.

Nothing generates one side from the other. Drift is caught after the fact by tests that parse the C# source with regular expressions (`tests/test_addin_hub_contract.py`): mapped commands exist, mutating commands are gated, no duplicate names. `check_contract.py` is a different contract: the line protocol of the read-only check scripts.

Drift still possible today:

- A command name used outside `_tool_mapping` (module code, metadata, `module.json`) that the add-in does not declare. Fixed by step 1.
- An add-in command that no hub tool uses, found only by reading code. Listed by step 1.
- A payload field renamed on one side. Not detected.
- A schema that allows a value the C# side rejects, or the reverse. Not detected.

## Decision

Move towards one definition file per command, from which both sides are generated, in steps that each stand alone.

1. Name check (done). Every `"revit.<name>"` literal in the server source must exist as a `[BridgeCommand]` in the add-in, and every add-in command that no Python source names is listed in `KNOWN_UNUSED`. Both lists fail when they grow or go stale.
2. Payload field check. Extract the field names each C# command reads (`payload.TryGetProperty("x", ...)`, `GetString(payload, "x")` and similar helpers) with the same regex approach, and compare them with the keys each `_tool_mapping` payload builder produces for a sample call. Report fields read but never sent, and sent but never read.
3. Command manifest. One JSON file per command group under `packages/contract/commands/` with: name, `is_mutating`, `confirmation_required`, payload fields (type, unit, required, default, description), and the MCP tool name and description. Python reads it at start-up to build `ProviderTool` schemas and `_tool_mapping` for simple pass-through commands. A test checks the C# attributes against it until step 4.
4. C# generation. A source generator or a pre-build script turns the manifest into a typed payload record per command and the `[BridgeCommand]` attribute values, so the C# method takes a typed payload instead of a `JsonElement`. This needs the Windows build and is the most expensive step.

Rules for every step: the approval flag (`is_mutating`) comes from one place and the gate test keeps checking it; generated code is committed and a CI check fails when it is stale (as for `docs/tools-generated.md`).

## Consequences

- Step 1 runs in Linux CI with no .NET SDK. It found ten add-in commands that no Python source uses (recorded with reasons) and one known dangling name (`revit.run_pyrevit_script`, documented in `docs/pyrevit-bridge.md`).
- Steps 3 and 4 change how tools are written; hand-written tools with custom payload builders stay possible and are listed as exceptions in the manifest.
- UNVERIFIED: steps 2 to 4 are a design only.
