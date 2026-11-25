# ADR 0021: Opt-in named-pipe transport to the Revit add-in

## Status

Implemented in source, opt-in. The C# add-in code is unbuilt in CI. Live Revit and live Windows behaviour, including the pipe ACL, is UNVERIFIED. Issue #281.

## Context

The Python server reaches the Revit add-in over HTTP on a loopback port. Any local process can connect to a loopback port, including processes of another Windows user on the same machine. The session token keeps out callers that cannot read the registry file, but the port itself is open to every local user. A Windows named pipe can carry an ACL, so the operating system refuses other users before any byte is read.

## Decision

- The add-in opens a named pipe beside the HTTP listener when the environment variable `AEC_BRIDGE_TRANSPORT` is `pipe` (read by Revit at start-up). HTTP stays on and remains the default for one release.
- Pipe name: `AECModelBridge-revit-<pid>-<32 hex>`. The pid identifies the Revit process; the random part is created in the process and published only after the first pipe instance exists, so another user cannot create the name first.
- The add-in writes the name as `pipe_name` in its registry entry (`%LOCALAPPDATA%\AECModelBridge\registry\revit-<pid>.json`). Older add-ins and add-ins without the variable write `null` or nothing.
- ACL: one allow entry, full control for the current user's SID (from `WindowsIdentity.GetCurrent()`). Inherited entries are removed. net48 uses the `NamedPipeServerStream` constructor that takes a `PipeSecurity`; net8 and net10 use `NamedPipeServerStreamAcl.Create`. Up to 4 pipe instances.
- Framing: a 4-byte little-endian unsigned length, then that many bytes of UTF-8 JSON. One request and one response per connection.
- Request: `{"method", "path", "headers": {"Authorization": "Bearer <session_token>"}, "body"}`. Response: `{"status", "body"}`. Routes, bodies, status codes and the token rule match HTTP: every path except `/health` needs the session token. The pipe has no legacy tokenless mode.
- Limits on both sides: a request frame is at most 5 MiB (the HTTP request limit); a response frame is at most 64 MiB. A larger declared length is refused before the body is read. The add-in answers an oversize request with status 413 and an oversize response with status 500.
- Requests go into the same `CommandQueue` and run on the Revit UI thread through the same `ExternalEvent` as HTTP requests. Workspace path checks run before a request is queued.
- The Python server selects the transport with `MCP_REVIT_BRIDGE_TRANSPORT` (`http` or `pipe`); when unset it reads `AEC_BRIDGE_TRANSPORT`, then uses `http`. Any other value makes the bridge unavailable with a plain error.
- With `pipe`, the server uses the `pipe_name` of the registry entry it selected. If the entry has no pipe name (older add-in, explicit `MCP_REVIT_BRIDGE_URL`, or Revit started without the variable), the server logs a warning and uses HTTP. On a system other than Windows, `pipe` is refused with a plain error.
- Before it sends the token, the client reads the pipe server's process id (`GetNamedPipeServerProcessId`) and refuses a pipe that is not served by the Revit pid in the registry entry.
- The registry session check also compares `pipe_name`, so a client bound to one Revit session never sends to a replacement.

## Consequences

- While HTTP stays on, the pipe does not close the loopback port. The security gain applies once HTTP can be turned off; that is a later change, after the pipe is verified in live Revit.
- The panel hub's instance routing (`routed_to`) follows the same setting: with `MCP_REVIT_BRIDGE_TRANSPORT=pipe`, a routed client uses the `pipe_name` of the registry entry it routes to, or warns and uses HTTP if there is none. The add-in's own calls to the hub (`HubClient`) still use HTTP.
- The framing is covered by Python tests with a fake framing server over a socket pair and by C# tests in `packages/revit-bridge-addin-tests` (`PipeFramingTests`). Source guards check the ACL, the opt-in switch, the token check and the queue path in `PipeBridgeServer.cs`.
- To verify in a live Windows session: the pipe exists only with `AEC_BRIDGE_TRANSPORT=pipe`, its DACL lists only the current user, a process of another user gets access denied, and tool calls work over the pipe in Revit 2024 (net48) and Revit 2025 or later (net8 and net10). When verified, remove the related known limit from `docs/security.md`.
