"""MCP prompts: short, reusable starting points for the common BIM-coordinator tasks.

Prompts only produce text for the model. They never run a tool and never approve a
plan. Tool names are written in backticks so a test can check each one against the
live tool registry. Approval always stays with the person (Revit panel or
`aec-model-bridge-approve`).
"""
from __future__ import annotations

from typing import Any, Mapping

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

APPROVAL_RULE = (
    "Approval: `plan_actions` only drafts a plan. You cannot approve it. Tell the person to review and approve it "
    "in the Revit panel (Plans view) or with `aec-model-bridge-approve`, then wait for them to say so. "
    "If `revit_get_context` shows server.dev_mode true, follow the Dev mode rule in the server instructions."
)


def _arg(name: str, description: str, required: bool = False) -> PromptArgument:
    return PromptArgument(name=name, description=description, required=required)


_SPECS: dict[str, dict[str, Any]] = {
    "qa_review": {
        "description": "Review model quality: warnings, QA/QC rule checks and a short report. Read-only.",
        "arguments": [
            _arg("rule_pack", "QA/QC rule pack to run (default core)."),
            _arg("category", "Optional Revit category to focus the review on."),
        ],
    },
    "parameter_fix": {
        "description": "Find elements with a wrong parameter, propose a fix, wait for the person's approval, then verify.",
        "arguments": [
            _arg("category", "Revit category of the elements, for example Doors.", True),
            _arg("parameter", "Parameter name to fix, for example Fire Rating.", True),
            _arg("value", "New value to set.", True),
            _arg("level", "Optional level name to limit the change to."),
        ],
    },
    "sheet_prep": {
        "description": "Check sheets and views before issue: missing numbers, names and parameters. Read-only.",
        "arguments": [_arg("level", "Optional level or discipline to focus on.")],
    },
    "handover_report": {
        "description": "Build the QA hand-over report from a snapshot, with before/after counts and the not-verified list.",
        "arguments": [
            _arg("rule_pack", "QA/QC rule pack (default core)."),
            _arg("plan_ids", "Optional comma-separated plan ids whose approved changes to include."),
        ],
    },
    "first_run": {
        "description": "A short tour of the server that is safe in mock mode and changes nothing.",
        "arguments": [],
    },
}


def prompt_names() -> list[str]:
    return list(_SPECS)


def list_prompts() -> list[Prompt]:
    return [
        Prompt(name=name, title=name.replace("_", " ").capitalize(),
               description=spec["description"], arguments=spec["arguments"])
        for name, spec in _SPECS.items()
    ]


def _clean(value: Any, default: str = "") -> str:
    """Single-line argument text so an argument cannot add new instructions on extra lines."""
    text = " ".join(str(value).split()) if value is not None else ""
    return (text or default)[:120]


def _qa_review(a: Mapping[str, str]) -> str:
    pack = _clean(a.get("rule_pack"), "core")
    focus = _clean(a.get("category"))
    focus_line = f" Focus on the {focus} category where a tool allows it." if focus else ""
    return (
        "Review the quality of the open model. Read-only: change nothing.\n"
        "1. `revit_get_context` and `revit_health`: confirm which document is open (or that this is mock mode).\n"
        "2. `snapshot_take` to capture the model. Note whether the capture was partial.\n"
        "3. `revit_review` and `warnings_triage_review_warnings` for warnings; `revit_warnings_delta` if an earlier snapshot exists.\n"
        f"4. `qaqc_checker_run_check` with rule_pack \"{pack}\", then `qaqc_checker_list_issues`.{focus_line}\n"
        "5. `qa_handover_build_report` for the written report.\n"
        "Report findings by rule and severity, with counts. Say what was not checked. Do not propose fixes unless asked."
    )


def _parameter_fix(a: Mapping[str, str]) -> str:
    category = _clean(a.get("category"), "<category>")
    parameter = _clean(a.get("parameter"), "<parameter>")
    value = _clean(a.get("value"), "<value>")
    level = _clean(a.get("level"))
    where = f" on level \"{level}\"" if level else ""
    return (
        f"Set parameter \"{parameter}\" to \"{value}\" on {category} elements{where}.\n"
        "1. `revit_get_context`: confirm the document and whether Dev mode is on.\n"
        "2. `snapshot_take`, then `parameter_manager_filter_params` to find the elements and their current values. "
        "Show the person the count and a few examples.\n"
        "3. `parameter_manager_plan_set_params` to prepare the change, then `plan_actions` with the exact "
        "tool arguments. Include a short review summary.\n"
        f"4. {APPROVAL_RULE}\n"
        "5. After the person says it is approved, run `execute_plan`, or the write tool with the approved plan_id and "
        "exactly the approved arguments.\n"
        "6. Verify by reading back: `revit_get_parameters` or `snapshot_take` and `snapshot_diff`. "
        "Report what changed and anything that did not. `get_proof_bundle` shows the record for the plan."
    )


def _sheet_prep(a: Mapping[str, str]) -> str:
    focus = _clean(a.get("level"))
    focus_line = f" Limit the summary to {focus}." if focus else ""
    return (
        "Check sheets and views before issue. Read-only: change nothing.\n"
        "1. `snapshot_take` with sheets and views included.\n"
        "2. `sheet_view_audit_run_audit` on that snapshot. If its status is partial, say which checks did not run.\n"
        "3. `revit_list_views_sheets_schedules` to list what exists, and `naming_checker_check_names` for naming.\n"
        f"Summarise missing sheet numbers or names, unplaced views, default view names and empty required parameters.{focus_line} "
        "Fixes need a plan; offer one with `plan_actions` only if the person asks. You cannot approve it: "
        "the person approves it in the Revit panel."
    )


def _handover_report(a: Mapping[str, str]) -> str:
    pack = _clean(a.get("rule_pack"), "core")
    plans = _clean(a.get("plan_ids"))
    plans_line = f" Pass plan_ids: {plans}." if plans else ""
    return (
        "Build the QA hand-over report.\n"
        "1. `snapshot_take` for the before state, or ask which saved snapshot to use. "
        "If fixes were made since, take a second snapshot as the after state.\n"
        f"2. `qa_handover_build_report` with rule_pack \"{pack}\" and the snapshot ids.{plans_line}\n"
        "3. Summarise: findings per rule, before/after counts, approved parameter changes from proof bundles, "
        "and the not-verified list. State plainly what was not verified, including anything not checked in a live Revit session."
    )


def _first_run(_a: Mapping[str, str]) -> str:
    return (
        "Give the person a short tour. Nothing here changes a model.\n"
        "1. `revit_get_context`: report the mode (mock or live), the profile and whether Dev mode is on.\n"
        "2. `revit_health`, then `revit_list_levels` and `revit_list_views` for a first look.\n"
        "3. `snapshot_take`, then `model_inspector_summarize_model` for a model summary.\n"
        "4. `qaqc_checker_run_check` and `qaqc_checker_list_issues` as an example check.\n"
        "5. Explain in two sentences how a change would work: `plan_actions` drafts it, the person approves it in the "
        "Revit panel, then `execute_plan` runs it. You cannot approve it. Do not draft a plan for this tour.\n"
        "In mock mode the answers are canned sample data; say so."
    )


_BUILDERS = {
    "qa_review": _qa_review,
    "parameter_fix": _parameter_fix,
    "sheet_prep": _sheet_prep,
    "handover_report": _handover_report,
    "first_run": _first_run,
}


def get_prompt(name: str, arguments: Mapping[str, str] | None) -> GetPromptResult:
    spec = _SPECS.get(name)
    if spec is None:
        raise ValueError(f"Unknown prompt: {name}")
    args = dict(arguments or {})
    known = {a.name for a in spec["arguments"]}
    unknown = sorted(set(args) - known)
    if unknown:
        raise ValueError(f"Unknown argument for prompt '{name}': {', '.join(unknown)}")
    missing = [a.name for a in spec["arguments"] if a.required and not _clean(args.get(a.name))]
    if missing:
        raise ValueError(f"Prompt '{name}' needs: {', '.join(missing)}")
    text = _BUILDERS[name](args)
    return GetPromptResult(
        description=spec["description"],
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )
