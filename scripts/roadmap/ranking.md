| # | Feature | Category | Score | P(top 10) | Rank p10-p90 | Effort | Mock-testable |
| ---: | --- | --- | ---: | ---: | --- | ---: | :---: |
| 1 | **MCP Prompts** - Ship slash-style workflows: QA review, parameter fix, sheet prep, handover | mcp | 415.0 | 94% | 1-9 | 1 | yes |
| 2 | **Annotation audit test** - CI test that every write tool is destructiveHint and every read tool readOnlyHint | mcp | 335.0 | 84% | 2-13 | 1 | yes |
| 3 | **Door/fire-rating consistency** - Rule pack: door fire rating vs wall rating, schedule consistency | qa | 320.0 | 82% | 1-14 | 1 | yes |
| 4 | **Token/latency benchmark in CI** - Publish token cost per workflow per release | ops | 315.0 | 79% | 2-15 | 1 | yes |
| 5 | **Excel mapping profiles** - Saved per-project column mappings for round-trip | data | 272.0 | 73% | 2-19 | 1 | yes |
| 6 | **Model health trend** - Health score per snapshot and trend over time | qa | 180.0 | 50% | 3-24 | 2 | yes |
| 7 | **Parameter completeness heatmap** - Fill-rate by category x parameter x level, CSV/Power BI/HTML | qa | 180.0 | 49% | 3-24 | 2 | yes |
| 8 | **HTML diff preview** - Render the plan diff as a before/after table (HTML + markdown) for the panel and chat | safety | 180.0 | 49% | 3-24 | 2 | yes |
| 9 | **Logging notifications** - Send server logs to the client at the requested level | mcp | 192.0 | 44% | 5-32 | 1 | yes |
| 10 | **COBie / classification checks** - Uniclass/OmniClass/COBie completeness checks as rule packs | qa | 170.0 | 43% | 3-26 | 2 | yes |
| 11 | **IFC diff** - GlobalId-based diff between two IFC files | integration | 170.0 | 42% | 3-26 | 2 | yes |
| 12 | **doctor command** - aec-model-bridge doctor: checks Python, add-in, ports, token, workspace, client config | ops | 174.0 | 41% | 4-24 | 2 | yes |
| 13 | **execute_python API-trap linter** - Lint IronPython scripts for known Revit API traps before running | ai | 160.0 | 37% | 4-28 | 2 | yes |
| 14 | **Hot profile switching** - Switch tool profile at runtime with tools/list_changed, no restart | mcp | 140.0 | 25% | 5-33 | 2 | yes |
| 15 | **Response redaction** - Redact user names, local paths and emails from tool responses (opt-in levels) | safety | 140.0 | 24% | 5-33 | 2 | yes |
| 16 | **Open-the-panel link** - URL-mode elicitation that opens the review panel at the pending plan | mcp | 150.0 | 23% | 6-37 | 1 | yes |
| 17 | **CSV/Sheets as plan source** - Import a CSV of element-id,parameter,value as a plan | data | 136.0 | 22% | 6-33 | 2 | yes |
| 18 | **MCP conformance in CI** - Run the MCP Inspector/conformance checks against mock mode in CI | ops | 120.0 | 18% | 6-39 | 2 | yes |
| 19 | **Power BI template** - Ship a .pbit dashboard for exported QA data | data | 120.0 | 17% | 7-38 | 2 | yes |
| 20 | **IDS validation** - Validate IFC files and snapshots against buildingSMART IDS requirements | qa | 126.7 | 13% | 9-34 | 3 | yes |
| 21 | **Policy file** - YAML policy: allowed categories/parameters, max elements per plan, blocked tools; enforced at plan time | safety | 126.7 | 12% | 10-33 | 3 | yes |
| 22 | **MCP Resources** - Expose model summary, snapshots, QA reports, plans and proofs as read-only resources | mcp | 113.3 | 8% | 11-37 | 3 | yes |
| 23 | **Clash report ingestion** - Import Navisworks XML / BCF clash reports into clash_triage groups and fix plans | qa | 113.3 | 8% | 11-37 | 3 | yes |
| 24 | **Hash-chained audit log** - Tamper-evident JSONL audit with verify command and export | safety | 110.7 | 7% | 12-38 | 3 | yes |
| 25 | **Excel round-trip to plan** - Export elements to xlsx, user edits, import as a reviewed plan with row diff | data | 114.3 | 7% | 12-37 | 3 | yes |
| 26 | **Tool search meta-tool** - search_tools returns matching tool schemas on demand; cuts the 80k full catalogue | mcp | 106.7 | 6% | 13-39 | 3 | yes |
| 27 | **BIM agent eval set** - 20 BIM tasks with expected tool calls run against mock mode | ops | 106.7 | 6% | 13-39 | 3 | yes |
| 28 | **Client roots as workspace** - Scope the workspace sandbox to the client's declared roots | mcp | 79.5 | 6% | 15-53 | 2 | yes |
| 29 | **Blast-radius estimate** - Each plan shows element count, categories, levels and worksets touched before approval | safety | 114.3 | 6% | 13-37 | 3 | yes |
| 30 | **QA finding to fix plan** - One call turns selected QA findings with fix templates into a reviewed plan | safety | 110.9 | 5% | 13-38 | 3 | yes |
| 31 | **Localized tool descriptions** - Translate tool descriptions | ops | 72.0 | 4% | 17-55 | 2 | yes |
| 32 | **Model Checker rule library** - Expand rule packs: worksets, levels, shared params, view templates, with severities | qa | 97.1 | 3% | 16-41 | 3 | yes |
| 33 | **Live session replay harness** - Record live bridge traffic to fixtures for mock tests | ops | 99.4 | 3% | 16-41 | 3 | yes |
| 34 | **Opt-in usage stats** - Off by default, local summary only | ops | 67.5 | 2% | 21-56 | 2 | yes |
| 35 | **Coexist with Autodesk MCP** - Namespace-safe names and a doc/test for running beside Autodesk's Revit MCP | ecosystem | 97.5 | 2% | 17-49 | 1 | yes |
| 36 | **outputSchema on read tools** - Declare outputSchema for the core profile so clients validate structuredContent | mcp | 86.7 | 2% | 18-46 | 3 | yes |
| 37 | **LOIN completeness** - ISO 19650 level-of-information completeness report per category | qa | 85.0 | 2% | 19-48 | 3 | yes |
| 38 | **Elicitation for clarification** - Ask the user for missing arguments (category, level, value) via MCP elicitation instead of guessing; never for approval itself | mcp | 85.0 | 1% | 19-48 | 3 | yes |
| 39 | **Quantity take-off export** - QTO from snapshot/IFC to CSV/BC3 | data | 80.0 | 1% | 20-50 | 3 | yes |
| 40 | **Progress + cancellation** - Progress notifications and cancel for long snapshot, QA and export jobs | mcp | 80.0 | 1% | 22-47 | 3 | yes |
| 41 | **IFC vs snapshot compare** - Compare delivered IFC against the Revit snapshot by GUID | data | 75.0 | 0% | 23-51 | 3 | yes |
| 42 | **BCF 3.0 REST** - Push/pull topics with BIMcollab/Revizto BCF API | integration | 72.0 | 0% | 24-52 | 3 | yes |
| 43 | **Two-person approval** - Optional rule: plan author cannot approve; second named approver required | safety | 71.1 | 0% | 26-52 | 3 | yes |
| 44 | **View screenshot as image** - Return view captures as MCP image content | ai | 68.6 | 0% | 28-54 | 2 | no |
| 45 | **Offline Revit API lookup** - Resource/tool indexing the Revit API for script authoring | ai | 65.0 | 0% | 28-55 | 3 | yes |
| 46 | **Streamable HTTP transport** - Opt-in localhost streamable HTTP so web/remote clients can connect | mcp | 60.0 | 0% | 31-56 | 3 | yes |
| 47 | **Argument completions** - Complete category, level, parameter names from the last snapshot | mcp | 58.0 | 0% | 32-58 | 3 | yes |
| 48 | **IFC write via IfcOpenShell** - Approved IfcPatch recipes on IFC files | integration | 57.8 | 0% | 35-56 | 4 | yes |
| 49 | **Read-only reviewer mode** - A role that can see plans and proofs but never approve | safety | 55.7 | 0% | 34-57 | 3 | yes |
| 50 | **PDF schedule to plan** - Extract a schedule/spec table from PDF into a parameter-update plan | ai | 53.3 | 0% | 38-58 | 4 | yes |
| 51 | **Sheet set from standards** - Generate sheet/view sets from a standards file as a plan | ai | 53.3 | 0% | 39-58 | 3 | no |
| 52 | **Element filter DSL** - Natural-language-friendly filter spec compiled to collector queries | ai | 52.5 | 0% | 38-59 | 3 | yes |
| 53 | **Revit API change canary** - Static checks for 2027 API changes | ops | 51.4 | 0% | 37-59 | 3 | yes |
| 54 | **IFC pre-export checks** - Check export settings and mapping before IFC export | qa | 51.0 | 0% | 39-59 | 3 | yes |
| 55 | **Speckle baseline diff** - Use a Speckle version as the 'before' for model diff | data | 47.1 | 0% | 40-60 | 3 | yes |
| 56 | **winget + signed auto-update** - Installer channel with signature check | ops | 42.0 | 0% | 46-62 | 3 | no |
| 57 | **MEP system tracing** - Connector-aware system trace read tools | ai | 40.9 | 0% | 47-62 | 4 | no |
| 58 | **MCP Tasks** - Map existing job tools onto spec Tasks (durable async with polling) | mcp | 36.7 | 0% | 45-67 | 3 | yes |
| 59 | **Grasshopper parity** - Describe graph, sliders, bake parity with Cordyceps | integration | 36.7 | 0% | 50-65 | 3 | no |
| 60 | **OAuth 2.1 for HTTP** - Protected-resource metadata and token validation for HTTP mode | mcp | 31.2 | 0% | 53-66 | 5 | yes |
| 61 | **Linked-model read-through** - Read elements through links | ops | 26.7 | 0% | 56-70 | 4 | no |
| 62 | **Autodesk certification path** - Prepare for Autodesk certified MCP listing | ops | 26.7 | 0% | 56-70 | 3 | no |
| 63 | **Worksharing metadata** - Sync status and last-changed-by in snapshots | data | 26.0 | 0% | 56-70 | 3 | no |
| 64 | **ACC/APS read** - Read ACC issues/RFIs/models via APS | data | 24.4 | 0% | 56-70 | 5 | yes |
| 65 | **Import external rule sets** - Convert Solibri/BIMcollab rule definitions into rule packs | qa | 24.0 | 0% | 56-70 | 5 | yes |
| 66 | **Sandboxed Python profile** - Restrict execute_python (no file/network) under a profile | safety | 23.7 | 0% | 58-70 | 5 | no |
| 67 | **Dynamo player runner** - Run Dynamo graphs with inputs under approval | integration | 21.4 | 0% | 59-70 | 5 | no |
| 68 | **Annotation placement plans** - Tag/dimension placement plans | ai | 20.0 | 0% | 61-71 | 5 | no |
| 69 | **Design Automation jobs** - Headless batch via APS Design Automation | data | 17.7 | 0% | 62-71 | 5 | no |
| 70 | **Rhino.Inside.Revit bridge** - List/run GH definitions inside Revit | integration | 17.7 | 0% | 63-71 | 5 | no |
| 71 | **Auto clash after execute** - Re-run clash on changed elements after a plan | qa | 15.7 | 0% | 64-71 | 5 | no |
