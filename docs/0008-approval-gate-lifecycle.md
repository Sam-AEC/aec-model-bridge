# ADR 0008: Approval Gate & ActionPlan Lifecycle

## Status
Accepted

## Context
AI agents modifying production BIM models (e.g., Revit, Navisworks) pose significant risks of silent data corruption, coordinate drift, or breaking company standards. We need a secure boundary where AI agents can propose changes (read, analyze, and plan) but can never execute modifying operations directly without explicit human review and approval. 

## Decisions

### 1. ActionPlan Lifecycle
An **ActionPlan** is the unit of human approval and execution control. It transitions through the following states:

```mermaid
---
config:
  look: neo
  theme: base
  themeVariables:
    primaryColor: "#334155"
    primaryTextColor: "#FFFFFF"
    primaryBorderColor: "#1E293B"
    secondaryColor: "#334155"
    tertiaryColor: "#334155"
    lineColor: "#6E7781"
    textColor: "#6E7781"
    titleColor: "#6E7781"
    nodeTextColor: "#FFFFFF"
    clusterBkg: "rgba(110,119,129,0.10)"
    clusterBorder: "#6E7781"
    edgeLabelBackground: "#334155"
    actorBkg: "#334155"
    actorTextColor: "#FFFFFF"
    actorBorder: "#1E293B"
    actorLineColor: "#6E7781"
    signalColor: "#6E7781"
    signalTextColor: "#6E7781"
    labelBoxBkgColor: "#334155"
    labelBoxBorderColor: "#6E7781"
    labelTextColor: "#FFFFFF"
    loopTextColor: "#6E7781"
    sequenceNumberColor: "#FFFFFF"
    noteBkgColor: "#F59E0B"
    noteTextColor: "#1F1300"
    noteBorderColor: "#92400E"
    transitionColor: "#6E7781"
    transitionLabelColor: "#FFFFFF"
    stateLabelColor: "#FFFFFF"
    stateBkg: "#334155"
    labelBackgroundColor: "#334155"
    compositeBackground: "#334155"
    specialStateColor: "#6E7781"
---
stateDiagram-v2
  state "Pending review" as Pending
  state "Rolled back" as RolledBack

  [*] --> Draft
  Draft --> Validated: plan_actions
  Validated --> Pending: submit
  Pending --> Approved: approve
  Pending --> Rejected: reject
  Approved --> Executed: execute
  Executed --> RolledBack: rollback_plan
  Rejected --> [*]
  RolledBack --> [*]

  classDef ok fill:#0F766E,stroke:#0B4F4A,color:#FFFFFF
  classDef blocked fill:#B91C1C,stroke:#7F1D1D,color:#FFFFFF
  class Approved,Executed ok
  class Rejected blocked
```

- **Draft**: A plan containing proposed actions (tool calls and arguments) under construction.
- **Validated**: The plan has been checked against schemas, and dry-run validation checks have run (e.g., uniqueness, category support, element ownership).
- **Pending**: Submitted to the human approval queue, visible on the dockable panel.
- **Approved**: Human checked the parameter diffs and element counts, giving explicit consent.
- **Rejected**: Human rejected the plan; it is closed and archived.
- **Executed**: The changes are applied to the model inside host transactions.
- **Rolled Back**: The executed changes are reversed using Revit Undo (same session) or inverse parameters.

### 2. ActionPlan Schema
The ActionPlan represents a batch of modifications:
```json
{
  "plan_id": "plan_01J...ULID",
  "state": "pending",
  "created_at": "2026-07-08T18:07:30Z",
  "actions": [
    {
      "action_id": "act_01...",
      "tool": "revit.batch_set_parameters",
      "arguments": {
        "elements": ["revit-uniqueid-1"],
        "parameter": "FireRating",
        "value": "60"
      },
      "diff": {
        "type": "parameter_change",
        "before": {"revit-uniqueid-1": {"FireRating": null}},
        "after": {"revit-uniqueid-1": {"FireRating": "60"}},
        "element_count": 1
      }
    }
  ],
  "is_reversible": true,
  "reversible_strategy": "inverse"
}
```

### 3. The Approval Gate Middleware
- **Enforcement Location**: The unified Python MCP hub acts as the single choke point. 
- **Rule**: If `approval_mode=required` (default in panel mode), any tool call containing mutating or destructive metadata (`is_mutating=True` or `destructive=True`) must supply a valid, approved `plan_id`. Unplanned mutations are immediately blocked and returned as an authorization error.
- **Bound to the approved action** (approval v2): a call with a `plan_id` must match a not-yet-executed action of that plan by tool name and canonical arguments (`plan_id`, `run_async`, `idempotency_key` are ignored; key order and `5` vs `5.0` do not matter). The matching action is marked `executed` when the call runs, on every path (MCP, `run_async` at queue time, panel, chat, recipes, `execute_plan`), and the plan becomes `executed` when all its actions have. A second identical call, or any call the plan does not contain, is refused. Only a `pending` plan can be approved or rejected.
- **Humans approve**: `approve_plan`, `reject_plan` and `rollback_plan` stay registered (the panel calls the registry directly) but are not listed to MCP clients, are refused over MCP, and are denied to the panel's Claude chat (`--disallowedTools`). The server instructions tell the model to stop after drafting a plan and ask the person. Approval happens in the panel (`approved_via: "panel"`) or with `aec-model-bridge-approve` (`approved_via: "cli"`, `approved_by: "cli"`), which prints the plan and needs the plan id typed, or `--yes`, and refuses non-interactive input without it.
- **Limits**: this does not authenticate the human, and a process that can run shell commands as the user can use `--yes`. `approval_mode` semantics are unchanged.
- **Auto-Approval**: For headless CI/CD pipelines, `approval_mode=auto` can be set via environment variable (`MCP_REVIT_APPROVAL_MODE=auto`).

### 4. Rollback Strategies
- **Revit Undo (`undo`)**: If executed inside the same Revit session, the add-in wraps the execution in a single named transaction (`"AMB: Plan <plan_id>"`). The add-in can trigger Revit's native Undo command.
- **Inverse Counter-Plan (`inverse`)**: For persistent history rollbacks, the hub generates an inverse counter-plan by capturing the before-state (e.g., parameter values) and executing a compensating batch of updates.
- **Irreversible (`none`)**: High-risk operations (e.g., deleting models, file outputs) cannot be rolled back and require a double-confirmation from the human operator.

## Consequences
- **Trust & Safety**: Eliminates the risk of hallucinated or malicious AI writes damaging BIM models.
- **Audit Trails**: Every write corresponds to a versioned ActionPlan, a specific approving user, and an audit ledger entry.
- **Decoupled Orchestration**: AI agents can generate plans asynchronously while running long-running processes (e.g., clash detection), leaving the execution to the user.
