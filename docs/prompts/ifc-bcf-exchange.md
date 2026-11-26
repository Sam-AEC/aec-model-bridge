# IFC and BCF exchange prompts

Prompts for IFC files, IDS checks and BCF issues. IFC reading works without Revit. Exporting from Revit goes through a plan. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### EX-01 Inspect an IFC file

- **When to use:** You receive an IFC from a consultant.
- **Prompt:**

```text
Inspect the IFC file "{file}" in the workspace. Change nothing.
1. Run ifc_get_metadata: schema, application, units and georeferencing.
2. Run ifc_get_spatial_structure: site, building, storeys and element counts per storey.
3. Run ifc_validate and summarise errors and warnings.
Tell me whether the file looks usable for coordination and why. Report a validation engine error as an error, not as "invalid file".
```

- **Tools:** `ifc_get_metadata`, `ifc_get_spatial_structure`, `ifc_validate`, `ifc_query_elements`
- **Expected result:** A short file profile and validation summary.
- **Tested:** Mock: exercised with a small test IFC. In this environment `ifc_validate` returned a validation engine error, which is why the prompt asks the assistant to report it as such.

### EX-02 Check an IFC against IDS requirements

- **When to use:** The client issued an IDS (Information Delivery Specification).
- **Prompt:**

```text
Check "{ifc_file}" against the IDS "{ids_file}", both in the workspace. Change nothing.
Run ids_validator_validate_ifc with html_filename "{report_name}.html".
Report pass or fail per specification with counts, and up to ten failing GlobalIds per failed specification.
Group the failures by the property or attribute that is missing.
```

- **Tools:** `ids_validator_validate_ifc`
- **Expected result:** Pass and fail counts per specification and an HTML report in the workspace.
- **Tested:** Mock: exercised with the repository's small IFC and IDS test files.

### EX-03 Export IFC and check what the export dropped

- **When to use:** Before sending an IFC, to catch missing classifications, materials or storeys.
- **Prompt:**

```text
Export the open model to IFC {ifc_version} as "{file}" in the workspace, then check what the export lost.
1. Draft a plan with plan_actions that calls revit_export with format "ifc", ifc_version "{ifc_version}" and overwrite false.
2. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
3. After I approve, run execute_plan.
4. Run revit_ifc_check on the exported file with expect_parameters {parameter_list}. Report elements dropped per category, missing classification, materials and storey assignment.
```

- **Tools:** `plan_actions`, `revit_export`, `execute_plan`, `revit_ifc_check`
- **Expected result:** An IFC in the workspace and a list of what did not make it into the file.
- **Safety:** The export writes a file and runs only after approval. No approval path deletes the file again.
- **Tested:** Mock: exercised (`revit_ifc_check` only; the export step was not run).

### EX-04 QA issues to BCF

- **When to use:** Sending QA findings to a team that uses a BCF viewer.
- **Prompt:**

```text
Save the recorded QA/QC issues to a BCF file "{file}.bcfzip" in the workspace for project "{project_name}".
List the open issues with qaqc_checker_list_issues first and tell me how many there are.
Then run bcf_exchange_export_bcf with use_qaqc_issues true and overwrite false. Report the file path and issue count.
Say that the BCF has not been checked in other BCF tools.
```

- **Tools:** `qaqc_checker_list_issues`, `bcf_exchange_export_bcf`
- **Expected result:** A BCF 2.1 file in the workspace. The model is not changed.
- **Tested:** Mock: exercised.

### EX-05 Import BCF issues and find the elements

- **When to use:** A consultant sent a BCF with comments on your model.
- **Prompt:**

```text
Read the BCF file "{file}" in the workspace and find the elements it refers to. Change nothing.
1. Run bcf_exchange_import_bcf and list the topics: title, status, priority and element ids.
2. For the topic I choose, select its elements with revit_select_by_unique_ids so I can see them.
Do not change any element; if a topic asks for a change, describe it and wait for me.
```

- **Tools:** `bcf_exchange_import_bcf`, `revit_select_by_unique_ids`
- **Expected result:** A topic list and a selection in Revit for the chosen topic.
- **Tested:** Mock: exercised (`bcf_exchange_import_bcf` only).
