# Views and annotation prompts

Prompts for view templates, crops, tags and review views. Every change is a plan that a person approves. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### VW-01 Views without a view template

- **When to use:** Graphics differ between plans that should look the same.
- **Prompt:**

```text
Find views named like "{name_filter}" that have no view template, and propose template "{template_name}" for them.
1. List templates with revit_list_view_templates and confirm "{template_name}" exists. List views with revit_list_views_sheets_schedules and name_contains "{name_filter}".
2. Show the views without a template, with their type.
3. Draft a plan with plan_actions that calls revit_set_view_templates for those views only. Leave views of another type out and say so.
4. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
5. After I approve, run execute_plan and list the views again.
```

- **Tools:** `revit_list_view_templates`, `revit_list_views_sheets_schedules`, `revit_list_views`, `plan_actions`, `revit_set_view_templates`, `execute_plan`
- **Expected result:** A plan that assigns one template to the listed views.
- **Safety:** Assigning a template overrides view-specific graphics. It runs only after approval.
- **Tested:** Mock: exercised (`revit_list_view_templates` and `revit_list_views`).

### VW-02 Align plan crops across levels

- **When to use:** Floor plans on a sheet set should show the same area on every level.
- **Prompt:**

```text
Align the crop regions of plans {view_names} to the reference plan "{reference_view}".
1. Find the view ids with revit_list_views.
2. Draft a plan with plan_actions that calls revit_align_crop with that reference, those views and annotation_crop "match_reference".
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and check one aligned view with revit_render_check.
```

- **Tools:** `revit_list_views`, `plan_actions`, `revit_align_crop`, `execute_plan`, `revit_render_check`
- **Expected result:** All listed plans share the reference crop rectangle.
- **Safety:** Crops change only after approval.
- **Tested:** Untested.

### VW-03 Tag all elements of a category in a view

- **When to use:** Doors or rooms in the active view are untagged.
- **Prompt:**

```text
Tag every {category} element in the active view.
1. Confirm the active view with revit_get_context and tell me its name. Stop if it is a 3D view or a sheet.
2. Draft a plan with plan_actions that calls revit_tag_all_in_view with category "{category}".
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and report how many tags were placed.
```

- **Tools:** `revit_get_context`, `plan_actions`, `revit_tag_all_in_view`, `execute_plan`
- **Expected result:** Tags placed in the active view; a count in the result.
- **Safety:** Tag placement runs only after approval. Tag positions are not checked for overlap; review the view after.
- **Tested:** Untested.

### VW-04 Create a coordination 3D view for a scope

- **When to use:** You need a framed 3D view of an area or a set of elements for a meeting.
- **Prompt:**

```text
Make a 3D view named "{view_name}" framed on {scope_description}, with display style "shaded_with_edges".
1. Find the elements or level with read tools and tell me the scope you will use.
2. Draft a plan with plan_actions that calls revit_make_view with kind "3d", name "{view_name}", tag "{tag}" and that scope.
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and check the view is not blank with revit_render_check, writing the PNG to the workspace.
```

- **Tools:** `plan_actions`, `revit_make_view`, `execute_plan`, `revit_render_check`
- **Expected result:** A new tagged 3D view and a PNG check.
- **Safety:** The view is created only after approval. A rerun with the same tag replaces only content it owns.
- **Tested:** Untested.

### VW-05 Blank-view check before issue

- **When to use:** A view on a sheet prints empty and you want to find others like it.
- **Prompt:**

```text
Check whether views {view_names} render blank. Change nothing.
For each view, run revit_render_check with output_path "{folder}/<view name>.png" in the workspace.
Report each file path, its size and whether the image looked blank. Say when the image could not be analysed.
```

- **Tools:** `revit_list_views`, `revit_render_check`
- **Expected result:** One line per view: path, bytes, blank or not, or unverified.
- **Tested:** Untested (needs a live view to export).
