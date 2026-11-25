# Add-in command contract

`contracts/bridge-commands.json` is the shared definition of the Revit add-in commands. The Python server and the C# add-in both use code generated from it. See [ADR 0022](adr/0022-shared-command-contract.md).

## File format

```json
{
  "contract_version": 1,
  "$defs": { "int32": { "type": "integer", "minimum": -2147483648, "maximum": 2147483647 } },
  "commands": {
    "revit.delete_element": {
      "is_mutating": true,
      "params": { "type": "object", "properties": { "element_id": { "$ref": "#/$defs/int32" } }, "required": ["element_id"] }
    }
  }
}
```

- `commands` is sorted by name. Names look like `revit.create_wall`.
- `is_mutating` must match the `IsMutating` flag of the `[BridgeCommand]` attribute in the add-in.
- `params` is a JSON Schema for the payload, or `"unchecked"` when the payload is not described. Unchecked commands are sent without a check.
- Supported keywords: `type`, `enum`, `minimum`, `maximum`, `minItems`, `pattern`, `items`, `properties`, `required`, `anyOf` and `$ref` to `#/$defs/<name>`. `x-ignore-case: true` makes an `enum` case-insensitive.
- Keys a schema does not list are allowed.
- An integer field refuses `5.0` and `true`, because the add-in's `GetInt32` refuses them.

## Generated files

Run after any change to the contract:

```bash
python scripts/gen_bridge_contract.py          # write
python scripts/gen_bridge_contract.py --check  # exit 1 if stale
```

| File | Content |
|---|---|
| `packages/mcp-server-revit/src/revit_mcp_server/bridge/contract_generated.py` | `COMMANDS`, `DEFS`, `validate_command(name, params)`, `is_mutating(name)`, `is_checked(name)` |
| `packages/revit-bridge-addin/src/Bridge/BridgeContract.g.cs` | `BridgeContract` name constants and the `IsMutating` dictionary |

The validator itself is `revit_mcp_server/bridge/contract_validate.py`.

## Validation in the bridge client

`BridgeClient.call_tool` checks the payload before it sends anything. A payload that does not fit raises `BridgeContractError` with each problem, for example `sheet_number is required and missing`. Nothing reaches Revit.

| Setting | Default | Effect |
|---|---|---|
| `MCP_REVIT_VALIDATE_BRIDGE_PAYLOADS` | on | `0`, `false`, `off` or `no` turns the check off. Any other value keeps it on. Read on each call. |

`BridgeClient(validate_payloads=False)` turns it off for one client.

## Tests

`packages/mcp-server-revit/tests/test_bridge_contract.py` checks that:

- the generated files are current;
- the contract lists exactly the commands registered with `[BridgeCommand]` in the add-in, with the same `IsMutating` flags;
- every command the Revit provider sends is in the contract;
- each provider payload builder fits the contract, with all arguments and with only the required ones. The `KNOWN_BUILDER_MISMATCH_*` lists are empty and must stay empty.

## Adding or changing an add-in command

1. Add or change the `[BridgeCommand]` handler in the add-in.
2. Add or change the entry in `contracts/bridge-commands.json`. Mark a key `required` only if the handler reads it with `GetProperty` and no check. Allow `null` only if the handler tolerates it.
3. Run `python scripts/gen_bridge_contract.py`.
4. Run `uv run pytest -q tests/test_bridge_contract.py` from `packages/mcp-server-revit`.
