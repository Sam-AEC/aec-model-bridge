# Record and replay bridge sessions

The server can record the traffic between itself and the Revit add-in to a cassette file, and later serve those recorded responses without Revit. Use it to turn a live session into a regression test, or to reproduce a report without the original model.

## Record a session

Recording is off by default. It works only in bridge mode (`MCP_REVIT_MODE=bridge`). In mock mode the setting is ignored and a warning is logged.

```powershell
$env:MCP_REVIT_MODE = "bridge"
$env:MCP_REVIT_RECORD = "walls-check"
python -m revit_mcp_server
```

- `MCP_REVIT_RECORD` is a plain cassette name: letters, digits, `_` or `-`, at most 64 characters. The values `1`, `true`, `on` and `yes` pick a timestamped name such as `session-20261124-101500`.
- The cassette is written to `<workspace>/cassettes/<name>.jsonl`. The path is built with `safe_child`, so a name that is a path (`../x`, `C:\x`, `a/b`, `x.jsonl`) is refused. A refused name fails closed: every Revit call reports why, and nothing is sent to Revit unrecorded.
- Each bridge call is appended as one JSON line. Lines are added to an existing cassette of the same name.
- Calls routed by the panel hub to another Revit instance are recorded too.
- A failure to write the cassette (for example a full disk) is logged and does not fail the Revit call.
- Batches are off while recording. An approved plan runs one action at a time (no `revit.execute_plan_batch`, so no single undo step), and element reads are sent one command at a time (no `revit.batch`). Every write and read is then a line in the cassette, and replay serves it the same way.

### What is masked

Before a line is written:

- Secrets and tokens are replaced with `<redacted>`: values under keys such as `token`, `session_token`, `password`, `api_key`, `authorization`, `secret` and `code`, `token=...` text, and secret values registered by the process (such as the panel token).
- Local file paths (Windows drive paths, UNC shares, rooted and POSIX paths) are replaced with `<redacted-path>`.
- The local OS user name and email addresses are replaced with `<redacted-user>`, and so are the values of person fields such as `user`, `author`, `owner`, `created_by` and `last_saved_by`.

The live caller still gets the real, unmasked response. Only the cassette is masked.

### Review before sharing

A cassette from a real model can still contain model data: project and element names, parameter values, element ids, view and sheet names, family names and free text that the masking rules do not recognise. Masking is pattern-based and can miss a value. Open the file and review it before you share it, attach it to an issue or commit it.

## Cassette format

One JSON object per line:

| Key | Meaning |
|---|---|
| `seq` | Line number in recording order, starting at 1. |
| `v` | Cassette format version. This server reads version `1`. |
| `tool` | The MCP tool call that made this bridge request, when known. |
| `arguments` | The masked MCP tool arguments. |
| `arguments_redacted` | `true` when masking changed the arguments, so they may not replay at tool level. |
| `command` | The bridge command, such as `revit.list_levels`. `__get_result__` is a `revit_get_result` lookup. |
| `params` | The masked bridge parameters, without `request_id` and `wait_ms`. |
| `ok` | `true` for a response, `false` for an error. |
| `response` | The masked result, as the provider received it after unwrapping. |
| `error` | `{type, message, payload}` with `type` `CommandFailed` (Revit ran the command and it failed) or `BridgeError`. |

## Replay a cassette

```powershell
$env:MCP_REVIT_MODE = "replay"
$env:MCP_REVIT_CASSETTE = "C:\revit-workspace\cassettes\walls-check.jsonl"
python -m revit_mcp_server
```

- Replay never contacts Revit.
- A request matches a line on its command and its normalised parameters: masked the same way as when recording, `request_id` and `wait_ms` removed, key order ignored.
- Equal requests are served in recorded order. When they run out, the last one repeats.
- A request with no recorded match fails with: `Replay: cassette '<name>' has no recorded response for command '<command>' with these parameters.` Record the session again or add the line by hand.
- A recorded error is raised again: `CommandFailed` for a failed command, `BridgeError` otherwise.
- Without `MCP_REVIT_CASSETTE`, or with a file that cannot be read or parsed, every call fails with a plain error that names the problem.
- `revit_get_context` reports mock-style context in replay mode, because no Revit session exists. `revit_list_commands` is not available.
- Write tools still go through `plan_actions`, approval and `execute_plan`. A write in replay only returns the recorded response; nothing changes in any model.

## Use a cassette as a regression test

The test suite has a `cassette_replay` fixture (`packages/mcp-server-revit/tests/conftest.py`, helper in `tests/cassette_replay.py`):

```python
from pathlib import Path

CASSETTE = Path(__file__).parent / "fixtures" / "cassettes" / "walls-check.jsonl"


def test_walls_check_still_replays(cassette_replay):
    cassette_replay(CASSETTE)
```

For each line with a `tool`, the helper calls that tool through the Revit provider in replay mode. The provider builds the bridge request again from the recorded arguments, so a changed payload builder fails with "no recorded response". The tool output must equal the recorded response; pass `compare=False` for tools that change the add-in result (for example paged reads). Lines without a tool, or with `arguments_redacted`, are replayed at bridge level only. Recorded errors must be raised again. Every line must be used.

`tests/fixtures/cassettes/sample_session.jsonl` is a small hand-written example.

## Limits

- Recording sees what the provider sends through the bridge client. `/health` probes are not recorded.
- Masking happens before matching, so two requests that differ only in a masked value (two different paths) match the same line.
- Live-Revit recording is UNVERIFIED: the recorder is tested with a stand-in bridge client, not against a running Revit.

## Related

- [Configuration reference](configuration-reference.md)
- [Logging and audit](logging-and-audit.md)
- [Privacy](privacy.md)
