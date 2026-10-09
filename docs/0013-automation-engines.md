# ADR 0013: Automation engines (Dynamo, pyRevit, Python)

## Status
Proposed. Nothing in this record is built yet. It needs a decision from the maintainer and checks in a live Revit session before any step is called supported.

## Context
Today the assistant works one tool call at a time: read a parameter, set a parameter, make a sheet. That covers simple tasks. Coordinators also run longer automation, such as Dynamo graphs and pyRevit scripts, and they want the assistant to run those too.

Running code inside Revit is the riskiest thing this product can do. A script can change or delete anything, and an assistant that can launch scripts has the same reach. The approval gate (ADR 0008) is what makes the rest of the product safe, so any new capability has to fit inside it.

What the repository already has, read from the code:

- **A generic reflection tool.** `revit_invoke_method` (bridge call `revit.invoke_method`, `BridgeCommandFactory.cs`) calls any public Revit API method by class and method name. It can run inside a transaction when `use_transaction` is true. `revit_reflect_set` sets any writable property the same way. Both are marked mutating, so the gate asks for an approved plan before they run.
- **A mismatch.** `revit.reflect_get` is also marked mutating in the add-in, while its tool description says read-only. That blocks harmless reads behind an approval.
- **An unattended mode.** `MCP_REVIT_APPROVAL_MODE=auto` skips the plan check entirely. With it set, `revit_invoke_method` has no gate at all.
- **Recipes.** The `recipe_runner` module chains existing tools from a YAML file. Every step is still an ordinary, gated tool call.
- **A pyRevit module in review.** PR #61 adds discovery, a plan with the script's SHA-256, and a hash-checked run. It is Python only. The add-in side that would run the script does not exist.
- **Nothing for Dynamo, and no plain Python runner.**

## Decisions

### 1. One pattern for every engine
Each engine follows the same steps: discover, inspect, plan, approve, run, prove.

- `list_*` finds what is available. Read-only.
- `inspect_*` reports what the file would do without running it. Read-only.
- `plan_run_*` drafts a plan with the file's hash, the inputs and the inspection report. It runs nothing, so it is not marked mutating.
- `run_*` is mutating. It needs an approved plan, re-checks the hash and refuses on any mismatch.

PR #61 already follows this shape for pyRevit. Dynamo and any later engine should copy it, so a reviewer learns one flow.

### 2. Order: Dynamo, then pyRevit, then Python
- **Dynamo first.** A `.dyn` file is JSON. It can be read without running it: its declared inputs and outputs, the node types, and whether it contains Python nodes or nodes that delete or modify elements. That gives a real risk report, not a guess.
- **pyRevit second.** A script is free-form code. The risk report is a line-based heuristic, and "no hits" does not mean read-only.
- **Python last, and mostly without new code in Revit.** The hub is already Python. An outside script can call the same gated tools over MCP. For most automation that is enough, and no code runs inside the Revit process. Chaining tools in a recipe is the safest next step. Running Python inside Revit needs a host (a Dynamo Python node, or pyRevit), so it comes after the other two prove themselves.

### 3. Safety rules that do not bend
1. Off by default. One flag turns automation on, and the message when it is off says that it runs code in Revit.
2. Files only from folders the user lists. No path traversal, no symlink escape.
3. The approved plan pins the file by SHA-256. A file that changed after approval does not run.
4. The plan shows the inspection report next to the approve button.
5. No auto-approval. Automation tools and `revit_invoke_method` refuse to run when `approval_mode` is `auto`.
6. The model never supplies code to execute. It names a file that already exists in an allowed folder.
7. Every run writes a proof file and can produce a revert plan (see the proof-and-revert work, PR #62).

### 4. Dry run before the first real run
The idea: run the graph or script inside a Revit `TransactionGroup`, roll it back, and report which elements it would have added, changed or deleted. The coordinator then approves with the result in front of them.

Known limits, to be tested rather than assumed:

- A graph or script that opens its own transactions may not roll back cleanly.
- File writes, network calls and anything outside the model cannot be rolled back at all. The inspection report should flag them so the dry run is not trusted blindly.
- Behaviour in workshared and linked models is unknown.
- Revit's document-changed events list added, modified and deleted element ids. That should be the source of the diff. This is general knowledge about the Revit API and has not been checked here.

### 5. Harden the existing reflection tool
Keep `revit_invoke_method` as an advanced escape hatch, and change three things:

- Refuse it under `approval_mode=auto`.
- Make the plan show the class, method and arguments clearly. A person cannot judge a call they cannot read.
- Fix the `revit.reflect_get` flag so reads do not need an approval.

## Phases

| Phase | Work | Size | Needed before it counts as supported |
| --- | --- | --- | --- |
| 1 | Dynamo inspect, plan and gated run. pyRevit gated run. Harden `revit_invoke_method`. | Medium | Run a real graph and a real script in Revit 2024 to 2027. Reject a plan whose file hash changed. |
| 2 | Dry-run diff preview on a rollback transaction group. | Medium to large | Test with graphs that open their own transactions, in a workshared model. |
| 3 | Recipes that chain gated tools and scripts. Outside Python through MCP. | Small | Run a recipe end to end and check that every step shows in the plan. |
| 4 | Python inside Revit through the safest host found in phase 1. | Large | Only after phases 1 and 2 hold up in daily use. |

## Consequences
- The assistant can run real automation, and every run still passes through a human approval with a hash-pinned file.
- Dynamo gets a better safety story than pyRevit, because its graphs can be inspected without running them.
- Automation is slower to start than a plain tool call. That is the price of the gate.
- Adding a new engine later means writing one module that follows the same four tools.

## Open questions
These need a person with a live Revit session.

1. Which entry point runs a `.dyn` file in the active session without opening the Dynamo window, and does it differ between Revit 2024 and 2027?
2. Does pyRevit offer a supported way to run a script in the current session from another add-in, or only through its own command loader?
3. Do Dynamo graphs that start their own transactions survive a rolled-back `TransactionGroup`?
4. What happens in a workshared model when a dry run touches elements another user owns?
5. Should `revit_invoke_method` stay available at all once the engines above exist?
