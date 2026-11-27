"""Presentation metadata for the MCP tool listing.

Providers define tools with terse descriptions and schemas that often leave
individual parameters undocumented. MCP directories (Glama, ToolBench, Smithery,
...) and the LLMs that call the tools both score/depend on three things: a clear
description, a documented input schema, and behaviour annotations
(readOnlyHint / destructiveHint / idempotentHint / openWorldHint).

This module layers that metadata on top of the provider definitions at listing
time. It never changes what a tool does or how it is gated: `enrich_tool` returns
a copy, and the annotations are *derived from* the existing `is_mutating` /
`destructive` flags plus an explicit table of the few tools whose flag alone
would be misleading (for example exports, which are not gated but do write files).
"""
from __future__ import annotations

import copy
import re
from typing import Any

from mcp.types import Tool, ToolAnnotations, ToolExecution

from .locale_descriptions import localized_description
from .mcp_tasks import TASK_TOOLS
from .output_schemas import output_schema_for
from .providers.base import ProviderTool
from .result_presentation import APPROVAL_TOOLS, add_response_schema
from .tool_profiles import ALWAYS_LOADED_TOOLS

# MCP tool `_meta` key that asks Claude Code to load a tool up front under tool search.
ALWAYS_LOAD_META_KEY = "anthropic/alwaysLoad"

PLAN_ID_DESCRIPTION = "Approved plan ID; see the server approval instructions."

# Canonical short text for parameters repeated across many tools. Applied in
# enrich_tool only when a tool's own text is one of the known long variants of
# the same rule; a tool with a genuinely different rule keeps its own text.
# plan_id is deliberately not handled here.
DRY_RUN_ROLLBACK = (
    "Default false. true: run the whole call as normal, then roll everything back, so nothing is "
    "written. The result says dry_run true, committed false and what would change (would_change). "
    "Still needs an approved plan like any write."
)
ON_ERROR_ABORT_SKIP = (
    "abort (default): first failure rolls everything back. skip: keep what worked, list the failures."
)
LIMIT_DEFAULT_50 = (
    "Most rows returned per list (default 50, max 500); the full list goes to a detail file when cut."
)
STATUS_LABELS = (
    "Stored text per status key (proposed, requested, approved, rejected, built), replacing the "
    "Dutch defaults Voorstel, Aangevraagd, Akkoord, Afgewezen, Gebouwd. "
    'Example {"approved": "Goedgekeurd"}.'
)
_TAG_PHASE = re.compile(
    r"^Your own label for this build phase \(for example (?P<ex>[^)]+)\)\. Elements made under the "
    r"same tag and (?P<key>\w+) are replaced when you run the call again; elements this tool did "
    r"not make are never touched\.$"
)
_TAG_COMMENTS = re.compile(
    r"^Prefix of the Comments parameter that marks the elements of one build phase "
    r"\(for example (?P<ex>[^)]+)\)\. Elements whose Comments start with it are checked\.$"
)
_FIELDS_ROWS = re.compile(
    r"^Row fields to keep \(for example (?P<ex>\[[^\]]*\])\); omit for all fields\.(?P<rows> Only affects rows\.)?$"
)


def canonical_param_text(
    tool_name: str, key: str, prop: dict[str, Any], *, is_mutating: bool
) -> str | None:
    """Short shared text for a known long variant of a repeated parameter, else None."""
    text = prop.get("description") or ""
    if key == "dry_run" and is_mutating and prop.get("type") == "boolean":
        if "roll everything back" in text:
            return DRY_RUN_ROLLBACK
    elif key == "on_error" and prop.get("enum") == ["abort", "skip"]:
        if text in (
            "abort (default): the first failure rolls the whole call back and nothing is kept. "
            "skip: keep what worked and list the failures.",
            "abort: the first failure rolls everything back. skip: keep what worked and list what failed.",
        ):
            return ON_ERROR_ABORT_SKIP
    elif key == "limit" and prop.get("type") == "integer":
        if "default 50" in text and "detail" in text:
            return LIMIT_DEFAULT_50
    elif key == "status_labels":
        return STATUS_LABELS
    elif key == "tag":
        m = _TAG_COMMENTS.match(text)
        if m:
            return f"Comments prefix of one build phase (for example {m['ex']}); only matching elements are checked."
        m = _TAG_PHASE.match(text)
        if m:
            return (
                f"Your own build-phase label (for example {m['ex']}). Re-running with the same tag "
                f"and {m['key']} replaces only what this tool made; other elements are never touched."
            )
    elif key == "fields":
        m = _FIELDS_ROWS.match(text)
        if m:
            return f"Row fields to keep, e.g. {m['ex']}; omit for all.{m['rows'] or ''}"
    return None

# One short 'Use X for A; use Y for B' sentence appended to the description of
# tools that have a near-duplicate sibling. Appended only, never replacing text,
# so every existing approval phrase stays. Names are checked by a test.
SIBLING_HINTS: dict[str, str] = {
    "revit_set_parameter_value": "Use this for one element; use revit_set_parameters for many with units, revit_batch_set_parameters for one value.",
    "revit_batch_set_parameters": "Use this for one value on listed ElementIds; use revit_set_parameters for per-element values with units.",
    "revit_batch_set_parameters_by_filter": "Use this to pick elements by filter; use revit_batch_set_parameters when you already have ElementIds.",
    "revit_set_type_parameter": "Use this for a type parameter; use revit_set_parameter_value for an instance parameter.",
    "revit_get_parameter_value": "Use this for one named parameter; use revit_get_element_parameters for all parameters of an element.",
    "revit_get_element_parameters": "Use revit_get_parameter_value for one named parameter; use revit_get_type_parameters for type values.",
    "revit_get_type_parameters": "Use this for type parameters; use revit_get_element_parameters for instance parameters.",
    "revit_get_view_templates": "Use this for a plain name list; use revit_list_view_templates for usage counts and unused templates.",
    "revit_apply_view_template": "Use this for one view; use revit_set_view_templates to assign a template to a list of views.",
    "revit_list_elements": "Use this for every element of one category; use revit_get_elements_by_type to filter by type or level.",
    "revit_get_elements_by_type": "Use this to filter by type, category or level; use revit_list_elements for a plain category list.",
    "revit_create_sheet": "Use this for one plain sheet; use revit_make_sheet for a tagged sheet with views placed on it.",
    "revit_make_sheet": "Use this for a tagged sheet with views; use revit_create_sheet for one plain sheet.",
    "revit_create_schedule": "Use this for one plain schedule; use revit_make_schedule for tagged fields, sorting and filters.",
    "revit_make_schedule": "Use this for tagged fields, sorting and filters; use revit_create_schedule for one plain schedule.",
    "revit_create_3d_view": "Use this for one plain 3D view; use revit_make_view for a framed, tagged view.",
    "revit_create_floor_plan_view": "Use this for one plain floor plan; use revit_make_view for a framed, tagged view.",
    "revit_create_section_view": "Use this for one plain section; use revit_make_view for a framed, tagged view.",
    "revit_create_tag": "Use this for one element; use revit_tag_all_in_view to tag a whole category in a view.",
    "revit_tag_all_in_view": "Use this for a whole category in a view; use revit_create_tag for one element.",
    "revit_set_selection": "Use this with ElementIds; use revit_select_by_unique_ids with UniqueIds, which also zooms to them.",
    "revit_select_by_unique_ids": "Use this with UniqueIds and a zoom; use revit_set_selection with ElementIds.",
    "revit_reflect_get": "Use this to read one property; use revit_api_lookup first to confirm the member exists.",
    "revit_reflect_set": "Use this to set a property; use revit_invoke_method to call a method, revit_api_lookup to check names.",
    "revit_invoke_method": "Use this to call one method; use revit_reflect_set to set a property, revit_execute_python for several steps.",
    "revit_get_element_bounding_box": "Use this for just the box; use revit_get_element_geometry for location, area, volume and length.",
    "revit_get_element_geometry": "Use this for location, area, volume and length; use revit_get_element_bounding_box for just the box.",
    "revit_change_element_type": "Use this to swap by element type; use revit_replace_family_type to swap by family and type name.",
    "revit_replace_family_type": "Use this to swap by family and type name; use revit_change_element_type to swap by element type.",
}

# --------------------------------------------------------------------------- #
# Tool descriptions (only tools whose provider-defined text is too terse)
# --------------------------------------------------------------------------- #
DESCRIPTIONS: dict[str, str] = {
    # --- Revit: model authoring -------------------------------------------
    "revit_health": "Check that the Revit bridge is reachable and return its status information. Call this first to confirm Revit is running.",
    "revit_create_wall": "Create a straight wall between two points on a level in the active Revit document. Coordinates and height are in feet (Revit internal units).",
    "revit_create_floor": "Create a floor on a level from a closed boundary of points in the active Revit document. Coordinates are in feet.",
    "revit_create_roof": "Create a roof on a level from a closed footprint of points, with an optional slope, in the active Revit document. Coordinates are in feet.",
    "revit_list_levels": "List all levels in the active Revit project with their names and elevations. Use it to get the level names or ids that creation tools need. Read-only.",
    "revit_list_views": "List all views in the active Revit project with their names, ids and view types. Use revit_list_views_sheets_schedules to get views, sheets and schedules in one call. Read-only.",
    "revit_list_elements": "List the elements of one Revit category (for example Walls, Floors, Roofs, Doors or Windows) in the active document. Each element has an id and a unique_id.",
    "revit_get_document_info": "Return metadata about the active Revit document, such as its title, path and workshare status. Use revit_health to check that Revit is reachable. Read-only.",
    "revit_create_level": "Create a new level with the given name at the given elevation (feet) in the active Revit document.",
    "revit_save_document": "Save the active Revit document, optionally to a path inside the allowed workspace directories.",
    "revit_create_grid": "Create a straight grid line between two points in the active Revit document. Coordinates are in feet.",
    "revit_create_room": "Create a room at an x/y point on a level, with a name and number, in the active Revit document. The point must lie inside an enclosed area.",
    "revit_delete_element": "Delete one element by its Revit ElementId from the active document. Dependent elements (for example hosted doors) may be deleted with it.",
    "revit_place_family_instance": "Place an instance of a loaded family type (for example furniture or equipment) at a point on a level. Coordinates are in feet.",
    "revit_place_door": "Place a door of a given family and type in a host wall at a location. Coordinates are in feet.",
    "revit_place_window": "Place a window of a given family and type in a host wall at a location. Coordinates are in feet.",
    "revit_list_families": "List the families loaded in the active Revit document together with their types. Use revit_list_elements for the placed instances of a category. Read-only.",
    "revit_create_floor_plan_view": "Create a floor plan view for the named level in the active Revit document.",
    "revit_create_3d_view": "Create a new 3D view with the given name in the active Revit document.",
    "revit_create_section_view": "Create a section view between two points with the given height in the active Revit document. Coordinates and height are in feet.",
    "revit_get_element_parameters": "Return every instance parameter of one element (name, value, storage type and read-only flag), and the element's unique_id.",
    "revit_set_parameter_value": "Set one instance parameter on one element to a new value in the active Revit document.",
    "revit_get_parameter_value": "Read the value of one named parameter on one element.",
    "revit_list_shared_parameters": "List the shared parameters defined in the active Revit document.",
    "revit_create_shared_parameter": "Create a shared parameter in the shared parameter file set in Revit, or reuse one with the same name and type, and bind it to categories in the active Revit document. Refuses when no shared parameter file is set; it never creates or switches that file.",
    "revit_list_project_parameters": "List the project parameters defined in the active Revit document with the categories they are bound to.",
    "revit_create_project_parameter": "Create a project parameter and bind it to categories in the active Revit document. Uses a temporary shared parameter file and restores the user's shared parameter file setting afterwards, so Revit stores it as a shared parameter with a new GUID.",
    "revit_batch_set_parameters": "Set the same parameter to the same value on many elements, given by ElementId, in one Revit transaction.",
    "revit_get_type_parameters": "Return the type parameters of the family type that an element belongs to.",
    "revit_set_type_parameter": "Set one type parameter on a family type, given by type_id. This changes every instance of that type.",
    "revit_list_sheets": "List all sheets in the active Revit project with their numbers, names and ids.",
    "revit_create_sheet": "Create a new sheet with a name, number and title block in the active Revit document.",
    "revit_delete_sheet": "Delete a sheet by ElementId. Views placed on it are not deleted, only their viewports.",
    "revit_place_viewport_on_sheet": "Place a view on a sheet at an x/y position (feet on the sheet).",
    "revit_batch_create_sheets_from_csv": "Create many sheets from a CSV file inside the allowed workspace. Columns: sheet_number, sheet_name, optional titleblock_name; titleblock_name is the default title block.",
    "revit_populate_titleblock": "Write a set of parameter values into the title block of a sheet.",
    "revit_list_titleblocks": "List the title block family types available in the active Revit document.",
    "revit_get_sheet_info": "Return detailed information about one sheet, such as its number, name, title block and placed views.",
    "revit_duplicate_sheet": "Duplicate a sheet under a new number and name, optionally copying its viewports.",
    "revit_renumber_sheets": "Renumber the listed sheets in one transaction: sheet_ids with a prefix and start number, or explicit numbers.",
    "revit_get_selection": "Return the ElementIds, and the matching UniqueIds, of the elements currently selected in the Revit UI. Use revit_set_selection to change the selection. Read-only.",
    "revit_set_selection": "Replace the current Revit UI selection with the given ElementIds. Does not modify the model.",
    "revit_preview_elements": "Preview which elements a proposed change affects: select and zoom to them in the active view and temporarily isolate them. Nothing is saved to the model.",
    "revit_clear_preview": "End the element preview: exit temporary isolate in the active view and clear the selection. Does not modify the model.",
    "revit_select_by_unique_ids": "Select elements by UniqueId and zoom to them in the active view. Changes the Revit UI selection and view only, not the model.",
    "revit_create_text_note": "Create a text note at an x/y position in a view of the active Revit document.",
    "revit_create_tag": "Tag one element at an x/y position in a view.",
    "revit_create_column": "Create a structural column of a given family type at an x/y point on a level. Coordinates are in feet.",
    "revit_create_beam": "Create a structural beam of a given family type between two x/y points on a level. Coordinates are in feet.",
    "revit_create_foundation": "Create a foundation element of a given family type at a point on a level. Coordinates are in feet.",
    "revit_create_duct": "Create a duct between two points at an elevation on a level, with a mechanical system type and duct type. Coordinates are in feet.",
    "revit_create_pipe": "Create a pipe between two points at an elevation on a level, with a piping system type and pipe type. Coordinates are in feet.",
    "revit_get_categories": "List the Revit categories available in the active document. Use it to find valid category names before listing elements. Read-only.",
    "revit_get_element_type": "Find element types by category name and family name in the active document.",
    "revit_close_document": "Close the active Revit document, optionally saving changes first.",
    "revit_create_new_document": "Create a new Revit project, optionally from a template file inside the allowed workspace.",
    "revit_export_dwg": "Export a view to a DWG file in a folder inside the allowed workspace; the file is named after the view. Writes a file; does not change the model.",
    "revit_export_ifc": "Export the model to an IFC file at a path inside the allowed workspace. Writes a file; does not change the model.",
    "revit_export_navisworks": "Export the model to a Navisworks NWC file at a path inside the allowed workspace. Writes a file; does not change the model.",
    "revit_export_image": "Export a view to an image file of the given pixel size at a path inside the allowed workspace. Writes a file; does not change the model.",
    "revit_render_3d": "Render a 3D view to an image file at a chosen quality level. Writes a file; does not change the model.",
    "revit_move_element": "Move one element by an offset vector in feet. Use revit_get_element_geometry to read its current location first.",
    "revit_copy_element": "Copy one element and place the copy at an offset vector in feet from the original.",
    "revit_rotate_element": "Rotate one element about a vertical axis through a centre point by an angle in radians.",
    "revit_mirror_element": "Mirror one element about a plane given by an origin point and a normal vector.",
    "revit_pin_element": "Pin an element so it cannot be moved by accident. Use revit_unpin_element to undo it.",
    "revit_unpin_element": "Unpin a previously pinned element so it can be moved again. Use revit_pin_element to pin it.",
    "revit_sync_to_central": "Synchronise a workshared model with the central model with a comment, optionally relinquishing ownership. Ignored if the document is not workshared.",
    "revit_relinquish_all": "Relinquish every element and workset the current user owns in a workshared model.",
    "revit_get_worksets": "List the worksets of a workshared model with their owners and open state. Use revit_get_document_info to check whether the model is workshared. Read-only.",
    "revit_create_schedule": "Create a schedule view for a category with the given name.",
    "revit_get_schedule_data": "Return the rows and columns of an existing schedule by schedule_id. Use revit_list_views_sheets_schedules to find schedule ids. Read-only.",
    "revit_get_element_bounding_box": "Return the axis-aligned bounding box (min and max corner, feet) of an element.",
    "revit_get_phases": "List the project phases of the active Revit document.",
    "revit_get_phase_filters": "List the phase filters of the active Revit document.",
    "revit_get_design_options": "List the design option sets and options of the active Revit document.",
    "revit_create_group": "Create a model group from a list of ElementIds, with a name.",
    "revit_ungroup": "Dissolve a model group into its member elements. Use revit_get_group_members first to see which elements it holds.",
    "revit_get_group_members": "List the member elements of a model group. Use revit_ungroup to dissolve the group. Read-only.",
    "revit_get_rvt_links": "List the linked Revit models (link types) in the active document. Use revit_get_link_instances for the placed instances. Read-only.",
    "revit_get_link_instances": "List the placed instances of linked Revit models in the active document. Use revit_get_rvt_links for the link types. Read-only.",
    "revit_create_conduit": "Create an electrical conduit between two points at a given diameter on a level. Coordinates and diameter are in feet.",
    "revit_check_clashes": "Check for geometric clashes between elements of two categories, within a tolerance (feet). Read-only.",
    "revit_create_material": "Create a new material with a colour, transparency, shininess and smoothness.",
    "revit_set_element_material": "Assign a material, by name, to an element or to one of its faces.",
    "revit_convert_to_group": "Convert a set of elements into a named model group.",
    "revit_edit_family": "Open a family for editing in the Revit family editor.",
    "revit_create_dimension": "Create a linear dimension between two points or two elements in the active view.",
    "revit_get_revision_sequences": "List the revision sequences defined in the active Revit document.",
    "revit_tag_all_in_view": "Tag every element of a category in the active view.",
    "revit_get_view_templates": "List the view templates available in the active Revit document.",
    "revit_apply_view_template": "Apply a view template to a view in the active Revit document.",
    "speckle_create_model": "Create a named model in the specified Speckle project.",
    "speckle_merge_branch": "Merge a source Speckle model into a target model in the specified project.",
    "revit_calculate_material_quantities": "Calculate material volumes and areas for all elements of a category. Read-only.",
    "revit_get_warnings": "Return the current warnings of the active Revit project (for example overlapping or duplicate elements). Use warnings_triage_review_warnings for a grouped review. Read-only.",
    "revit_invoke_method": (
        "Advanced escape hatch: call any public Revit API method by class and method name through reflection, "
        "optionally inside a transaction. Can change anything the Revit API can change; prefer a dedicated tool."
    ),
    "revit_reflect_get": "Advanced: read any public Revit API property of an object identified by target_id, through reflection. Needs plan approval because a getter on an arbitrary object can have side effects.",
    "revit_reflect_set": "Advanced escape hatch: set any writable Revit API property of an object identified by target_id, through reflection. Prefer a dedicated tool.",
    # --- Approval tools ----------------------------------------------------
    "plan_actions": (
        "Create a draft ActionPlan describing the model changes you want to make, capturing the before-state of each. "
        "Nothing is changed in the model; the plan must be approved before any write tool will run. "
        "Use it only when revit_get_context shows server.plans_required true; otherwise call the write tool directly with no plan_id."
    ),
    "list_pending_plans": "List the ActionPlans waiting for human approval, with their plan_id. Use it to find a plan_id after plan_actions; approval itself happens in the approval panel. Read-only.",
    "approve_plan": "Approve a pending ActionPlan so that its actions may be executed. This is the human approval step.",
    "reject_plan": "Reject and archive a pending ActionPlan so that it can never be executed.",
    "get_proof_bundle": "Return the proof bundle (plan hash, approver, document, per-element before and new values, skipped elements and execution outcome) of a finished ActionPlan. Read-only.",
    "plan_revert": "Draft a new ActionPlan that sets each parameter back to the before value recorded in an executed plan's proof bundle. Refuses if the plan was not fully executed, a before value is missing, or the model changed since. Never executes; the draft needs approval.",
    "rollback_plan": "Write back the recorded before-values of an already executed ActionPlan, in reverse order. Not a one-step Revit undo: an action without a rollback handler or a recorded before-value is skipped and reported as a warning, so the rollback can be partial. Revit's Ctrl+Z works per step. Untested in a live Revit session.",
    # --- Modules (panel commands) -----------------------------------------
    "module_list_commands": "List all registered modules and the commands they expose to the dockable Revit panel. Read-only.",
    "familytype_mapper_audit_families": "Audit the families in a saved snapshot and report problems such as unmapped or inconsistent family types. Read-only.",
    "familytype_mapper_list_type_mappings": "List family-type mappings found in a saved snapshot, optionally for one category. Read-only.",
    "model_bloat_audit": "Check a saved snapshot for model bloat: unused families and types (purge candidates), in-place families, families with very many types, imported CAD files, and a rough cleanliness score, sorted by likely impact. Read-only: it never deletes or purges; any clean-up must go through an approved plan.",
    "hello_world_say_hello": "Example module command that returns a greeting; use it to confirm the module system works.",
    "model_inspector_summarize_model": "Summarise a saved snapshot, for example element counts by category. Use it for a first overview; use snapshot_query or snapshot_compute for specific questions. Read-only.",
    "model_inspector_ask": "Answer a question about a saved snapshot by filtering its element records with the filter DSL. Read-only.",
    "model_inspector_list_groups": "List the model groups found in a saved snapshot. Read-only.",
    "model_inspector_inspect_selection": "Return the snapshot records of the given elements (by UniqueId) from a saved snapshot. Use revit_get_element_parameters to read the live model instead. Read-only.",
    "model_inspector_save_query": "Save a named filter query so it can be re-run later with model_inspector_run_saved_query.",
    "model_inspector_run_saved_query": "Run a previously saved named query against a saved snapshot. Read-only.",
    "model_inspector_list_saved_queries": "List the saved named queries. Read-only.",
    "naming_checker_check_names": "Check file names, sheet numbers and names, view names and level or grid names against the naming convention you provide (a pattern of named fields with allowed values per field). Reports pass or fail per name, which field failed and why, and a count summary. Read-only.",
    "naming_checker_list_example_conventions": "List the bundled example naming conventions. They use placeholder codes only and are not a standard. Read-only.",
    "parameter_manager_filter_params": "Return a parameter grid for the elements of a snapshot that match a filter, optionally including read-only parameters. Read-only.",
    "parameter_manager_diff_params": "Compare parameter values between two saved snapshots and list the differences. Read-only.",
    "parameter_manager_plan_set_params": "Create a draft ActionPlan that sets parameter values on the elements of a snapshot matching a filter. Review and approve the plan before it runs.",
    "parameter_manager_export_params_csv": "Export parameters of the matching snapshot elements to a CSV file in the workspace. Writes a file; does not change the model.",
    "parameter_manager_import_params_csv": "Read parameter values from a CSV file in the workspace and create a draft ActionPlan that applies them. Does not change the model; review and approve the plan before it runs.",
    "param_completeness_heatmap": "Measure how many elements have a value in each parameter, per category (and per level on request), from a saved snapshot: filled, total and percent. Writes an optional CSV and a self-contained HTML heatmap to the workspace, and says when the snapshot is a partial capture. Use model_inspector_summarize_model for plain counts instead. Read-only.",
    "model_health_score": "Give a 0 to 100 health score for a saved snapshot with its components, and a trend across all saved snapshots of the same document with changes between captures. Inputs the snapshot lacks are listed as excluded, not scored as zero. Optional CSV, and an optional self-contained HTML dashboard (html_filename) that adds top issues from the latest stored QA/QC run and parameter completeness. Read-only.",
    "ids_validator_validate_ifc": "Check an IFC file in the workspace against a buildingSMART IDS file and return pass or fail per specification with the GlobalIds of failing entities (capped, with full counts). Optional HTML or JSON report in the workspace. Needs the optional ids extra (ifctester). Read-only.",
    "parameter_manager_export_params_xlsx": "Export parameters of the matching snapshot elements to an Excel workbook in the workspace for editing. Writes a file; does not change the model.",
    "parameter_manager_import_params_xlsx": "Read an edited Excel workbook from the workspace, diff it against the snapshot and create a draft ActionPlan with a row diff. Does not change the model; review and approve the plan before it runs.",
    "qa_handover_build_report": "Write a short hand-over report (JSON and Markdown in the workspace) of QA findings per rule, before/after re-check counts, approved parameter changes from plan proof bundles, and an explicit not-verified list; use this instead of qaqc_checker_run_check or model_changes_compare_snapshots when the result must be handed to someone else. Built from saved data only. Read-only.",
    "model_changes_list_snapshots": "List the saved model snapshots with their timestamps, newest first, so you can pick the latest and previous ones to compare. Read-only.",
    "model_changes_compare_snapshots": "Say what changed between two saved snapshots: elements added, removed or modified, parameter values before and after, and counts per category. Read-only.",
    "links_worksets_audit_audit": "Check linked models and worksets for problems (unloaded or missing links, links not pinned or placed Origin to Origin, empty or default-named worksets, worksets owned by someone else, elements on the wrong workset) and give plain next steps. Read-only.",
    "qaqc_checker_run_check": "Run a QA/QC rule pack against a saved snapshot and record the issues it finds. Take the snapshot first with snapshot_take; read the results with qaqc_checker_list_issues. Does not change the Revit model.",
    "qaqc_checker_list_issues": "List recorded QA/QC issues for a document, optionally filtered by status, severity and snapshot. Hides stale issues (not seen in the latest run) unless include_stale is true. Read-only.",
    "qaqc_checker_resolve_issue": "Mark one recorded QA/QC issue as resolved. It changes only the issue record in the workspace, not the Revit model. Find issue ids with qaqc_checker_list_issues.",
    "clash_triage_import_clash_report": "Read a Navisworks XML clash report or a BCF .bcfzip from the workspace, match each clash to Revit elements by GUID, group clashes by element pair and level, and list unmatched items with the reason. Never changes the model; records the result as issues in the workspace.",
    "clash_triage_match_clashes": "Match each clash from a Navisworks clash test to the Revit elements it involves, by UniqueId or IFC GUID, and say how sure each match is (exact, ambiguous or unmatched). Never guesses and never changes the model; records the result as issues in the workspace.",
    "clash_triage_list_clash_issues": "List the clash issues recorded by clash triage, optionally filtered by status and match confidence. Read-only.",
    "qaqc_checker_list_rule_packs": "List the built-in QA/QC rule packs and the user packs in the workspace rule_packs folder, with a validity flag for each. Read-only.",
    "qaqc_checker_validate_rule_pack": "Schema-check a YAML rule pack and return actionable errors per rule (id, severity, required fields, unknown operators). Never executes the rules. Read-only.",
    "qaqc_checker_import_rule_pack": "Validate a YAML rule pack inside the workspace and copy it into the workspace rule_packs folder. Refuses invalid packs and existing names unless overwrite is true.",
    "qaqc_checker_export_rule_pack": "Copy a validated built-in or workspace rule pack to a YAML file inside the workspace so it can be shared. Refuses to overwrite unless overwrite is true.",
    "qaqc_checker_test_naming_rule": "Test a proposed naming rule (category, regex, message, severity) against a saved snapshot and return how many names match and miss, with a capped sample of each. Read-only; saves nothing. Rejects invalid and catastrophic-backtracking regexes.",
    "qaqc_checker_save_naming_rule": "Save a tested naming rule to the workspace naming_rules folder so it can be replayed without a model. Writes a file, so it runs only as an approved plan action. Refuses invalid or catastrophic regexes and existing ids unless overwrite is true.",
    "qaqc_checker_replay_naming_rules": "Replay the saved naming rules against a saved snapshot with no model call. The same snapshot gives the same findings. Returns the rule hashes and appends them to the workspace naming rules audit log.",
    "qaqc_checker_list_rules": "List the QA/QC rules that are available, optionally for one rule pack. Use qaqc_checker_list_rule_packs to see the packs first. Read-only.",
    "sheet_view_audit_run_audit": "Check the sheets and views in a saved snapshot for empty sheets, unplaced views, duplicate sheet numbers, missing sheet parameters and default view names. Read-only.",
    "geometry_screening_run_checks": "Screen a saved snapshot with repeatable geometric checks: room area against a brief table, door width against a minimum, a turning circle inside a room outline, and travel distance through doors to exit rooms. Each finding names element ids, the measured value, the threshold and the unit. Refuses when the room outlines or door data a check needs are missing. A screening aid, not a code compliance check. Read-only.",
    "schedule_diff_compare": "Compare two saved snapshots by their sheet list, sheet revision fields and schedule rows: sheets added, removed, renumbered, renamed or moved in the numbering order, revision fields changed, and schedule rows added, removed, changed or moved. A block a snapshot does not hold (schedule rows are not captured yet) is reported as not captured, never as no change. Compact by default; optional .csv or .xlsx export in the workspace. Read-only.",
    "sheet_set_qa_check": "Check the sheets in a saved snapshot before a drawing issue: duplicate or equivalent sheet numbers, gaps in the numbering within a prefix, empty title block fields (configurable, defaults Sheet Number, Sheet Name, Drawn By, Checked By, Sheet Issue Date), sheets with no placed views, and numbers or names that break a regex. Findings have severities; checks the snapshot cannot support are reported as not run. Optional CSV in the workspace. Use sheet_view_audit_run_audit for unplaced views and view names. Read-only.",
    "schedule_consistency_check_doors_and_rooms":"Check door and room schedules in a saved snapshot for duplicate or missing Marks, missing or identical From/To rooms, unnumbered or duplicate room numbers and zero-area rooms, and optionally Marks that do not fit a pattern you supply. Read-only; any suggested Marks are a proposal only.",
    "mark_renumber_plan_analyze": "Find duplicate marks, empty marks, gaps and out-of-order sequences for doors, rooms and windows in a saved snapshot, and propose a new numbering from a small rule file (doors: To room number plus a letter; rooms and windows: level prefix plus sequence). Read-only.",
    "mark_renumber_plan_draft_plan": "Draft one plan_actions-ready list of parameter writes for the proposed mark numbering. Swaps and chains go through temporary values. Refused if the final numbering would hold a duplicate. Read-only; a person must approve the plan.",
    "warnings_triage_review_warnings": "Group the open project's Revit warnings by type, rank them by how many elements they touch, flag duplicate marks, overlapping elements and rooms not enclosed for the coordinator, and suggest a next step for each group. Read-only.",
    "revit_check_joins": "Check wall joins in the live model: for every end of the selected walls (ids, or a Comments tag) report whether it is joined to another wall, to which, and the join type. Use after building walls; a free end is a FAIL unless its join is switched off or you list it in allow_free_ids. Returns a summary such as '27 ends checked, 0 unjoined', FAIL lines and a pageable list (default 50 rows). Read-only; for overlapping volumes use revit_check_intersections, for wall facing use revit_check_orientation.",
    "revit_check_intersections": "Measure solid/solid overlaps in the live model between two sets of elements (ids, Comments tag, categories): boolean-intersection volume in m3, pairs sorted largest first, with categories, ids and location; bounding boxes are only a pre-filter. Use it after building walls, floors, roofs or columns to prove they do not overlap. mode 'bbox' falls back to bounding boxes only (what revit_check_clashes does, false positives likely). Stops with a partial result at a time or pair budget. Read-only; summary, FAIL lines and a pageable list (default 50 rows).",
    "revit_warnings_delta": "Track Revit warnings across a build phase. Call without baseline_id before the phase to save a baseline (returns baseline_id and counts); call with that baseline_id afterwards to list warnings that are new and closed, with element ids. Pass tag_prefix (your Comments prefix) so only new warnings on your own elements are FAIL. Use revit_get_warnings or warnings_triage_review_warnings for a one-off grouped view of all current warnings instead. Read-only; it saves only the baseline file in the workspace.",
    "revit_check_orientation": "Check that walls face the right way: probes 0.6 m along each exterior wall's Orientation (the exterior side) and reports walls whose probe lands inside a room, which means the wall is flipped. Use after building walls and placing rooms; with no rooms in the model it says UNVERIFIED. Select walls by ids, Comments tag or category. Read-only; summary, FAIL lines and a pageable list (default 50 rows). For joins use revit_check_joins.",
    "revit_audit_openings": "Inspect scoped doors and windows for host, fit, dimensions and wall cuts, using ray or volume evidence when available. Supply ids, a Comments tag or categories. Read-only; unavailable geometry is UNVERIFIED, never proof of a cut.",
    "revit_audit_roofs": "Inspect scoped roofs for heights, slopes, coverage, exposed edges and stair openings. Supply ids, a Comments tag or categories and the optional expected geometry. Read-only; missing expectations or geometry are reported as unverified.",
    "revit_probe_family": "Inspect a family for category, nested instances, parameters, connectors and geometry. Read-only; optional deep inspection opens and closes a family document without saving, and reports any inspection or close failure.",
    "revit_system_report": "Inspect scoped MEP elements for connector domains, system membership, connections, open ends and size differences. Intentional open ends can be listed explicitly. Read-only; reports topology facts, not engineering sizing.",
    "revit_check_naming_and_params": "Check scoped elements for required parameter values, duplicate Marks and names matching a supplied pattern. Supply ids, a Comments tag or categories. Read-only; returns measured failures and bounded details.",
    "revit_check_levels_grids": "Check scoped levels and grids for missing plan views, duplicate elevations and coincident grids, using the supplied tolerance. Read-only; budgets and incomplete checks are reported explicitly.",
    "revit_review": "Run selected read-only Revit checks for an explicit scope and return FAIL, PASS or INCOMPLETE with evidence. Include a warnings baseline for a warnings diff. Missing data, empty checks and truncated geometry cannot produce a verified PASS; image review remains separate.",
    "revit_api_lookup": "Check that a Revit API type, member or overload really exists before you use it in a revit_execute_python script, and get its exact signature. Answers from the RevitAPI.xml / RevitAPIUI.xml documentation of an installed Revit (2024-2027) or the NuGet cache, without Revit running; every answer names the Revit year. A name that does not exist returns NOT FOUND with the nearest real names. The XML has no return types or inheritance. No docs found means UNVERIFIED. Use revit_inspect_elements to see the values of real elements in the open model, and revit_execute_python mode='read' to test behaviour. Read-only; no network.",
    "revit_list_views_sheets_schedules": "List views, sheets, schedules and view templates in the active document, with filters, placement status and pagination. Read-only; no model changes.",
    "revit_render_check": "Export a view to a workspace PNG and inspect its pixel content for a blank image. Reports the actual file path and bytes separately from image-analysis verification; unsupported or corrupt images remain unverified. Read-only to the model.",
    "revit_make_view": "Create a framed 3D, plan, section or elevation view under an approved action. Replaces only owned content; refuses a deletion cascade touching foreign dependencies and checks that level names remain unchanged.",
    "revit_make_sheet": "Create a tagged sheet and place supplied views under an approved action. A rerun replaces owned content only and refuses deletion of foreign dependent placements. Returns changed ids and post-check evidence.",
    "revit_make_schedule": "Create a tagged schedule with requested fields, sorting and filters under an approved action. Replaces owned content only and reports failed steps or post-checks rather than claiming success.",
    "revit_export": "Export selected sheets or views as PDF or DWG, or the model as IFC or NWC, inside the workspace under an approved action. Reports actual output files and sizes; existing output names are refused unless overwrite is explicit.",
    "revit_make_family": "Make loadable Revit families from data (name, category, box size, pipe, duct or electrical ports) under an approved action: builds from a family template, saves the .rfa inside the workspace, loads it and checks it with revit_probe_family. Refuses a category that does not fit the port kinds and fails with a clear message when no template is found. Rolls back on failure unless on_error is skip.",
    "bcf_exchange_export_bcf": "Save issues (your own list and/or the recorded QA/QC issues) to a BCF 2.1 .bcfzip file in the workspace. Writes a file; does not change the model. Not yet checked against other BCF tools.",
    "bcf_exchange_import_bcf": "Read a BCF .bcfzip file from the workspace and return its issues (title, description, status, priority, element ids). Read-only; unsafe zip files are refused.",
    "recipe_runner_run_recipe": "Run a named automation recipe (a YAML-defined sequence of tool calls) with arguments; set dry_run to list the steps without executing them.",
    "recipe_runner_list_recipes": "List the available automation recipes. Read-only.",
    "recipe_runner_list_runs": "List past recipe runs, optionally for one recipe. Read-only.",
    "recipe_runner_get_run_status": "Return the status and results of one recipe run. Read-only.",
    "report_generator_export_excel": "Export a snapshot (optionally filtered, with chosen parameters and QA/QC findings) to an Excel workbook in the workspace. Writes a file; does not change the model.",
    "report_generator_build_review_pack": "Build one Excel 'Model review' workbook from a snapshot: cover, findings from the QA/QC rules, counts by category and what to do next. Writes a file; does not change the model.",
    "pyrevit_bridge_list_pyrevit_scripts": "List pyRevit pushbutton scripts found in the directories named by MCP_REVIT_PYREVIT_EXTENSION_DIRS, with tab, panel, description and whether obvious write calls were detected. Read-only.",
    "pyrevit_bridge_plan_run_pyrevit_script": "Create a draft ActionPlan for running one pyRevit script, showing its path, SHA-256 and detected write-call lines. Never executes the script.",
    "pyrevit_bridge_run_pyrevit_script": "Run a pyRevit script inside Revit after its plan was approved and only if its SHA-256 still matches the plan. The Revit-side runner is not implemented yet, so this currently reports bridge_unavailable.",
    "report_generator_export_sqlite_summary": "Export a summary of a snapshot to a SQLite database file in the workspace. Writes a file; does not change the model.",
    "selection_tools_set_selection": "Select the given elements (by UniqueId) in the Revit UI. Does not modify the model.",
    "selection_tools_save_selection": "Save a set of element UniqueIds under a name for later restore.",
    "selection_tools_restore_selection": "Re-select a previously saved named selection in the Revit UI.",
    "selection_tools_select_by_query": "Select in Revit the elements of a snapshot that match a filter query. It changes only the Revit UI selection, not the model. Use snapshot_query to list matches without selecting them.",
    "selection_tools_list_saved_selections": "List the saved named selections. Read-only.",
    "selection_tools_group_rename": "Rename a model group identified by its UniqueId.",
    "selection_tools_group_ungroup": "Ungroup a model group identified by its UniqueId. Its members stay in the model as separate elements.",
    "selection_tools_group_convert_to_detail": "Convert a model group into a detail group.",
    # --- Navisworks --------------------------------------------------------
    "navisworks_health": "Check that the Navisworks bridge is reachable and return its status.",
    "navisworks_get_document_info": "Return metadata about the active Navisworks document. Read-only.",
    "navisworks_get_model_tree": "Return the model hierarchy tree of the active Navisworks document down to a maximum depth. Read-only.",
    "navisworks_get_selection": "Return the items currently selected in Navisworks. Read-only.",
    "navisworks_append_file": "Append a model file (for example NWD, NWC or IFC) from the allowed workspace to the active Navisworks document.",
    "navisworks_refresh": "Refresh all appended files that changed on disk in the active Navisworks document.",
    "navisworks_list_viewpoints": "List the saved viewpoints of the active Navisworks document. Read-only.",
    "navisworks_create_viewpoint": "Create a saved viewpoint with the given name from the current view.",
    "navisworks_activate_viewpoint": "Switch the Navisworks view to a saved viewpoint identified by its Guid.",
    "navisworks_list_clash_tests": "List the clash tests defined in Clash Detective. Read-only.",
    "navisworks_run_clash_test": "Run one Clash Detective test, identified by Guid, and update its results.",
    "navisworks_get_clash_results": "Return the results of one clash test, with paging by skip and limit. Read-only.",
    "navisworks_invoke_method": "Advanced escape hatch: call a public C# method in Navisworks through reflection. Prefer a dedicated tool.",
    "navisworks_reflect_get": "Advanced: read a C# property of a Navisworks object through reflection. Needs plan approval because a getter on an arbitrary object can have side effects.",
    "navisworks_reflect_set": "Advanced escape hatch: set a C# property of a Navisworks object through reflection.",
    # --- Rhino -------------------------------------------------------------
    "rhino_health": "Check that the Rhino bridge is reachable and healthy.",
    "rhino_get_document_info": "Return the active Rhino document name, path, unit system and object count. Read-only.",
    "rhino_get_lines": "Return all curves and lines in the active Rhino document. Read-only.",
    "rhino_get_scene": "Return every object in the Rhino scene with its type, layer and bounding box. Read-only.",
    "rhino_list_layers": "List all layers of the Rhino document with name, colour, visibility and lock state. Read-only.",
    "rhino_clear_scene": "Delete all objects in the Rhino document, or only the objects on one layer.",
    "rhino_reflect_get": "Advanced: read a C# property of a Rhino object through reflection. Needs plan approval because a getter on an arbitrary object can have side effects.",
    "rhino_invoke_method": "Advanced escape hatch: call a public C# method on a Rhino object through reflection. Prefer a dedicated tool.",
    "rhino_reflect_set": "Advanced escape hatch: set a C# property of a Rhino object through reflection.",
    # --- Graph / Speckle / jobs / snapshots --------------------------------
    "snapshot_take": "Extract and save a semantic BIM snapshot of the active Revit model into the workspace and return its snapshot_id. Large models are captured within a size and time limit (truncated=true says so); scope it with categories.",
    "snapshot_query": "Query the element records of a saved snapshot with the filter DSL. Use it for filtered lists; use snapshot_compute for joins, grouping and counts. Read-only.",
    "snapshot_compute": "Answer a model question in one call: a read-only pipeline of steps (join, where, group, aggregate, sort, select) over a saved snapshot. Read-only.",
    "snapshot_diff": "Compare two saved snapshots and report added, deleted and modified elements. Take both snapshots with snapshot_take first. Read-only.",
    "speckle_health": "Check that the Speckle provider is configured and report whether it can reach the Speckle server.",
    "speckle_auth_status": "Report the current Speckle OAuth authentication status of this server (signed in or not).",
    "speckle_oauth_refresh": "Refresh the Speckle OAuth access token so later Speckle calls keep working.",
    "speckle_list_projects": "List the Speckle projects the signed-in user can access, up to a limit.",
    "speckle_get_version_metadata": "Read the metadata of one Speckle version by project and version ID. Read-only.",
    "speckle_checkout_version": "Retrieve the metadata of one Speckle version by ID. Does not change data on the Speckle server.",
    "job_status":"Return the status, progress, result or error of a background job started with run_async. Use it to poll a job; use job_cancel to stop one. Read-only.",
    "job_cancel": "Cancel a running or queued background job by job_id. Use job_status to check the job first.",
}

# --------------------------------------------------------------------------- #
# Parameter descriptions, used only where a schema property has none.
# Lookup order: (tool, param) -> (provider, param) -> param
# --------------------------------------------------------------------------- #
PARAM_DESCRIPTIONS: dict[str, str] = {
    "element_id": "Revit ElementId (integer) of the target element.",
    "element_ids": "List of Revit ElementIds (integers).",
    "element_uids": "List of Revit UniqueIds (strings) of the target elements.",
    "name": "Name to give to the new item.",
    "categories": "Revit categories to capture, for example [\"Doors\", \"Rooms\"] (names with or without the OST_ prefix). Omit for the default element set, which is limited in size on large models.",
    "max_elements": "Largest number of elements to capture in one snapshot. The capture also stops at a time limit and reports truncated=true.",
    "snapshot_id": "ID of a saved semantic snapshot (returned by snapshot_take or revit_extract_snapshot).",
    "snapshot_a_id": "ID of the first (baseline) saved snapshot.",
    "snapshot_b_id": "ID of the second (comparison) saved snapshot.",
    "x": "X coordinate in feet (Revit internal units).",
    "y": "Y coordinate in feet (Revit internal units).",
    "z": "Z coordinate or elevation in feet (Revit internal units).",
    "start_x": "Start point X in feet.",
    "start_y": "Start point Y in feet.",
    "start_z": "Start point Z in feet.",
    "end_x": "End point X in feet.",
    "end_y": "End point Y in feet.",
    "end_z": "End point Z in feet.",
    "center_x": "X of the rotation centre in feet.",
    "center_y": "Y of the rotation centre in feet.",
    "center_z": "Z of the rotation centre in feet.",
    "plane_origin_x": "X of a point on the mirror plane, in feet.",
    "plane_origin_y": "Y of a point on the mirror plane, in feet.",
    "plane_origin_z": "Z of a point on the mirror plane, in feet.",
    "plane_normal_x": "X component of the mirror plane normal vector.",
    "plane_normal_y": "Y component of the mirror plane normal vector.",
    "plane_normal_z": "Z component of the mirror plane normal vector.",
    "angle_radians": "Rotation angle in radians (counter-clockwise positive).",
    "level": "Name of the Revit level, for example 'Level 1'.",
    "level_name": "Name of the Revit level, for example 'Level 1'.",
    "family_name": "Name of the loaded Revit family.",
    "type_name": "Name of the family type within the family.",
    "family_symbol_id": "ElementId (integer) of the family symbol (type).",
    "family_instance_id": "ElementId (integer) of the family instance.",
    "category": "Revit category name, for example 'Walls', 'Doors' or 'Windows'.",
    "category_name": "Revit category name, for example 'Walls', 'Doors' or 'Windows'.",
    "category1": "First Revit category name, for example 'Ducts'.",
    "category2": "Second Revit category name, for example 'Structural Framing'.",
    "view_id": "Revit ElementId (integer) of the view.",
    "view_name": "Name for the new view.",
    "sheet_id": "Revit ElementId (integer) of the sheet.",
    "schedule_id": "Revit ElementId (integer) of the schedule.",
    "titleblock_id": "ElementId (integer) of the title block family type.",
    "titleblock_name": "Name of the title block family type.",
    "template_id": "ElementId (integer) of the view template.",
    "template_path": "Path of a Revit template file inside the allowed workspace.",
    "wall_id": "ElementId (integer) of the host wall.",
    "group_id": "ElementId (integer) of the model group.",
    "group": "Parameter group the parameter is shown under.",
    "type": "Data type of the parameter.",
    "visible": "Whether the parameter is visible in the properties palette.",
    "output_path": "Destination file path; must be inside the allowed workspace directories.",
    "output_filename": "File name for the output, written into the workspace.",
    "csv_path": "Path of a CSV file inside the allowed workspace.",
    "csv_sha256": "Set by the server in plan_actions: sha256 of the CSV content. Copy it from the plan; a changed CSV is refused.",
    "csv_row_count": "Set by the server in plan_actions: number of sheet rows in the CSV, shown for review.",
    "csv_filename": "Name of a CSV file in the workspace.",
    "xlsx_filename": "Name of an Excel .xlsx workbook in the workspace root, such as doors.xlsx.",
    "path": "File path; must be inside the allowed workspace directories.",
    "limit": "Maximum number of items to return.",
    "skip": "Number of items to skip (for paging).",
    "offset": "Number of items to skip (for paging).",
    "idempotency_key": "Optional unique key; repeating a call with the same key does not repeat the write.",
    "plan_id": "ID of an ActionPlan (from plan_actions).",
    "review": "Optional reviewable rationale shown to the approver and covered by the plan hash: an object with summary, reasoning, citations [{rule_id, clause, source}], assumptions [string], excluded [{element_id, reason}] and warnings [string]. Unknown keys and over-long text are refused.",
    "skipped": "Elements or parameters excluded when drafting (for example the blocked list of a parameter plan), each with a reason.",
    "approver": "Name of the person approving the plan; recorded in the proof bundle but not authenticated.",
    "allow_conflicts": "If true, draft the revert even where the model's current value differs from the value the plan wrote, listing those elements as conflicts for explicit review.",
    "actions": "List of proposed tool calls, each with a tool name and its arguments.",
    "parameter_name": "Name of the Revit parameter.",
    "param_name": "Name of the parameter.",
    "param_names": "List of parameter names.",
    "value": "New value to write; a string, number or boolean that matches the parameter's type.",
    "location": "Location object with x, y and optional z in feet.",
    "height": "Height in feet.",
    "width": "Width in pixels.",
    "quality": "Render quality level.",
    "tolerance": "Distance tolerance in feet.",
    "radius": "Radius in the document's units.",
    "diameter": "Diameter in feet.",
    "system_type": "Name of the system type (for example a piping or duct system).",
    "duct_type": "Name of the duct type.",
    "pipe_type": "Name of the pipe type.",
    "text": "Text content.",
    "comment": "Comment recorded with the operation.",
    "relinquish": "Whether to relinquish ownership of elements and worksets after syncing.",
    "save_changes": "Whether to save changes before closing.",
    "with_views": "Whether to also duplicate the views placed on the sheet.",
    "duplicate_option": "How to duplicate the sheet's content (Revit duplicate option name).",
    "prefix": "Prefix for the new sheet numbers.",
    "start_number": "First number to use.",
    "parameters": "Map of parameter name to value.",
    "color": "Colour as an object with r, g and b values (0-255) or, for Rhino, an [r, g, b] array.",
    "transparency": "Transparency of the material.",
    "shininess": "Shininess of the material (0-100).",
    "smoothness": "Smoothness of the material (0-100).",
    "reflectivity": "Reflectivity of the material (0-1).",
    "material_name": "Name of an existing material.",
    "start_point": "Start point as an object with x, y and z in feet.",
    "end_point": "End point as an object with x, y and z in feet.",
    "element1_id": "ElementId (integer) of the first element.",
    "element2_id": "ElementId (integer) of the second element.",
    "use_transaction": "Wrap the call in a Revit transaction.",
    "max_depth": "Maximum tree depth to return.",
    "filter": "Filter DSL object selecting records, for example by category, level or parameter value.",
    "element_filter": "Filter DSL object selecting elements, for example by category, level or parameter value.",
    "include_readonly": "Whether to include read-only parameters.",
    "doc_guid": "GUID of the document the issues belong to.",
    "severity": "Severity filter, for example 'error' or 'warning'.",
    "issue_id": "ID of the QA/QC issue.",
    "rule_pack": "Name of the QA/QC rule pack: a built-in such as 'core' or a pack saved in the workspace rule_packs folder.",
    "source_path": "YAML rule pack file; must be inside the allowed workspace directories.",
    "destination": "Target YAML file or directory; must be inside the allowed workspace directories.",
    "overwrite": "Whether to replace an existing file or pack with the same name.",
    "class_name": "Fully qualified class name that holds the method to call.",
    "method_name": "Name of the method to call.",
    "arguments": "Positional arguments for the method, as a JSON array.",
    "target_id": "Identifier of the target object (for example a Revit ElementId).",
    "property_name": "Name of the property.",
    "guid": "Guid of the item, as returned by the corresponding list command.",
    "node_ids": "List of graph node IDs.",
    "message": "Message recorded with the operation.",
    "number": "Number (identifier string) to assign.",
    "project_id": "ID of the Speckle project.",
    "model_id": "ID of the Speckle model.",
    "version_id": "ID of the Speckle version.",
    "branch_id": "ID of the Speckle branch.",
    "object_id": "ID of the Speckle object to publish.",
    "source_model_id": "ID of the Speckle model or branch to merge from.",
    "target_model_id": "ID of the Speckle model or branch to merge into.",
    "source_application": "Name of the application the data comes from.",
    "description": "Free-text description.",
    "layer": "Name of the Rhino layer.",
    "ids": "List of Rhino object GUIDs.",
    "base_id": "GUID of the base Rhino object.",
    "cutter_ids": "List of GUIDs of Rhino objects to subtract.",
    "rotation": "Rotation object (angle and axis).",
    "node_id": "ID of the graph node.",
    "related_node_id": "ID of the related graph node.",
    "relation": "Relation type, for example SUPPORTED_BY.",
    "direction": "Relation direction to follow: incoming or outgoing.",
    "relation_types": "List of relation types to consider.",
    "node_types": "List of node types to consider.",
    "min_degree": "Minimum number of connections a node must have.",
    "attributes": "Free-form attributes stored on the relation.",
    "code": "Authorization code returned by the OAuth flow.",
    "state": "State value returned by the OAuth flow.",
    "source_id": "Identifier to translate.",
    "model_name": "Name of the Speckle model.",
    "data": "JSON object to send.",
}

# Per-tool overrides where the generic text would be wrong or vague.
TOOL_PARAM_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("revit_move_element", "x"): "X component of the offset vector in feet.",
    ("revit_move_element", "y"): "Y component of the offset vector in feet.",
    ("revit_move_element", "z"): "Z component of the offset vector in feet.",
    ("revit_copy_element", "x"): "X component of the offset vector in feet.",
    ("revit_copy_element", "y"): "Y component of the offset vector in feet.",
    ("revit_copy_element", "z"): "Z component of the offset vector in feet.",
    ("revit_place_viewport_on_sheet", "x"): "X position on the sheet in feet.",
    ("revit_place_viewport_on_sheet", "y"): "Y position on the sheet in feet.",
    ("revit_create_text_note", "x"): "X position in the view in feet.",
    ("revit_create_text_note", "y"): "Y position in the view in feet.",
    ("revit_create_tag", "x"): "X position in the view in feet.",
    ("revit_create_tag", "y"): "Y position in the view in feet.",
    ("revit_create_level", "name"): "Name of the new level.",
    ("revit_create_grid", "name"): "Name (label) of the new grid line.",
    ("revit_create_room", "name"): "Name of the new room.",
    ("revit_create_room", "number"): "Room number.",
    ("revit_create_sheet", "name"): "Name of the new sheet.",
    ("revit_create_sheet", "number"): "Sheet number, for example 'A101'.",
    ("revit_create_schedule", "name"): "Name of the new schedule.",
    ("revit_create_material", "name"): "Name of the new material.",
    ("revit_create_group", "name"): "Name of the new group.",
    ("revit_convert_to_group", "name"): "Name of the new group.",
    ("revit_create_shared_parameter", "name"): "Name of the new shared parameter.",
    ("revit_create_project_parameter", "name"): "Name of the new project parameter.",
    ("revit_create_project_parameter", "categories"): "Revit categories to bind the parameter to, for example [\"Walls\", \"Doors\"] (names or OST_ names).",
    ("revit_create_shared_parameter", "categories"): "Revit categories to bind the parameter to, for example [\"Walls\", \"Doors\"] (names or OST_ names).",
    ("revit_create_shared_parameter", "group"): "Parameter group shown in Revit: Data (default), IdentityData, Text, Constraints, Dimensions, General, Graphics, Materials, Construction or Phasing.",
    ("revit_create_project_parameter", "group"): "Parameter group shown in Revit: Data (default), IdentityData, Text, Constraints, Dimensions, General, Graphics, Materials, Construction or Phasing.",
    ("revit_create_shared_parameter", "is_instance"): "True (default) for an instance parameter, false for a type parameter.",
    ("revit_create_project_parameter", "is_instance"): "True (default) for an instance parameter, false for a type parameter.",
    ("revit_create_shared_parameter", "definition_group"): "Group in the shared parameter file for a new definition. Default 'AEC Model Bridge'.",
    ("revit_create_shared_parameter", "type"): "Parameter data type: Text (default), Integer, Number, Length, Area, Volume, Angle, Currency, YesNo, URL or Material.",
    ("revit_create_project_parameter", "type"): "Parameter data type: Text (default), Integer, Number, Length, Area, Volume, Angle, Currency, YesNo, URL or Material.",
    ("revit_preview_elements", "element_uids"): "UniqueIds of the elements to preview.",
    ("revit_preview_elements", "element_ids"): "ElementIds (integers) of the elements to preview; combined with element_uids.",
    ("revit_preview_elements", "isolate"): "Temporarily isolate the elements in the active view (default true); false only selects and zooms.",
    ("revit_render_3d", "view_id"): "ElementId (integer) of the 3D view to render.",
    ("revit_create_floor_plan_view", "view_name"): "Name for the new floor plan view.",
    ("revit_check_clashes", "tolerance"): "Clash tolerance in feet (the add-in defaults to 0.01 ft).",
    ("revit_get_type_parameters", "element_id"): "ElementId (integer) of any element of the type to read.",
    ("revit_set_element_material", "face_index"): "Optional index of a single face; omit to apply to the whole element.",
    ("revit_save_document", "path"): "Optional path to save to; must be inside the allowed workspace directories. Omit to save in place.",
    ("navisworks_create_viewpoint", "name"): "Name of the new saved viewpoint.",
    ("navisworks_append_file", "path"): "Path of the file to append; must be inside the allowed workspace directories.",
    ("navisworks_get_clash_results", "limit"): "Maximum number of clash results to return.",
    ("hello_world_say_hello", "name"): "Name to greet.",
    ("graph_add_relation", "source_id"): "ID of the source graph node.",
    ("graph_add_relation", "target_id"): "ID of the target graph node.",
    ("graph_add_relation", "relation"): "Relation type, for example SUPPORTED_BY.",
    ("speckle_create_model", "name"): "Name of the new Speckle model.",
    ("speckle_create_branch", "name"): "Name of the new Speckle branch.",
    ("speckle_create_model", "description"): "Optional description of the new model.",
    ("speckle_create_branch", "description"): "Optional description of the new branch.",
    ("rhino_set_view", "view"): "Display mode or projection to switch to.",
    ("rhino_create_box", "min_pt"): "Minimum corner as [x, y, z] in metres.",
    ("rhino_create_box", "max_pt"): "Maximum corner as [x, y, z] in metres.",
    ("rhino_create_sphere", "center"): "Centre as [x, y, z] in metres.",
    ("rhino_create_sphere", "radius"): "Radius in metres.",
    ("rhino_create_cylinder", "base"): "Base centre as [x, y, z] in metres.",
    ("rhino_create_cylinder", "height"): "Height in metres.",
    ("rhino_create_cylinder", "radius"): "Radius in metres.",
    ("rhino_boolean_union", "layer"): "Layer to place the resulting object on.",
    ("rhino_set_material", "layer"): "Apply the material to every object on this layer.",
    ("rhino_set_material", "ids"): "GUIDs of the objects to apply the material to.",
    ("rhino_set_material", "name"): "Name of the material.",
    ("rhino_set_material", "color"): "Material colour as an [r, g, b] array (0-255).",
    ("rhino_set_material", "transparency"): "Transparency of the material (0-1).",
    ("rhino_transform_objects", "ids"): "GUIDs of the objects to transform.",
    ("rhino_transform_objects", "translation"): "Translation vector [x, y, z] in metres.",
    ("rhino_transform_objects", "scale"): "Scale factors [x, y, z].",
    ("rhino_run_python", "code"): "IronPython source to run inside Rhino; stdout is captured and returned.",
    ("revit_list_commands", "contains"): "Only list commands whose name contains this text, for example wall.",
    ("revit_list_commands", "mutating"): "true lists only commands that change the model, false only read-only ones.",
    ("revit_invoke_method", "class_name"): "Revit API type name, for example Wall or Autodesk.Revit.DB.Wall.",
    ("revit_invoke_method", "method_name"): "Name of the public method to call.",
    ("revit_invoke_method", "arguments"): "JSON array of arguments: numbers, strings, booleans, {x,y,z} for an XYZ, or {\"type\":\"reference\",\"id\":\"...\"} for an element id or obj_N handle.",
    ("revit_invoke_method", "use_transaction"): "true when the call changes the model and needs its own transaction.",
    ("revit_raw_command", "command"): "Name of the Revit add-in command to run, for example revit.create_wall or revit.list_levels.",
    ("revit_raw_command", "payload"): "Native payload object for that command, exactly as the add-in reads it (lengths in Revit internal feet).",
    ("revit_execute_python", "script"): "Python/IronPython source to run inside Revit with access to the Revit API.",
    ("revit_invoke_method", "target_id"): "Identifier of the object to call the method on; omit for a static method.",
    ("revit_reflect_set", "value"): "New value for the property.",
    ("navisworks_reflect_set", "value"): "New value for the property.",
    ("rhino_reflect_set", "value"): "New value for the property.",
    ("ifc_get_properties", "element_id"): "GlobalId or step id of the IFC element.",
    ("ifc_get_bounding_box", "element_id"): "GlobalId or step id of the IFC element.",
    ("ifc_query_elements", "property_value"): "Value the property must have.",
    ("ifc_query_elements", "guid"): "IFC GlobalId to look for.",
    ("ifc_query_elements", "name_filter"): "Substring that the element name must contain.",
    ("ifc_query_elements", "ifc_class"): "IFC class to filter by, for example IfcWall.",
    ("exporter_to_sqlite", "db_path"): "SQLite database file path; must be inside the allowed workspace directories.",
    ("exporter_graph_to_sqlite", "db_path"): "SQLite database file path; must be inside the allowed workspace directories.",
}

# --------------------------------------------------------------------------- #
# Behaviour annotations
# --------------------------------------------------------------------------- #
# Tools that the gate does NOT treat as mutating (is_mutating=False) but that are
# not read-only either (they write files, plan state, UI state or in-memory
# state). value = (destructiveHint, idempotentHint).
NOT_READ_ONLY: dict[str, tuple[bool, bool]] = {
    "plan_actions": (False, False),
    # Re-binds the server to a live Revit session (discovery and health check only); no model request.
    "revit_reconnect": (False, True),
    "approve_plan": (False, True),
    "reject_plan": (False, True),
    "rollback_plan": (True, False),
    "plan_revert": (False, False),
    "execute_plan": (True, False),
    "revit_extract_snapshot": (False, False),
    "snapshot_take": (False, False),
    # Exports write to output_path; nothing refuses an existing file there, so they may replace it.
    "revit_export_dwg": (True, True),
    "revit_export_ifc": (True, True),
    "revit_export_navisworks": (True, True),
    "revit_export_image": (True, True),
    "revit_render_3d": (True, True),
    "revit_set_selection": (False, True),
    "revit_select_by_unique_ids": (False, True),
    "revit_preview_elements": (False, True),
    "revit_clear_preview": (False, True),
    "navisworks_append_file": (False, False),
    "navisworks_refresh": (False, True),
    "navisworks_activate_viewpoint": (False, True),
    # The SQLite exporters empty the tables of an existing database before writing.
    "exporter_to_sqlite": (True, True),
    "exporter_graph_to_sqlite": (True, True),
    # Named output files and saved entries replace an existing file or entry of the same name.
    "parameter_manager_export_params_csv": (True, True),
    "parameter_manager_export_params_xlsx": (True, True),
    "report_generator_export_excel": (True, True),
    "report_generator_build_review_pack": (True, True),
    "report_generator_export_sqlite_summary": (True, True),
    "model_inspector_save_query": (True, True),
    "selection_tools_save_selection": (True, True),
    "bcf_exchange_export_bcf": (True, True),
    "qaqc_checker_run_check": (False, False),
    "clash_triage_match_clashes": (False, True),
    "clash_triage_import_clash_report": (False, True),
    "qaqc_checker_resolve_issue": (False, True),
    "qaqc_checker_import_rule_pack": (True, False),  # overwrite=true replaces a rule pack
    "qaqc_checker_export_rule_pack": (True, False),  # overwrite=true replaces the destination file
    "qaqc_checker_replay_naming_rules": (False, False),  # appends to the naming rules audit log
    "recipe_runner_run_recipe": (True, False),
    "aec_register_mapping": (True, True),  # replaces the mapping already held for the same id
    "graph_compile": (True, False),  # replace=true drops the existing graph
    "graph_add_relation": (False, True),
    "speckle_oauth_start": (False, False),
    "speckle_oauth_exchange_code": (False, False),
    "speckle_oauth_refresh": (False, True),
    "speckle_checkout_version": (False, True),
    # Same OAuth and checkout handlers as the Speckle tools above (providers/cloud.py).
    "autodesk_data_oauth_start": (False, False),
    "autodesk_data_oauth_exchange_code": (False, False),
    "autodesk_data_oauth_refresh": (False, True),
    "autodesk_data_checkout_version": (False, True),
    "job_cancel": (True, True),
    "revit_job_cancel": (True, True),
    "rhino_generate_diagrid_tower": (False, False),
    # Write files under the workspace only (no model change, so no approval plan); saving over an
    # existing recipe or spec file replaces it.
    "revit_recipe_save": (True, True),
    "revit_sparing_export_spec": (True, True),
}

# Tools that read the model or a snapshot and can also write a report or baseline file in the
# workspace. They are not read-only, but their results are still presented like reads (compact
# and size-capped, see is_read_only_tool). value = (destructiveHint, idempotentHint).
REPORT_FILE_WRITERS: dict[str, tuple[bool, bool]] = {
    # Optional named output files; an existing file of the same name is replaced.
    "param_completeness_heatmap": (True, True),
    "model_health_score": (True, True),
    "ids_validator_validate_ifc": (True, True),
    "sheet_set_qa_check": (True, True),
    "schedule_diff_compare": (True, True),
    "qa_handover_build_report": (True, True),
    "revit_render_check": (True, True),
    # Without baseline_id it saves a new warnings baseline file under a fresh id.
    "revit_warnings_delta": (False, False),
}

# Mutating tools that only add things (or only change UI/plan state): they cannot
# destroy existing model content, so destructiveHint is false. Every other
# mutating tool defaults to destructive=true, which is the safe MCP default.
ADDITIVE_NAME_PARTS = frozenset({"create", "place", "copy", "duplicate", "tag", "pin", "unpin"})
ADDITIVE_NAMES = frozenset(
    {
        "selection_tools_set_selection",
        "selection_tools_restore_selection",
        "selection_tools_select_by_query",
        "navisworks_run_clash_test",
        "speckle_publish_version",
        "speckle_send_object",
    }
)
# Verbs that make a repeated identical call a no-op.
IDEMPOTENT_NAME_PARTS = frozenset({"set", "pin", "unpin", "delete", "save", "apply", "restore", "select"})
# Providers whose tools talk to remote services (open world).
OPEN_WORLD_PROVIDERS = frozenset({"speckle", "aps", "autodesk_data", "cloud"})

_ACRONYMS = {
    "ifc": "IFC", "dwg": "DWG", "nwc": "NWC", "rvt": "RVT", "csv": "CSV", "sqlite": "SQLite",
    "aps": "APS", "3d": "3D", "qaqc": "QA/QC", "id": "ID", "ids": "IDs", "uids": "UIDs", "aec": "AEC",
}


def humanize(name: str) -> str:
    return " ".join(_ACRONYMS.get(p, p.capitalize()) for p in name.split("_"))


def annotations_for(provider_id: str, tool: ProviderTool) -> ToolAnnotations:
    """Derive MCP behaviour hints from the tool's existing gate flags."""
    parts = set(tool.name.split("_"))
    open_world = provider_id in OPEN_WORLD_PROVIDERS or provider_id.startswith("proxy")

    if tool.name in NOT_READ_ONLY:
        read_only, (destructive, idempotent) = False, NOT_READ_ONLY[tool.name]
    elif tool.name in REPORT_FILE_WRITERS and not tool.is_mutating:
        read_only, (destructive, idempotent) = False, REPORT_FILE_WRITERS[tool.name]
    elif tool.is_mutating:
        read_only = False
        if tool.destructive:
            destructive = True
        else:
            destructive = not (
                tool.name in ADDITIVE_NAMES or bool(parts & ADDITIVE_NAME_PARTS)
            )
        idempotent = bool(parts & IDEMPOTENT_NAME_PARTS) and not (parts & {"create"})
    else:
        read_only, destructive, idempotent = True, False, True

    if tool.destructive:
        destructive = True
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


def add_cursor_option(name: str, tool: Any, schema: dict) -> None:
    """A read-only tool whose input schema forbids extra keys still has to accept the cursor its cut
    answers hand out; the SDK validates input before response_options is split off (#274 review).
    Only the cursor is listed, to keep the schema small."""
    properties = schema.get("properties")
    if schema.get("additionalProperties") is not False or not isinstance(properties, dict):
        return
    if "response_options" in properties or not is_read_only_tool(name, tool):
        return
    properties["response_options"] = {
        "type": "object", "additionalProperties": False,
        "properties": {"cursor": {"type": "string", "maxLength": 64}},
        "description": "cursor: from a truncated answer, for the next part. Repeat the same arguments.",
    }


def is_read_only_tool(name: str, tool: Any) -> bool:
    """True when the tool's result is presented as a read (compact, size-capped): it does not change
    the model and is not an approval or job tool. Same rule as readOnlyHint, except that the report
    tools in REPORT_FILE_WRITERS, which may also write a file, still count as reads here.
    Fails closed: an unknown tool is not read-only."""
    if tool is None or name in NOT_READ_ONLY or name in APPROVAL_TOOLS:
        return False
    parts = name.split("_")
    if {"plan", "plans"} & set(parts) or name.endswith("recipe_get"):
        return False  # plan-shaped material (actions, plan_arguments) is never compacted or trimmed
    return not getattr(tool, "is_mutating", True)


def enrich_tool(provider_id: str, tool: ProviderTool) -> Tool:
    """Return the MCP `Tool` for a provider tool, with fuller metadata.

    Approval guidance is shared in SERVER_INSTRUCTIONS. Keep each write's
    plan_id schema and behaviour annotations without repeating that guidance.
    """
    description = DESCRIPTIONS.get(tool.name, tool.description)
    hint = SIBLING_HINTS.get(tool.name)
    if hint and hint not in description:
        description = f"{description} {hint}"
    description = localized_description(tool.name, description)

    schema = copy.deepcopy(tool.input_schema) if tool.input_schema else {"type": "object"}
    schema.setdefault("type", "object")
    props: dict[str, Any] = schema.setdefault("properties", {})
    if tool.is_mutating and "plan_id" not in props:
        props["plan_id"] = {"type": "string", "description": PLAN_ID_DESCRIPTION}
    for key, prop in props.items():
        if not isinstance(prop, dict):
            continue
        if prop.get("description"):
            short = canonical_param_text(tool.name, key, prop, is_mutating=tool.is_mutating)
            if short:
                prop["description"] = short
                if key == "status_labels":
                    for sub in prop.get("properties", {}).values():
                        if isinstance(sub, dict):
                            sub.pop("description", None)
            elif key == "ids" and isinstance(prop.get("items"), dict):
                # The list text already says what the ids are; drop the repeated item text.
                prop["items"].pop("description", None)
            continue
        text = (
            TOOL_PARAM_DESCRIPTIONS.get((tool.name, key))
            or PARAM_DESCRIPTIONS.get(key)
        )
        if text:
            prop["description"] = text
    add_response_schema(tool.name, schema)
    add_cursor_option(tool.name, tool, schema)
    output_schema = output_schema_for(tool.name)
    extra: dict[str, Any] = {}
    if tool.name in ALWAYS_LOADED_TOOLS:
        # Claude Code loads a tool marked this way up front when tool search defers the rest.
        # Passed by alias: the SDK keeps a `meta=` keyword as an unrelated extra field.
        extra["_meta"] = {ALWAYS_LOAD_META_KEY: True}
    if tool.name in TASK_TOOLS:
        # MCP Tasks (docs/mcp-tasks.md): the tool accepts a task-augmented tools/call.
        extra["execution"] = ToolExecution(taskSupport="optional")
    return Tool(
        name=tool.name,
        title=humanize(tool.name),
        description=description,
        inputSchema=schema,
        outputSchema=copy.deepcopy(output_schema) if output_schema else None,
        annotations=annotations_for(provider_id, tool),
        **extra,
    )
