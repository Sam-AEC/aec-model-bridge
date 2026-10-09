# ADR 0014: Routing to the right Revit when several are open

## Status
Proposed. This record describes problems found by reading the code. None of them has been reproduced in a live Revit session yet, and no fix is built.

## Context
People run more than one Revit at the same time: Revit 2024 for an older project and Revit 2026 for a new one, or two sessions of the same year. The assistant and the panel must always act on the Revit the person means.

How it works today, read from the code:

- **Each add-in picks a free port.** `BridgeServer.Start` asks the operating system for an unused loopback port, releases it, then starts its HTTP listener on that port. It writes a registry file under `%LOCALAPPDATA%\AECModelBridge\registry` with the Revit year (`host_version`), the process id, a session token and the start time. It deletes the file when it stops.
- **The hub reads the registry.** `bridge/discovery.py` lists the files, drops entries whose process is gone, and sorts by start time. `select_switch` returns the newest live entry, optionally filtered by Revit year.
- **The hub chooses once.** `RevitProvider.__init__` calls `_build_bridge` a single time and keeps the endpoint and token for the life of the hub process.
- **MCP clients can pin a year.** The `MCP_REVIT_HOST_VERSION` setting narrows the choice to one Revit year. Without it, the newest instance wins.
- **The hub starts the AI client's tools in a separate process.** The `/agent/chat` endpoint calls `agent_bridge.run_agent_turn`. That launches the Claude or Codex CLI, and the CLI starts its own `revit_mcp_server.mcp_server` process over stdio. The Revit add-in does not start that process and does not know its pid. Its `RevitProvider` runs the same registry lookup as the hub does, so it takes the newest live entry unless `MCP_REVIT_HOST_VERSION` narrows it. The same is true for any MCP client the user configures by hand.
- **The shared hub belongs to whichever Revit launched it.** `PanelHubLauncher.EnsureRunning` runs once at startup. It skips the launch when `/health` answers. `App.OnShutdown` calls `StopIfLaunched`, which kills the hub only if this Revit started it. Nothing relaunches the hub later.
- **The registry identity is a pid.** The file is named `revit-{pid}.json`. Its fields are `pid`, `started_at` (the bridge server's start time), and `session_token`. `is_pid_alive` asks Windows whether a process with that pid exists, nothing more.
- **The panel shares one hub.** The panel hub listens on fixed port 8787. `PanelHubLauncher` does not start a new hub when one already answers. The panel's `HubClient` posts `tool` and `arguments` to `/execute` and nothing that says which Revit it belongs to.

## Problems

1. **A restarted Revit leaves the hub talking to a dead port.** A new Revit gets a new port and token. A hub that is still running keeps the old ones until it is restarted.
2. **Two panels can drive one Revit.** With Revit 2024 and 2026 both open, the second Revit finds the hub on 8787 already running and attaches to it. The hub holds one bridge, so both panels act on the same Revit, whichever the hub picked when it started. An approval clicked in the 2024 panel could run in the 2026 model.
3. **Two sessions of the same year cannot be told apart by year.** A year pin picks the newest of the two.
4. **The AI client's own tool server can pick the wrong Revit.** A chat started from the older Revit's panel goes through the hub's `/agent/chat`, which starts a CLI, which starts a separate MCP server. That server has no idea which Revit the panel belongs to, so it takes the newest one. Routing by process id inside the hub does not reach it.
5. **The hub dies with the Revit that launched it.** Close the first Revit and the hub goes with it. Every other panel loses its connection, and nothing restarts the hub.
6. **A process id can be reused.** Windows may give a dead Revit's pid to a new process. A plan tied to "pid plus document" could match a later session.
7. **A small race when choosing the port.** The port is released before the listener binds it, so another program can take it in between. The listener then fails to start, and nothing retries.

Problem 2 matters most, because the approval step is the product's safety promise.

## Options

| Option | What it does | Verdict |
| --- | --- | --- |
| A. Keep random ports; route by instance identity | The add-in sends an identity for its Revit with every panel request. The hub finds that instance's registry entry on each request and reconnects when a call fails. The identity is also passed to the MCP server the hub starts for chat. | Recommended. Fixes problems 1 to 4 and 6. Problem 5 needs the hub lifecycle change below. |
| B. One hub per Revit | Each add-in starts its own hub on its own random port. | Works, but runs one Python process per Revit. Keep as a fallback. |
| C. A fixed port per Revit year | For example 3024 for Revit 2024. | Rejected. Two sessions of one year collide, and fixed ports can clash with other software. |
| D. Named pipes | No TCP port, access limited to the current user. The pipe name can carry the instance identity, which also removes the port race. | Feasible. An earlier draft of this record rejected it as too hard on both .NET Framework 4.8 (Revit 2024) and .NET 8 (2025 and later). The architect review disagrees: named pipes work on both, and the job is roughly medium. Keep it as the likely second step, after option A proves the routing model. |

## Decision (proposed)
Take option A, with these parts.

### Instance identity
1. **Do not use the process id alone.** Use the pid together with the process start time from the operating system, as one pair. A reused pid has a different start time, so the pair does not match. As an alternative, or in addition, the add-in writes a new non-secret `instance_id` (a GUID made at startup) into its registry file. The `session_token` stays what it is today, a secret for calling the bridge. It must not be copied into plan files or logs, and it should not be the routing key.
2. Registry readers treat a missing `instance_id` or start time as "unknown" and refuse to match on it. They do not fall back to the pid.

### Panel requests
3. The add-in adds the instance identity to every request it sends the hub. The panel never chooses a Revit; the add-in that hosts the panel does.
4. The hub resolves the bridge per request. If no live registry entry matches, it returns a clear error. It never falls back to "the newest Revit" for panel requests.
5. On a connection error the hub discards its cached bridge and looks the registry up again once before it reports failure.
6. The add-in retries the listener start with a new port a few times if binding fails.

### Chat and other MCP clients
7. `/agent/chat` takes the instance identity from the request and passes it to the CLI it starts. For Claude the identity goes into the generated MCP config; for Codex it goes into the registered server's command or environment. The exact mechanism is an open question, because the Codex server is registered once with `codex mcp add` and shared by later turns. A per-turn environment variable may not reach it.
8. The MCP server reads that identity at startup, resolves the matching registry entry, and refuses to start tools against any other Revit. If the identity is set and no entry matches, it errors. It does not pick the newest.
9. Verification must cover both CLI providers, Claude and Codex.
10. A hand-configured MCP client keeps the year pin. A setting that pins an instance (or a pid and start time) can follow.

### Plans
11. A plan records which Revit created it (instance identity and the document's unique id) and `execute_plan` refuses to run it in a different one. This ties an approval to the model it was reviewed against. Because the pid can be reused, a pid-only match is never enough.
12. The architect review also asks that approval state, the plan hash and whole-plan execution as one `TransactionGroup` move into the add-in, so each Revit owns the approval for its own model. That fits this record only in part: it would make step 11 a local check inside the add-in, with no cross-process lookup. It is a larger change and is better decided in its own record. This one should not block on it.

### Hub lifecycle
13. The hub must not die with the Revit that happened to launch it. Options, for the maintainer to choose from:
    - Start the hub detached from the launching Revit, with a lock or a health check so exactly one instance runs, and stop it when the last registry entry goes away.
    - Let every add-in check `/health` on a timer and relaunch the hub if it is gone. Whichever Revit notices first starts it.
    - Run one hub per Revit (option B), which avoids the sharing problem at the cost of more Python processes.
    Today `StopIfLaunched` kills the hub on exit. Any option has to change that, or add relaunch, and needs a test that closes the hub-owning Revit while another stays open.

## How to verify
These need real Revit sessions, so none of them is checked today:

- Open Revit 2024 and 2026 with different documents. Approve a plan in each panel. Each plan must run in its own Revit, and a request carrying a stale process id must fail with a clear message.
- Close and reopen one Revit while the hub keeps running. The panel must recover without restarting the hub.
- Open two sessions of the same year. Each panel must reach its own Revit.
- Start a chat from the older Revit's panel while a newer Revit is open, once with the Claude CLI and once with the Codex CLI. The tool calls must land in the older Revit.
- Close the Revit that launched the hub while another Revit stays open. The remaining panel must keep working, either because the hub survived or because it was relaunched.
- Fake a registry entry with a reused pid and a different start time or `instance_id`. A plan from the old session must fail.
- Block the chosen port at the moment of binding. The add-in must pick another and still register.

## Consequences
- Panels stay correct when several Revit versions are open.
- The shared hub stays, so there is still one Python process, not one per Revit.
- The panel protocol gains one header and the hub gains a lookup by instance identity. The MCP server gains a startup setting. These are small and easy to test with fake registry entries.
- The registry file gains a field. The hub lifecycle gains a rule about who may start and stop it.
- Plan files gain fields, which older plans will not have. The check has to treat a missing field as "unknown" and say so, not as a match.

## Open questions
1. Should a plan created through an MCP client, which is not tied to a panel, carry a process id too? Probably yes, from the bridge it used.
2. When a document is saved under a new name, is the instance identity enough, or should plans also record the document's unique id? (Step 11 assumes both.)
3. Should the registry file move to a per-user folder with tighter access rights now, or only if named pipes are adopted?
4. How does the Codex path receive a per-turn instance identity when its MCP server is registered once and reused? Does it need one registration per Revit, or a lookup the server does itself?
5. Which hub lifecycle option is least fragile on a machine with no bundled Python (see the installer gap noted in `PanelHubLauncher`)?
6. Should approval state and whole-plan execution move into the add-in, as the architect review suggests? If yes, which of these steps shrink?
