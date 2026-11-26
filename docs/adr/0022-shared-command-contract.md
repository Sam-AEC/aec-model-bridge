# ADR 0022: Shared contract for add-in command inputs

## Status

Implemented in source. The Python side is tested. The generated C# file is not compiled in CI (no .NET there) and is not yet used by the add-in at runtime.

## Context

The Python server sends add-in commands such as `revit.create_wall` with a JSON payload. The C# add-in reads that payload with `GetProperty` and `TryGetProperty` in each handler. Nothing tied the two sides together. When a Python payload builder used a different key than the handler reads, the call reached Revit and failed there with a `KeyNotFoundException` or an `InvalidOperationException`.

Seeding the contract from the code found 10 provider tools whose payloads never match what the add-in reads, and 6 more that fail when an optional argument is left out (the builder sends `null` where the handler calls `GetInt32` or `GetDouble`). The test `test_provider_payload_builders_against_the_contract` lists them.

## Decision

- One file, `contracts/bridge-commands.json`, describes every add-in command: its name, `is_mutating`, and `params`, a JSON Schema for the payload. A command whose payload is not described has `"params": "unchecked"`.
- The schemas describe what the C# handler reads. A key the handler reads with `GetProperty` and no prior check is `required`. A key read with `GetInt32`, `GetInt64`, `GetDouble` or `GetBoolean` without a null check does not allow `null`. Integer fields are bounded to the C# type (Int32 or Int64). Enums are listed where the add-in rejects other values; the category enum is case-insensitive, as the add-in is. Where the add-in clamps a number silently, the contract refuses values outside the clamp range.
- Keys a schema does not list are allowed, because the server adds `request_id` and `action_id`.
- `scripts/gen_bridge_contract.py` generates `revit_mcp_server/bridge/contract_generated.py` (schemas and `validate_command`) and `packages/revit-bridge-addin/src/Bridge/BridgeContract.g.cs` (name constants and an `IsMutating` map). The C# file uses only `const string` fields and a `Dictionary<string, bool>`, so it builds on net48, net8 and net10.
- `BridgeClient.call_tool` calls `validate_command` before it sends. A payload that does not fit raises `BridgeContractError` and nothing is sent. Commands the contract does not list, and `unchecked` commands, pass unchanged. `MCP_REVIT_VALIDATE_BRIDGE_PAYLOADS=off` turns the check off; it is on by default.
- `BridgeCommandFactory.cs` is not changed. Tests check that the contract names and `IsMutating` flags match the `[BridgeCommand]` attributes, and that the generated files are current.

## Consequences

- A new or changed add-in command needs a contract entry. The tests fail until the names and flags agree and the generated files are regenerated.
- The 16 provider tools above now fail before sending, with a message that names the missing or wrong parameter, instead of failing inside Revit. Fixing each builder is separate work.
- The contract does not check what an escape hatch runs: `revit.execute_python` and `revit.invoke_method` are checked only for the fields the add-in reads.
- The add-in does not validate payloads against the contract. A later change can use `BridgeContract` constants in the `[BridgeCommand]` attributes.
- Whether the C# handlers behave as read from source is UNVERIFIED in a live Revit.
