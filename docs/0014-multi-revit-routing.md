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
- **The panel shares one hub.** The panel hub listens on fixed port 8787. `PanelHubLauncher` does not start a new hub when one already answers. The panel's `HubClient` posts `tool` and `arguments` to `/execute` and nothing that says which Revit it belongs to.

## Problems

1. **A restarted Revit leaves the hub talking to a dead port.** A new Revit gets a new port and token. A hub that is still running keeps the old ones until it is restarted.
2. **Two panels can drive one Revit.** With Revit 2024 and 2026 both open, the second Revit finds the hub on 8787 already running and attaches to it. The hub holds one bridge, so both panels act on the same Revit, whichever the hub picked when it started. An approval clicked in the 2024 panel could run in the 2026 model.
3. **Two sessions of the same year cannot be told apart by year.** A year pin picks the newest of the two.
4. **A small race when choosing the port.** The port is released before the listener binds it, so another program can take it in between. The listener then fails to start, and nothing retries.

Problem 2 matters most, because the approval step is the product's safety promise.

## Options

| Option | What it does | Verdict |
| --- | --- | --- |
| A. Keep random ports; route by process id | The add-in sends its process id with every panel request. The hub finds that process's registry entry on each request and reconnects when a call fails. | Recommended. Small change, fixes problems 1 to 3. |
| B. One hub per Revit | Each add-in starts its own hub on its own random port. | Works, but runs one Python process per Revit. Keep as a fallback. |
| C. A fixed port per Revit year | For example 3024 for Revit 2024. | Rejected. Two sessions of one year collide, and fixed ports can clash with other software. |
| D. Named pipes | No TCP port, access limited to the current user. | Stronger on security, but the server would need rewriting for both .NET Framework (Revit 2024) and .NET 8 (2025 and later). Revisit later. |

## Decision (proposed)
Take option A.

1. The add-in adds its process id to every request it sends the hub. The panel never chooses a Revit; the add-in that hosts the panel does.
2. The hub resolves the bridge per request, by process id. If no live registry entry matches, it returns a clear error that names the problem. It never falls back to "the newest Revit" for panel requests.
3. On a connection error the hub discards its cached bridge and looks the registry up again once before it reports failure.
4. The add-in retries the listener start with a new port a few times if binding fails.
5. A plan records which Revit created it (process id and document). `execute_plan` refuses to run it in a different one. This ties an approval to the model it was reviewed against.

MCP clients keep the year pin. A second setting that pins a process id would help the same-year case, but it can wait.

## How to verify
These need real Revit sessions, so none of them is checked today:

- Open Revit 2024 and 2026 with different documents. Approve a plan in each panel. Each plan must run in its own Revit, and a request carrying a stale process id must fail with a clear message.
- Close and reopen one Revit while the hub keeps running. The panel must recover without restarting the hub.
- Open two sessions of the same year. Each panel must reach its own Revit.
- Block the chosen port at the moment of binding. The add-in must pick another and still register.

## Consequences
- Panels stay correct when several Revit versions are open.
- The shared hub stays, so there is still one Python process, not one per Revit.
- The panel protocol gains one header and the hub gains a lookup by process id. Both are small and easy to test with fake registry entries.
- Plan files gain two fields, which older plans will not have. The check has to treat a missing field as "unknown" and say so, not as a match.

## Open questions
1. Should a plan created through an MCP client, which is not tied to a panel, carry a process id too? Probably yes, from the bridge it used.
2. When a document is saved under a new name, is the process id enough, or should plans also record the document's unique id?
3. Should the registry file move to a per-user folder with tighter access rights now, or only if named pipes are adopted?
