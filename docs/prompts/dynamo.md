# Dynamo prompts

AEC Model Bridge has no Dynamo tools. These prompts help teams that already use Dynamo: port Python nodes to `revit_execute_python`, check what a graph did, and feed data to graphs. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### DY-01 Port a Dynamo Python node to a bridge script

- **When to use:** A Python Script node works in Dynamo and you want the assistant to run the same logic through the bridge.
- **Prompt:**

```text
Port this Dynamo Python Script node to a revit_execute_python script:
{node_code}
Rules for the port:
- Inputs IN[0], IN[1] become literals at the top of the script: {input_values}.
- UnwrapElement is not needed; get elements with doc.GetElement(ElementId(id)).
- TransactionManager.Instance.EnsureInTransaction / TransactionTaskDone become Transaction(doc, "{name}") with Start and Commit.
- OUT becomes print() or __output__. Return ids and values, not Dynamo geometry.
- The bridge runs IronPython 2.7. Remove CPython 3 only syntax and check API members with revit_api_lookup.
First run the read part with mode "read". If the node writes, draft a plan with plan_actions; you cannot approve it, so tell me to approve it in the Revit panel and wait.
```

- **Tools:** `revit_api_lookup`, `revit_execute_python`, `plan_actions`, `execute_plan`
- **Expected result:** An equivalent bridge script, tested read-only, and a plan for the write part.
- **Safety:** The write part runs only through an approved plan.
- **Tested:** Untested.

### DY-02 Check what a Dynamo run changed

- **When to use:** Someone ran a Dynamo graph or Player script and you want to know what it touched.
- **Prompt:**

```text
I am about to run the Dynamo graph "{graph_name}". Record what it changes. Change nothing yourself.
1. Take a snapshot now with snapshot_take and tell me its id.
2. Wait until I say the graph has run.
3. Take a second snapshot and compare them with model_changes_compare_snapshots.
4. Run revit_warnings_delta. Report elements added, removed and modified per category, parameter changes and new warnings.
```

- **Tools:** `snapshot_take`, `model_changes_compare_snapshots`, `revit_warnings_delta`
- **Expected result:** A before and after record of the graph run. Dynamo writes do not go through the approval gate, so this record is the only trace the bridge has of them.
- **Tested:** Untested (needs two snapshots of one document taken around a real run).

### DY-03 Export data for a Dynamo graph

- **When to use:** A Dynamo graph reads parameter data from Excel.
- **Prompt:**

```text
Export {parameter_list} for {category} elements to "{file}.xlsx" in the workspace, with one row per element and the element UniqueId in the first column, for a Dynamo graph to read.
Take a snapshot and run parameter_manager_export_params_xlsx. Tell me the path and row count and the exact column headers.
```

- **Tools:** `snapshot_take`, `parameter_manager_export_params_xlsx`
- **Expected result:** An .xlsx file and its column headers, ready for Dynamo's Excel nodes.
- **Tested:** Mock: exercised (the same export call as PAR-03).

### DY-04 Explain a Dynamo graph before replacing it

- **When to use:** You inherited a .dyn file and want to know whether bridge tools can replace it.
- **Prompt:**

```text
Here is the node list of a Dynamo graph (from the .dyn JSON):
{node_list}
1. Explain in plain steps what the graph does, in order.
2. For each step, name the AEC Model Bridge tool that does the same, using search_tools. Mark steps with no matching tool.
3. Say which steps write to the model; those would need a plan with plan_actions in the bridge.
Do not run anything.
```

- **Tools:** `search_tools`
- **Expected result:** A step list mapped to bridge tools, with write steps marked.
- **Tested:** Untested.

### DY-05 Replace a Dynamo Player script with a recipe

- **When to use:** A Player script runs the same sequence every week.
- **Prompt:**

```text
Our Dynamo Player script "{player_script}" does: {steps}.
1. List available recipes with recipe_runner_list_recipes. Tell me if one already covers these steps.
2. If one does, run it with recipe_runner_run_recipe and dry_run true and show the steps it would take.
3. Any step that changes the model must end in a plan; you cannot approve it. Tell me to approve it in the Revit panel and wait.
```

- **Tools:** `recipe_runner_list_recipes`, `recipe_runner_run_recipe`, `recipe_runner_get_run_status`
- **Expected result:** A matching recipe and its dry-run steps, or a statement that none fits.
- **Safety:** Write steps inside a recipe still need an approved plan.
- **Tested:** Mock: exercised (`recipe_runner_list_recipes` only).
