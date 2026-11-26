# ADR 0002: Switch Contract v2 Specification

**Status:** Accepted
**Date:** 2026-06-13

## Context
Our initial architecture (ADR 0001) established a multi-provider model where desktop switches (Revit, Navisworks) run local HTTP servers that the hub contacts. However, this relied on hardcoded ports (3000, 3002) and lacked authentication, preventing concurrent instances and leaving the local bridge unsecured. We need a robust Contract v2 to standardize discovery, security, and capabilities across all switches.

## Decision
We adopt "Switch Contract v2", which standardizes how desktop and local switches advertise their presence, secure their endpoints, and describe their tools.

### 1. Discovery Registry & Dynamic Ports
- Switches bind to an OS-assigned dynamic loopback port (`127.0.0.1:0`) on startup.
- Upon binding, the switch creates a JSON registry file at:
  `%LOCALAPPDATA%\AECModelBridge\registry\<provider_id>-<pid>.json`
- **Registry Schema:**
  ```json
  {
    "provider_id": "string",
    "endpoint": "http://127.0.0.1:<port>",
    "pid": "integer",
    "host_version": "string",
    "connector_version": "string",
    "protocol_version": 2,
    "capability_digest": "string",
    "session_token": "string",
    "started_at": "ISO-8601 timestamp"
  }
  ```
- The switch deletes its registry file upon graceful shutdown.
- **Pruning Rules:** The hub is responsible for checking PID liveness when scanning the directory. Any file whose PID is no longer running, or is older than a maximum age (e.g., 7 days if the process ID is reassigned to something else, verified via process name) must be deleted by the hub.

### 2. Token Rules & Authentication
- **Generation:** The switch generates a cryptographically secure random session token at startup (e.g., 32 bytes hex).
- **ACL:** The registry file must be written with OS-level ACLs restricting read access to the current user only.
- **Header:** The hub sends the token on all requests via the HTTP header: `Authorization: Bearer <session_token>`.
- Requests lacking a valid token are rejected with HTTP 401 Unauthorized.

### 3. Endpoints & Protocol
All v2 switches must implement three endpoints:
- `GET /health` (returns `{ status, application, host_version, connector_version, protocol_version, document: {...} | null }`)
- `GET /capabilities` (returns the tool manifest per ADR 0001 §3, including `is_mutating`, `confirmation_required`, `execution_mode`)
- `POST /execute` (accepts `{ tool, payload, request_id, idempotency_key? }`)

**Result Envelope:**
Every execution returns:
```json
{
  "ok": true,
  "request_id": "...",
  "data": {},
  "warnings": [],
  "artifacts": [ { "kind": "file|url|object_ref", "value": "..." } ],
  "job": null
}
```

### 4. Legacy Fallback & Deprecation
- The hub will attempt to probe the legacy fixed ports (`3000` for Revit, `3002` for Navisworks) without tokens.
- If a legacy switch responds, the hub issues a deprecation warning in its logs but allows the connection.
- Legacy fallback will be maintained for one minor release cycle before being removed.

## Consequences
- The PY and NET lanes can implement discovery and security independently against this spec.
- Hardcoded port collisions are eliminated.
- Local endpoint security is established, satisfying the missing policy layers.
