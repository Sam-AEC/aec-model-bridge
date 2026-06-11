# Multi-Platform Integration Handover

Research date: 2026-06-11

This document hands AEC Model Bridge to the next implementation agent. It
summarizes the current repository, the most useful AEC integration targets,
their official API surfaces, and the decisions that must be made before adding
connectors.

## Short Handover Prompt

```text
Act as the lead architect and implementation owner for AEC Model Bridge.

Read docs/integration-expansion-handover.md, inspect the repository, and verify
any API detail that may have changed against the linked official documentation.
Evolve the current Revit-only MCP system into a multi-provider AEC automation
platform without breaking existing Revit tool names, configuration, packaging,
or tests.

First write a concise architecture decision record covering provider discovery,
transport types, capability manifests, object references, authentication,
mutation controls, asynchronous jobs, licensing boundaries, and compatibility.
Then implement the smallest complete vertical slice: a provider contract and
registry, a compatibility adapter for the existing Revit bridge, and a
production-quality read-only IFC connector using IfcOpenShell. Expose a small,
coherent IFC tool set for health, file metadata, spatial structure, element
query, properties, quantities, and validation. Do not create empty connector
packages or attempt a universal BIM object model.

Keep host-specific SDK code out of the platform core. Treat desktop products as
separate local adapters, cloud products as OAuth providers, and batch engines as
asynchronous job providers. Add reusable provider contract tests, IFC fixtures,
mock coverage, migration documentation, and security tests. Preserve the
working Revit path throughout. Run the relevant Python tests and all supported
Revit add-in builds before finishing, and report exact results and remaining
vendor-account or licensed-application test gaps.
```

## Current Baseline

AEC Model Bridge currently has two runtime tiers:

1. A Python MCP server in `packages/mcp-server-revit`.
2. A C# add-in in `packages/revit-bridge-addin` that runs inside Revit.

The local bridge contract is already useful beyond Revit:

```text
GET  /health
GET  /tools
POST /execute
```

The Python client discovers the bridge tool catalog and sends a tool name,
payload, and request ID. The Revit add-in queues work onto the Revit UI thread.
The repository currently contains about 100 MCP tools and 110 unique Revit
bridge routes.

Important constraints in the present implementation:

- Configuration is Revit-specific through the `MCP_REVIT_` prefix.
- One bridge URL represents one active provider.
- Tool registration and argument translation are largely hard-coded.
- Revit bridge routing is concentrated in `BridgeCommandFactory.cs`.
- Mock mode, workspace restrictions, and JSONL audit logging already exist.
- The bridge binds to loopback, but it does not authenticate local requests.
- Existing Revit tool names and behavior are a public compatibility surface.

The next architecture should extract reusable provider behavior incrementally.
It should not rewrite the working Revit implementation before another provider
proves the abstraction.

## Integration Priority

The recommended order balances user value, API maturity, development friction,
and the ability to test without paid desktop software.

| Order | Integration | Why it belongs here | First useful release |
| --- | --- | --- | --- |
| 1 | IFC and IfcOpenShell | Open, headless, cross-platform, and useful as the interoperability baseline | Read IFC metadata, hierarchy, elements, properties, quantities, geometry summaries, IDS validation, and BCF references |
| 2 | Rhino and Grasshopper | Mature developer APIs and high value for computational design | Inspect the active model, query objects and user text, exchange geometry, run named Grasshopper definitions, and return artifacts |
| 3 | Autodesk Forma Data Management / ACC | Adds projects, documents, published model data, and construction issues | OAuth connection, account/project/file discovery, AEC Data Model queries, issue workflows, and webhooks |
| 4 | Tekla Structures | High-value structural detailing and fabrication workflows | Query model objects, assemblies, profiles, drawings, and selected safe modifications through a local .NET adapter |
| 5 | Navisworks | Strong coordination, aggregation, viewpoints, and clash workflows | Query selection/model tree, manage viewpoints, inspect clash tests, and export coordination data |
| 6 | Archicad | Important authoring platform with an official local JSON automation interface | Project info, elements, properties, classifications, layouts, and selected documentation workflows |
| 7 | Speckle | Useful vendor-neutral data and event layer with Python, .NET, GraphQL, and webhooks | Project/model/version discovery, object transfer, and update-triggered automation |
| 8 | Bentley iTwin | Strategic for infrastructure digital twins, changesets, synchronization, and reality data | iTwin/iModel discovery, changeset queries, synchronization status, and reporting |
| 9 | Trimble Connect | Useful common data environment with file, model, property, and BCF services | Project/file/model access, property sets, BCF topics, and events |
| 10 | Procore | Important construction management platform | Project discovery, document and issue workflows, RFIs, and webhooks |
| 11 | Primavera Cloud / P6 | Important schedule and portfolio data, but not the first modeling connector | Projects, WBS, activities, relationships, progress, and schedule analytics |
| 12 | SketchUp | Broad early-design adoption and a mature in-process Ruby API | Model/entity query, attributes, selection, and controlled geometry operations |
| 13 | Microsoft 365 / Excel | Common operational data source rather than a BIM host | Read and update controlled workbook tables in SharePoint or OneDrive for Business |

This sequence is not a promise to support every product. Each connector should
earn its place through a concrete workflow, test access, and maintainable API
coverage.

## Platform Findings

### OpenBIM Foundation

IfcOpenShell should be the first new provider. Its official documentation
exposes Python and C++ APIs for IFC parsing, authoring, geometry, schema
queries, validation, conversion, BCF, IDS-related testing, cost, scheduling,
clash detection, and other utilities. It can be developed and tested without a
licensed desktop host.

Use IFC as an exchange and validation foundation, not as a forced replacement
for every host application's native data model. Add BCF for issue exchange and
IDS for machine-readable information requirements. Consider bSDD later for
classification and dictionary references.

Official sources:

- [IfcOpenShell documentation](https://docs.ifcopenshell.org/)
- [buildingSMART BCF](https://technical.buildingsmart.org/standards/bcf/)
- [buildingSMART standards and API portfolio](https://www.buildingsmart.org/standards/)

### Rhino and Grasshopper

RhinoCommon is the primary .NET SDK for Rhino plug-ins and Grasshopper
components. Rhino's developer site also documents Python scripting, openNURBS
for `.3dm` file access, Grasshopper APIs, Rhino.Compute, and Hops.

Use a local Rhino plug-in for live document and UI-dependent operations.
Rhino.Compute is a separate HTTP geometry service suited to scalable or
headless geometry calculations. It should be modeled as a job or compute
provider, not as a substitute for all live Rhino document operations.

Official sources:

- [Rhino and Grasshopper developer documentation](https://developer.rhino3d.com/)
- [Rhino API references](https://developer.rhino3d.com/api)
- [Rhino.Compute overview](https://developer.rhino3d.com/guides/compute/compute-faq/)
- [Grasshopper Hops](https://developer.rhino3d.com/guides/compute/hops-component/)

### Tekla Structures

Tekla Structures Open API is a .NET API for plug-ins, macros, and external
applications. The official examples cover model objects, properties, geometry,
cuts, fittings, drawings, and creating structural elements.

Development requires Tekla Structures access and version-specific assembly
references. Keep Tekla SDK dependencies inside a local Windows adapter. The
platform core should communicate with that adapter through a stable,
vendor-neutral transport contract.

Official sources:

- [Tekla Structures Open API getting started](https://developer.tekla.com/documentation/get-started-tekla-structures-open-api)
- [Tekla Developer Center](https://developer.tekla.com/)

### Autodesk Forma and Construction Cloud

Autodesk now presents Forma as an industry cloud with multiple API families.
Do not treat "Forma" as one connector:

- Forma Data Management / Construction Cloud APIs cover files, projects,
  issues, reviews, cost, assets, and other construction data.
- AEC Data Model is a GraphQL API for granular cloud-hosted design data and
  currently depends on appropriate Forma Data Management access.
- Forma Site Design API is a separate conceptual-design API and is documented
  as beta.
- Data Exchange supports selective data exchange between supported products.
- Automation API runs headless Autodesk product engines for batch work.

Start with read-only project, file, issue, and AEC Data Model access. Add writes
only after OAuth scopes, account provisioning, regional behavior, rate limits,
and webhook handling are covered by tests. Treat Automation API calls as
asynchronous jobs with cost and retry metadata.

Official sources:

- [Autodesk Forma APIs](https://aps.autodesk.com/autodesk-forma)
- [Forma / Construction Cloud API overview](https://aps.autodesk.com/en/docs/acc/v1/overview/)
- [AEC Data Model API](https://aps.autodesk.com/en/docs/aecdatamodel/v1/developers_guide/onboarding)
- [Forma Site Design API beta](https://aps.autodesk.com/en/docs/forma/v1)
- [Automation API](https://aps.autodesk.com/en/docs/design-automation/v3)
- [Revit Automation tutorial](https://aps.autodesk.com/en/docs/design-automation/v3/tutorials/revit/)
- [Data Exchange API](https://aps.autodesk.com/apis-and-services/data-exchange-api)

### Navisworks

Navisworks Manage and Simulate include a .NET API and SDK documentation for
plug-ins and applications. A local adapter is appropriate for the active model,
selection, viewpoints, model hierarchy, saved searches, and clash workflows.

Keep Navisworks distinct from APS Model Derivative. Model Derivative is useful
for cloud translation and extraction, while a Navisworks plug-in can interact
with the live desktop coordination session.

Official source:

- [Navisworks API overview](https://aps.autodesk.com/developer/overview/navisworks-api)

### Archicad

Archicad exposes an Automation API through a local JSON interface. Graphisoft's
official Python package communicates with a running Archicad instance over
HTTP. It is a relatively low-friction path for properties, classifications,
layouts, navigator items, and other documented automation commands.

Use the JSON/Python route first. Consider the C++ Add-On API only when a
required workflow cannot be implemented through the automation interface.

Official sources:

- [Archicad JSON interface](https://archicadapi.graphisoft.com/JSONInterfaceDocumentation/)
- [Archicad Python connection](https://archicadapi.graphisoft.com/getting-started-with-archicad-python-connection)
- [Archicad automation technologies](https://archicadapi.graphisoft.com/archicad-extension-and-automation-technologies)

### Cloud and Data Platforms

These platforms should use authenticated cloud providers rather than local
desktop bridges:

- Bentley iTwin provides APIs for iTwins, iModels, changesets,
  synchronization, reality data, validation, and reporting.
- Trimble Connect provides cloud APIs for projects, files, models, model
  queries, property sets, and BCF-compatible topics.
- Procore provides OAuth 2.0 REST APIs and webhooks for construction workflows.
- Speckle provides GraphQL, Python and .NET SDKs, object transport, viewer
  tooling, webhooks, and automation.
- Primavera Cloud and P6 expose REST APIs for project and schedule data.
- Microsoft Graph can read and modify supported Excel workbooks stored in
  OneDrive for Business and SharePoint.

Official sources:

- [Bentley iTwin Platform](https://developer.bentley.com/)
- [iModels API](https://developer.bentley.com/apis/imodels-v2/overview/)
- [iTwin Synchronization API](https://developer.bentley.com/apis/synchronization/overview/)
- [Trimble Connect Core API](https://developer.trimble.com/docs/connect/reference/openapi/core/)
- [Trimble Connect Model API](https://developer.trimble.com/docs/connect/reference/openapi/model/)
- [Procore developer documentation](https://developers.procore.com/documentation/introduction)
- [Procore webhooks](https://developers.procore.com/documentation/webhooks)
- [Speckle developer documentation](https://docs.speckle.systems/developers/introduction)
- [Oracle Primavera Cloud REST API](https://docs.oracle.com/en/industries/construction-engineering/primavera-cloud/rest-api/index.html)
- [Primavera P6 EPPM REST API](https://docs.oracle.com/cd/F37125_01/English/Integration_Documentation/rest_api/index.html)
- [Microsoft Graph Excel API](https://learn.microsoft.com/en-us/graph/api/resources/excel?view=graph-rest-1.0)

### SketchUp

SketchUp's Ruby API provides live access to the desktop model and UI. Its
desktop SDK supports file-level `.skp` access under separate access terms. A
small in-process Ruby extension can expose the same local bridge contract used
by other desktop hosts.

Official source:

- [SketchUp Developer Center](https://developer.sketchup.com/)

## Required Architecture Decisions

The next agent should document these decisions before implementing the shared
core.

### 1. Provider Contract

Every provider needs a small common lifecycle:

```text
identity
health
capabilities
execute
shutdown or disconnect
```

The capability manifest should be generated from provider code and include:

- Stable tool name and version.
- Input and output JSON schemas.
- Read-only or mutating classification.
- Required confirmation policy.
- Authentication and entitlement requirements.
- Synchronous or asynchronous execution.
- Supported host and connector versions.
- Expected artifacts and side effects.

Do not maintain separate handwritten catalogs in the MCP layer and connector
layer when one generated manifest can be authoritative.

### 2. Runtime Types

Support four runtime types explicitly:

| Runtime | Examples | Execution characteristics |
| --- | --- | --- |
| Desktop host adapter | Revit, Rhino, Tekla, Navisworks, SketchUp | Separate process boundary, host UI-thread rules, local discovery, version-specific deployment |
| Headless file provider | IfcOpenShell, openNURBS file access | In-process or isolated worker, deterministic fixtures, no desktop UI |
| Cloud provider | Forma/ACC, iTwin, Trimble Connect, Procore, Speckle, Primavera, Microsoft Graph | OAuth, scopes, pagination, rate limits, webhooks, regional endpoints |
| Batch/compute provider | Autodesk Automation, Rhino.Compute | Long-running jobs, polling, cancellation, cost metadata, downloadable artifacts |

One `BridgeClient` implementation may not be sufficient for every runtime, but
the providers should return a consistent result envelope.

### 3. Compatibility

Existing `revit_*` MCP names and `revit.*` bridge routes must continue to work.
Introduce the provider registry behind the current public surface, then migrate
internals in small steps.

New tools should use a stable provider namespace. Avoid duplicating a broad
generic tool set for every product. Prefer provider-native tools, with a small
set of normalized cross-platform operations only where semantics are genuinely
equivalent.

### 4. Object References

Do not design a universal BIM object class before real connectors exist.
Instead, use a reference envelope that can preserve native identity:

```json
{
  "provider": "ifc",
  "project_id": null,
  "model_id": "example.ifc",
  "object_id": "12345",
  "stable_id": null,
  "ifc_guid": "2XQ$n5SLP5MBLyL6JQj8Z0",
  "version": null
}
```

Provider-native data remains authoritative. Cross-platform workflows can map
references through IFC GUIDs, external IDs, URNs, Data Exchange identifiers,
or an explicit mapping store.

### 5. Discovery and Local Security

Multiple desktop hosts cannot all assume port `3000`. Define dynamic port
allocation and a local provider registry or discovery mechanism.

Each local adapter should:

- Bind only to loopback.
- Publish its provider, host version, connector version, process ID, endpoint,
  and capability digest.
- Use a random per-session bearer token or equivalent nonce.
- Reject stale registrations and requests from unsupported protocol versions.
- Apply request size and concurrency limits.

Do not generalize reflection, arbitrary method invocation, or arbitrary script
execution as cross-provider capabilities. Those operations require a separate,
explicitly enabled high-risk policy.

### 6. Cloud Authentication

Tokens must never appear in MCP tool arguments, model-visible results, audit
logs, or repository configuration.

Use an OS credential store or another established secret backend. Cloud
providers need:

- OAuth authorization code with PKCE for user-delegated access where supported.
- Service-to-service credentials only where the vendor supports the workflow.
- Scoped account and project selection.
- Refresh, revocation, and expiry handling.
- Pagination, retries with jitter, rate-limit handling, and regional endpoints.
- Redacted structured logging.

### 7. Mutations and Jobs

Mutating tools need:

- Preview or dry-run where practical.
- Explicit confirmation metadata.
- Transaction or undo integration where the host supports it.
- Idempotency keys for cloud writes and retried requests.
- Before/after references and audit records.

Long-running operations should return a job reference with status, progress,
warnings, artifacts, cancellation support, and terminal error details.

### 8. Licensing Boundary

The current GPL linking exception is specific to Autodesk Revit. It should not
be assumed to cover Rhino, Tekla, Navisworks, Archicad, SketchUp, or other
proprietary SDKs.

Before distributing another desktop connector:

- Review the vendor SDK and marketplace terms.
- Keep proprietary SDK binaries out of the repository unless redistribution is
  expressly allowed.
- Prefer references to assemblies installed with the host product.
- Decide whether a connector-specific exception or a broader host-application
  linking exception is required.
- Obtain qualified legal review before publishing revised exception language.

Cloud REST integrations also require review of API terms, branding rules,
commercial-use limits, and data retention requirements.

## Recommended Repository Direction

The exact package names belong in the architecture decision, but ownership
should move toward these boundaries:

```text
packages/
  aec-model-bridge-core/       provider contracts, registry, policy, audit
  aec-model-bridge-mcp/        MCP composition and compatibility aliases
  mcp-server-revit/            existing package during migration
  revit-bridge-addin/          existing Revit desktop adapter
  connector-ifc/               first headless provider
  connector-rhino/             future local host adapter
  connector-autodesk-forma/    future OAuth cloud provider
  connector-tekla/             future local host adapter
```

Do not create all of these directories immediately. Add a package only when it
contains an implemented provider, tests, and documentation.

Cross-provider workflows belong in the orchestration layer. Connectors should
remain thin translators around vendor APIs and should not call each other
directly.

## First Implementation Slice

The first implementation after the architecture decision should deliver:

1. A typed provider protocol and capability manifest.
2. A provider registry with one fake provider for contract tests.
3. A compatibility adapter around the existing Revit bridge client.
4. An IfcOpenShell provider with read-only tools:
   - Health and library version.
   - Open/close or scoped file session.
   - File schema, header, units, and georeferencing summary.
   - Spatial hierarchy.
   - Element query by IFC class, GUID, name, and property criteria.
   - Property sets and quantities.
   - Geometry or bounding-box summary without returning oversized meshes by
     default.
   - IFC validation and structured findings.
5. Small IFC fixtures covering IFC2X3 and IFC4 when licensing permits.
6. Contract, security, schema, and regression tests.
7. Documentation showing existing Revit configuration and the new
   multi-provider configuration side by side.

Writes, geometry authoring, BCF creation, and IDS workflows should follow only
after the read-only provider is stable.

## Acceptance Criteria

The architecture foundation is complete when:

- Existing Revit clients work without tool-name or configuration regressions.
- Provider discovery is data-driven rather than another central switch table.
- A fake provider and the Revit compatibility adapter pass the same contract
  tests.
- IFC tools work without Revit or any licensed desktop application.
- Mutating, high-risk, and asynchronous capabilities are represented in the
  manifest even if the first IFC release is read-only.
- Local provider requests are authenticated and use collision-free endpoints.
- Cloud credential interfaces exist only when a cloud provider is implemented.
- Tests cover malformed manifests, unavailable providers, stale discovery
  records, path traversal, oversized requests, and redacted logs.
- The Python suite passes and Revit 2024 through 2027 add-in builds remain
  successful.

## Evidence Limits

Vendor APIs, product names, entitlements, beta status, pricing, and marketplace
rules change. This research establishes a direction, not a substitute for
checking the official documentation during implementation.

Some integrations cannot be verified fully without paid accounts or installed,
licensed desktop applications. Keep those tests behind explicit live-test
flags and record the exact product version, account entitlement, region, and
date used for each verification.
