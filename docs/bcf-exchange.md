# BCF issue exchange

Two tools move issues in and out of the standard BCF 2.1 `.bcfzip` format:

- `bcf_exchange_export_bcf` saves a list of issues, and optionally the issues recorded by the QA/QC checker, to a `.bcfzip` file in your workspace folder.
- `bcf_exchange_import_bcf` reads a `.bcfzip` from your workspace folder and returns the issues (title, description, status, priority, assigned to, element ids).

Each issue can carry `title`, `description`, `status`, `priority`, `author`, `assigned_to`, `element_uids` (Revit UniqueIds) and `ifc_guids`. Neither tool changes the Revit model.

## Safety

Files must be inside the allowed workspace directories. When reading, the zip is never unpacked to disk. Files with paths that climb out of the archive, absolute paths, symbolic links, too many entries or oversized content (zip bombs) are refused, as is any XML that declares a DOCTYPE or entity (which blocks entity expansion and external-file tricks).

## Not verified

The BCF layout was written from general knowledge of BCF 2.1. It has **not** been validated against buildingSMART's XSD schemas, and files have **not** been opened in Revit, Solibri, BIMcollab, Navisworks or any other BCF tool. Treat interoperability as UNVERIFIED. Revit UniqueIds are not IFC GUIDs, so they are stored as the authoring-tool id of a component; only IFC GUIDs given as `ifc_guids` are written as `IfcGuid`. Viewpoints contain a component selection only (no camera).

## BCF 3.0 server topics

Three more tools talk to a BCF 3.0 REST server (for example BIMcollab or Revizto) for topics only:

- `bcf_exchange_list_server_topics` lists topics (`GET /bcf/3.0/projects/{project_id}/topics`). It is read-only.
- `bcf_exchange_create_server_topic` creates a topic (`POST` to the same path). It needs an approved plan.
- `bcf_exchange_update_server_topic` updates a topic by `topic_guid` (`PUT .../topics/{guid}`). It needs an approved plan.

Create and update go through `plan_actions`, human approval and `execute_plan` like every other write. Call them with the same arguments the plan holds. They change the server, not the Revit model. Viewpoints, comments and images are not synced.

### Setup

Set these environment variables for the MCP server process:

| Variable | Meaning |
|---|---|
| `MCP_REVIT_BCF_URL` | Server base address, for example `https://bcf.example.test`. Must be `https`; plain `http` is accepted only for `127.0.0.1` and `localhost` (for a local mock). No user name, query or fragment. |
| `MCP_REVIT_BCF_TOKEN` | Bearer token. Only read from the environment. It is never a tool argument and is never logged, returned or put in an error. |
| `MCP_REVIT_BCF_PROJECT_ID` | Default project id. A `project_id` argument overrides it. |

The server address is not a tool argument, so a prompt cannot send the token to another host. Redirects are not followed. Requests time out after 15 seconds. A missing token, or a 401 or 403 answer, gives a plain refusal. A response that is not JSON, or has the wrong shape, is refused.

Topic fields: `title` (required on create), `description`, `topic_type`, `topic_status`, `priority`, `assigned_to`, `due_date`, `stage`, `labels`.

UNVERIFIED: the client is tested only against a local mock of the BCF 3.0 topics endpoints. It has not been run against real BIMcollab or Revizto servers, whose authentication (OAuth2 flows, token refresh) and project paths may differ.
