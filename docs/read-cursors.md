# Read result cursors

A read-only tool result longer than the size cap is cut at list rows. The answer says how much was left out and how to get the rest. Write tools, plans, proofs, approvals, jobs and errors are never cut.

## The cap

- Default: 20,000 characters of result JSON (`DEFAULT_MAX_CHARS`).
- Server-wide: `MCP_REVIT_READ_MAX_CHARS` (characters, `0` = off). Read on each call.
- Per call: `response_options.max_chars` (`0` = off). It overrides the server value.
- The largest list in the result is cut first, at a row boundary. The answer stays valid JSON.

## A cut answer

| Field | Meaning |
| --- | --- |
| `truncated` | `true` when rows were left out. |
| `total` | Rows in the full list. |
| `returned` | Rows in this answer. |
| `truncated_field` | Dotted path of the list that was cut, for example `elements` or `data.rows`. |
| `also_trimmed` | Other lists that were cut, with their counts. Only the first list pages. |
| `cursor` | Opaque string for the next part. |
| `next` | One line on how to use `cursor` or `resource_uri`. |
| `resource_uri` | Present instead of `cursor` when the list was too large to keep in memory. |

When the result already has a key with one of these names, the markers move under `truncation`.

## Next part

Repeat the same tool with the same arguments and `fields`, and add the cursor:

```json
{"category": "Walls", "response_options": {"cursor": "rc...-120"}}
```

- The server returns the next rows from memory. The tool is not run again, so Revit is not asked twice.
- The part holds the cut list only, at its path, with `truncated`, `total`, `offset`, `returned` and, when rows remain, a new `cursor`.
- `max_chars` and `compact` may change between parts. Each part holds at least one row.
- A cursor can be repeated until it expires.

## Refusals

A cursor is refused with kind `invalid_cursor` and a plain message when:

- it expired. Cursors last `MCP_REVIT_READ_CURSOR_TTL` seconds (default 600, at most 3600);
- the server restarted. Cursors live only in the server process;
- the tool, arguments or `fields` differ from the call that issued it;
- it is malformed or points past the end.

Call the tool again without a cursor to start over.

## Storage limits

- At most 32 cursors, and about 16 million characters in total. The oldest go first.
- A cut list longer than 2 million characters is not kept in memory. The full redacted result is saved to `<workspace>/results/<id>.json` and the answer carries `resource_uri` (`aec://result/<id>`) plus an MCP resource link. Read it with `resources/read`.
- Only the newest 20 saved results are kept. Ids are checked with `safe_child`, so a link resolves only inside the workspace `results` folder.
- Saved and stored results are the redacted answer, never the raw provider output.

## Where it applies

Every read-only tool, including `revit_list_elements`, `revit_list_views`, `revit_list_families`, `revit_get_element_parameters`, `module_list_commands` and `snapshot_compute`. The five tools in `READERS` advertise `cursor` in their `response_options` schema; other read-only tools accept it without listing it. The list tools that take `limit` and `offset` still page in the provider; cursors page what the size cap cut.

Behaviour against a live Revit is UNVERIFIED; tests use mock and stub providers.
