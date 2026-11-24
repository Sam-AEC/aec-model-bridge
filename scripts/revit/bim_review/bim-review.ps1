<#
.SYNOPSIS  DEPRECATED. The BIM review now runs through the MCP server's read-only tools.
.DESCRIPTION
This script used to read the add-in's registry file and POST revit.execute_python straight to the add-in's
/execute endpoint with the session token. That skipped the MCP server's approval/read-mode gate and its audit
log, so it has been retired. It no longer contacts Revit.

Use instead:
  - the bim-reviewer agent (.claude/agents/bim-reviewer.md), which calls revit_review, revit_list_views and
    revit_render_check through the server, discovers views from the model and reads the PNGs; or
  - the MCP tools directly: revit_review (FAIL/PASS/INCOMPLETE with evidence), revit_list_views, then
    revit_render_check per view.

The villa-specific checks it ran are kept as integration-test evidence in docs/recipes/villa/review_checks.py
(run after docs/recipes/villa/prelude.py). That prelude contains a Transaction, so the pair is not accepted by
revit_execute_python mode='read'.
Exit code 2 always.
#>
param([string]$OutDir, [switch]$NoImages)
Write-Warning ('scripts/revit/bim_review/bim-review.ps1 is deprecated and no longer contacts Revit. ' +
    'Use the bim-reviewer agent, or the MCP tools revit_review, revit_list_views and revit_render_check.')
exit 2
