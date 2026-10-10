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
- **Rolled Back**: The recorded changes are reversed by `rollback_plan`, which applies inverse parameter values and can skip an action that has no recorded before-value. Revit's own Ctrl+Z is the other route. Neither is verified in a live Revit session (UNVERIFIED).

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
- **Auto-Approval**: For headless CI/CD pipelines, `approval_mode=auto` can be set via environment variable (`MCP_REVIT_APPROVAL_MODE=auto`).

### 4. Rollback Strategies
- **Revit Undo (`undo`)**: Design target, not built. The intent is one named transaction per plan (`"AMB: Plan <plan_id>"`), so that a single Ctrl+Z reverts the whole plan. Today the add-in names one transaction per action (for example one per parameter write), so undoing a plan takes one Ctrl+Z per action. A one-step undo for a whole plan is planned. Live-Revit behaviour is UNVERIFIED.
- **Inverse Counter-Plan (`inverse`)**: For persistent history rollbacks, the hub records the before-state (e.g., parameter values) and `rollback_plan` writes those values back in reverse order. An action with no recorded before-value (including an empty one) is skipped and reported as a warning, so a rollback can be partial. `plan_revert` drafts the same reversal as a new plan that needs approval. Live-Revit behaviour is UNVERIFIED.
- **Irreversible (`none`)**: High-risk operations (e.g., deleting models, file outputs) cannot be rolled back and require a double-confirmation from the human operator.

## Consequences
- **Trust & Safety**: Reduces the risk of hallucinated or malicious AI writes damaging BIM models. The gate is enforced in the hub; behaviour in a live Revit session is UNVERIFIED.
- **Audit Trails**: Every write corresponds to a versioned ActionPlan, a specific approving user, and an audit ledger entry.
- **Decoupled Orchestration**: AI agents can generate plans asynchronously while running long-running processes (e.g., clash detection), leaving the execution to the user.
