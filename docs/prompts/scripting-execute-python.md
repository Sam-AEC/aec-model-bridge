# Scripting prompts (revit_execute_python)

Prompts for IronPython 2.7 scripts that run inside Revit through `revit_execute_python`. Use a dedicated tool when one exists; scripts are for what the catalog does not cover. `mode` "read" needs no approval and cannot open transactions. `mode` "write" needs an approved plan. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow). For building geometry in live Revit, also see [the pre-flight prompt](revit-agent-preflight-and-verify.md).

### PY-01 Read-only query script

- **When to use:** You need a model fact that no read tool returns.
- **Prompt:**

```text
Find out {question} in the open model. Change nothing.
1. Check with search_tools and revit_list_commands whether a dedicated tool already answers this. If one does, use it and stop.
2. Otherwise write a short IronPython 2.7 script and run it with revit_execute_python and mode "read". Use doc, print the result, and do not mention Transaction.
3. Keep it under 20 seconds: collect with FilteredElementCollector and a category filter, not whole-model geometry.
Show me the script and the output.
```

- **Tools:** `search_tools`, `revit_list_commands`, `revit_execute_python`
- **Expected result:** The answer, the script used and its raw output.
- **Tested:** Mock: exercised (`revit_execute_python` read returned a mock response; `revit_list_commands` is not available in mock mode and says so).

### PY-02 Check API members before writing a script

- **When to use:** Every time a script uses a Revit API member you have not used before.
- **Prompt:**

```text
Before writing the script, check every Revit API type and member you plan to use with revit_api_lookup, for Revit {revit_year}.
List each one as FOUND with its signature, or NOT FOUND with the nearest real names.
If the lookup says UNVERIFIED because no API docs were found, tell me and do not present the member as confirmed.
Only then write the script.
```

- **Tools:** `revit_api_lookup`
- **Expected result:** A checked list of API members with signatures, or a clear UNVERIFIED note.
- **Tested:** Mock: exercised (no Revit API docs in the test environment, so the lookup correctly returned unverified).

### PY-03 Write script under a plan

- **When to use:** A change no dedicated tool can make, for example a one-off batch edit.
- **Prompt:**

```text
I need to {change_description} in the open model. No dedicated tool covers it.
1. Run a read-only version first with revit_execute_python and mode "read": list the element ids and current values the script would change. Show me the count.
2. Write the write script: one Transaction named "{transaction_name}", t.Start() and t.Commit(), lengths in feet (mm / 304.8), and print the changed ids.
3. Draft a plan with plan_actions whose action is revit_execute_python with mode "write" and that exact script. Put the element count and the read-only output in the review text.
4. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
5. After I approve, run execute_plan, then rerun the read-only script and compare.
```

- **Tools:** `revit_execute_python`, `plan_actions`, `execute_plan`
- **Expected result:** A plan containing the exact script; after approval, a read-back that shows the change.
- **Safety:** A write script without an approved plan is refused (observed in mock mode). Scripts are not undone by Revit's per-action undo in every case; keep them small and record the before-values in the review text.
- **Tested:** Mock: exercised up to the gate (the write call without a plan was refused).

### PY-04 Debug a failing script

- **When to use:** A script returned an error or wrong output.
- **Prompt:**

```text
This script failed with "{error_text}":
{script}
1. Explain the error in one sentence.
2. Check every API member it uses with revit_api_lookup.
3. Make the smallest fix. If the script writes, first rerun the read part with revit_execute_python mode "read" to test the selection.
4. Common causes to check: IronPython 2.7 syntax (no f-strings), internal units in feet, a missing Transaction for a write, a None element from doc.GetElement, a parameter that is read-only.
Show the fixed script and say whether it still needs a plan to run.
```

- **Tools:** `revit_api_lookup`, `revit_execute_python`
- **Expected result:** A short diagnosis, a minimal fix and a statement on whether approval is needed.
- **Tested:** Untested.

### PY-05 Run a pyRevit script under a plan

- **When to use:** Your team already has a pyRevit button that does the job.
- **Prompt:**

```text
Run the pyRevit script "{script_name}" on the open model.
1. List scripts with pyrevit_bridge_list_pyrevit_scripts and show me its path, description and whether write calls were detected.
2. Draft a plan with pyrevit_bridge_plan_run_pyrevit_script for that script. The plan records its SHA-256.
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run pyrevit_bridge_run_pyrevit_script with the plan_id and report the output.
```

- **Tools:** `pyrevit_bridge_list_pyrevit_scripts`, `pyrevit_bridge_plan_run_pyrevit_script`, `pyrevit_bridge_run_pyrevit_script`
- **Expected result:** The script runs once, only if its file still matches the approved hash.
- **Safety:** The run is refused without approval or when the file changed after the plan was drafted.
- **Tested:** Untested (needs pyRevit extension folders).
