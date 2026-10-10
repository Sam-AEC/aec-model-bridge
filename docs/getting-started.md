# Getting started

This tutorial takes about 15 minutes. You will install the server, ask an AI assistant to review a model, and see how a change is planned, approved and checked. You do not need Revit for the first part. It runs in **demo mode** on built-in sample data.

You do not need to write code. You will type a few short commands and talk to your AI assistant.

**Who this is for:** BIM coordinators who want to see how the tool works before they connect it to a real project.

## What you will do

1. Install the server and connect an AI client (part 1).
2. Ask the assistant to review the sample model (part 2).
3. Plan, approve and run one change, then read the proof (part 3).
4. Optional: connect live Revit (part 4, **UNVERIFIED**).

## What demo mode is

Demo mode runs the server with `MCP_REVIT_MODE=mock`. It does not touch Revit or any model file. Tools that read the model answer from a tiny built-in sample model. Tools that write answer with a canned `mock-response` and change nothing. See the [FAQ](faq.md#what-is-demo-mode).

The sample model is small. It has two levels, one wall, one door and two rooms. It is not the 12-door fixture from the [demo runbook](demo-runbook.md), which needs a real Revit.

## Part 1: install and connect (5 minutes)

### What you need

- Python 3.11 or later, or [uv](https://docs.astral.sh/uv/getting-started/installation/) (the one-click install buttons need uv and nothing else).
- An MCP client. Claude Desktop, VS Code with GitHub Copilot, Cursor and Codex are documented. See [compatibility](compatibility.md).

### Option A: add the server to your client with uvx

Open your client's MCP settings and add this entry. For Claude Desktop the file is `claude_desktop_config.json`. This is the same entry the [README quick start](../README.md#quick-start) uses, with the mode set to `mock`:

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit",
        "aec-model-bridge"
      ],
      "env": {
        "MCP_REVIT_MODE": "mock"
      }
    }
  }
}
```

`uvx` downloads the server from GitHub, so it needs Git and an internet connection the first time. Restart your client after you save the file.

### Option B: install from source in a virtual environment

Use this if you cloned the repository. These are the commands from the [install guide](install.md):

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit
```

Then point your client at `.venv\Scripts\python.exe` with the arguments `-m revit_mcp_server.mcp_server` and the environment variable `MCP_REVIT_MODE` set to `mock`. The [install guide](install.md#configure-an-mcp-client) shows the full entry.

### Check that it works

Restart the client and open a new chat. Ask:

> Which AEC Model Bridge tools do you have? Group them by area.

**What to look for:** the assistant lists a long catalog of tools. You should see names that start with `revit_`, `qaqc_checker_`, `model_inspector_` and `parameter_manager_`, plus `plan_actions`, `execute_plan` and `get_proof_bundle`. If the list is empty or the assistant says it has no such tools, go to [troubleshooting: the MCP client cannot start the server](troubleshooting.md#the-mcp-client-cannot-start-the-server).

The full tool list is in the [tool reference](tools-generated.md).

## Part 2: review the sample model (5 minutes)

### Step 1: summarize the model

Ask:

> Summarize the model.

The assistant calls `model_inspector_summarize_model`. **What to look for:** a short summary with a document title, a count of elements, a count by category, and a room count split into placed and unplaced. In demo mode the title is a mock project name. That tells you the answer comes from sample data and not from your model.

### Step 2: run the quality check

Ask:

> Run the core QA check and list the open issues.

The assistant calls `qaqc_checker_run_check` with the `core` rule pack, then `qaqc_checker_list_issues`. **What to look for:**

- A result with a number of rules run, a total number of findings, and a count by severity.
- A list of findings. Each one has a rule id, a severity, a label, a plain message and a suggested fix.
- On the sample model the findings are about rooms: one room that is not placed on a level, and rooms without a name.

If the assistant lists issues from an earlier session too, ask it to pass the `doc_guid` from the check and the status `open`. The issue store keeps old findings.

Read the findings yourself. The check reports; it does not change anything.

## Part 3: plan, approve, run, verify (5 minutes)

This is the heart of the tool. A model change is never made directly. It goes through a plan that a person approves.

### Step 3: see the gate block a direct change

Ask:

> Set the Comments parameter of element 401 to "Checked". Do it directly, without a plan.

**What to look for:** the call is refused. The message says that approval mode is enabled and that the tool needs a valid `plan_id`. That is the approval gate working. It is on by default (`MCP_REVIT_APPROVAL_MODE` is `required`).

### Step 4: create a plan

Ask:

> Make a plan to set the Comments parameter of element 401 to "Checked". Do not run it.

The assistant calls `plan_actions`. **What to look for:**

- A `plan_id` that starts with `plan_`.
- A state of `pending`.
- One action with a before value and an after value. In demo mode the before value is `null`, because mock mode has no real model to read from.

Ask the assistant to call `list_pending_plans`. Your plan should be in the list.

The plan is saved as a file in the `plans` folder of your workspace. The default workspace is `~/Documents/AEC Model Bridge`.

### Step 5: approve the plan

In live Revit you approve in the Revit panel, on the Plans tab. In demo mode there is no panel. You have two ways to approve:

- **Approve it yourself, outside the chat.** Start the panel hub in a second terminal, then send one approval request. The hub is the same program the Revit panel talks to. This keeps the AI out of the approval.

  ```powershell
  $env:MCP_REVIT_MODE = "mock"
  aec-model-bridge-panel-server
  ```

  Run it from the same virtual environment. In a third terminal, replace `plan_xxxxxxxxxxxx` with your plan id:

  ```powershell
  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8787/execute -ContentType "application/json" `
    -Body '{"tool":"approve_plan","arguments":{"plan_id":"plan_xxxxxxxxxxxx","approver":"your name"}}'
  ```

  **What to look for:** a reply with `ok` set to true and the plan state `approved`. Use the same workspace folder for the hub and for your client, or the hub will not find the plan. If port 8787 is busy, see [troubleshooting](troubleshooting.md#the-panel-hub-cannot-start-port-8787-is-in-use).

- **Ask the assistant to approve it.** This works today, because `approve_plan` is a normal tool. It also means the assistant approved its own plan. Use this only in demo mode. See the [FAQ](faq.md#can-the-ai-change-my-model-without-me-clicking-approve) for what is true today.

### Step 6: run the plan

Ask:

> The plan is approved. Run it.

The assistant calls `execute_plan`. **What to look for:** a result with the plan state `executed` and one entry per action. In demo mode each entry carries `mock: true` and a status of `mock-response`. Nothing was changed, because there is no model. In live Revit this step would write to the model.

### Step 7: read the proof

Ask:

> Show me the proof bundle for that plan.

The assistant calls `get_proof_bundle`. **What to look for:** times for created, approved and executed; who approved (this name is self-reported and not checked); a plan hash; a list of elements with the before and new values; an outcome; and a line that says the result is UNVERIFIED against the live model. That line is honest. The bundle records what the server asked for, not what the model now contains. To prove a change, take a new snapshot and run the check again. The [proof and revert](proof-and-revert.md) page explains each field.

### Step 8: try a rejected plan

Ask the assistant to make a second plan. Reject it the same way you approved the first, with `reject_plan` in the request body. Then ask the assistant to run it.

**What to look for:** the run is refused. The message says the plan is `rejected`, not `approved`. Nothing runs.

### Step 9: roll back

Ask:

> Roll back the first plan.

The assistant calls `rollback_plan`. **What to look for:** the plan state becomes `rolled_back`. Read the `rollback_warnings` list. In demo mode it says the action was skipped because no before value was recorded. The state alone does not prove that the values went back. This is also true in live Revit when a parameter was empty before. See [undo in the FAQ](faq.md#how-do-i-undo-a-change).

You have now seen the full loop: ask, plan, approve, run, prove, undo.

## Part 4: live Revit (UNVERIFIED)

> **Read this first.** Nobody has run model writes in a real Revit yet. The read-only steps (connect, snapshot, QA check) are checked in code, but they have not been recorded against a live session either.
>
> A review found that the add-in's `CreateTransaction` method calls itself. As written on `main`, every model write would loop until Revit crashes. The fix is [pull request #95](https://github.com/Sam-AEC/aec-model-bridge/pull/95). It is open and not merged at the time of writing. **Do not run any write step (Part 4, step L5 and the undo steps) until #95 is merged and you have rebuilt the add-in from it.** Use a throwaway copy of a model. Never a project file.

Everything in this part is UNVERIFIED (live Revit) unless it says otherwise.

### L1: install the add-in

Follow the [install guide](install.md). The easiest route on Windows is the installer from the [latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest). Close Revit before you run it. Windows SmartScreen may warn about an unknown publisher, because the installer is not code-signed. See [troubleshooting](troubleshooting.md#windows-or-antivirus-blocks-the-installer).

Start Revit. **What to look for:** an **AEC Bridge** tab on the ribbon.

### L2: switch the client to bridge mode

Change `MCP_REVIT_MODE` from `mock` to `bridge` in your client entry. Set `MCP_REVIT_WORKSPACE_DIR` and `MCP_REVIT_ALLOWED_DIRECTORIES` to a folder you can write to. Restart the client. Keep Revit open with a project loaded.

### L3: verify the bridge

Run the health check from the [install guide](install.md#verify-the-bridge). **What to look for:** a status of `healthy` and the year of the Revit you have running. If not, see [troubleshooting](troubleshooting.md).

### L4: take a snapshot and run the check (read-only)

Ask the assistant to take a snapshot of the active model. The tool is `revit_extract_snapshot`. Keep the `snapshot_id` it returns. In live mode the QA check refuses to run without one. It does this on purpose, so it never answers with sample data that looks like your model.

Then ask for the core QA check on that snapshot, and list the open issues for that document. Compare the findings with what you see in Revit. If they do not match, treat that as a finding and write it down.

### L5: change something (blocked until #95 is merged)

Only do this after #95 is merged and the add-in is rebuilt, and only on a throwaway copy.

1. Ask the assistant to plan one small change, such as a Mark on a single door. Check the element id, the old value and the new value yourself.
2. Approve the plan in the Revit panel, on the Plans tab. Press Approve.
3. Ask the assistant to run it.
4. Take a new snapshot and run the check again. Never verify with the old snapshot.
5. To undo, press Ctrl+Z in Revit straight after the run. Revit's Undo list should show `AMB: Set Parameter Value`. This is not confirmed in a live Revit.

The [demo runbook](demo-runbook.md) walks through a larger version of this with 12 doors and the expected counts.

## If something goes wrong

Start with [troubleshooting](troubleshooting.md). For common questions, see the [FAQ](faq.md).
