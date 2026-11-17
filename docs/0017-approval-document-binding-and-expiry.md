# ADR 0017: Binding approvals to a Revit document, and expiring them

Status: not in 1.5.0 (see below).

## Status
Accepted, implemented in part (see "As built"). Not verified against a live Revit.

## Context
A person approves a plan after reading its actions. Today the approval records the plan hash, who approved, when and through which channel (see [security](security.md)). It does not record which Revit document, view or instance the person had in mind, and it never expires. An approved plan stays executable until it runs, is rejected, or its running actions are abandoned.

Consequences, read from the code:

- A plan drafted and approved against model A can be executed after the person switched to model B, or in a different Revit when several are open ([ADR 0014](0014-multi-revit-routing.md)). Element ids are only meaningful inside one document, so the actions may touch unrelated elements.
- An approval given on Monday can be spent on Friday, after the model changed. The before-values captured at drafting are then stale.
- Plans do not record the Revit instance that created them (listed in security.md, "Before any release: panel token and routing").

## Decision (proposed)
1. **Document binding.** At drafting, store a `binding` object inside the hashed plan: document GUID or central path hash, document title, Revit process id and start time, Revit version, and the active view id for view-scoped actions. The CLI and panel show it. `claim_action` compares it with the live document and refuses on a mismatch, with a message naming both. Fail closed: if the live document cannot be read, the claim is refused. Plans without a binding cannot be approved after the change (same rule as plans without `plan_hash`).
2. **Expiry.** `approved_at` already exists. Add a configurable `approval_ttl` (default proposed: 8 hours, 0 disables). `verify_approved` refuses a plan whose approval is older than the TTL, and the plan moves to `expired`, which needs a new plan. Expiry is checked at claim time, not by a timer, so a clock jump cannot reopen anything; a clock set backwards is treated as expired.
3. **No silent renewal.** Neither check can be waived by a tool call. Only a new approval by a person renews anything.

## Alternatives considered
- Binding only on the document title: titles repeat and can be renamed.
- Expiry without binding: does not stop use in the wrong document within the window.
- Re-reading before-values at claim time and refusing on drift: complementary, tracked separately (the revert path already does this).

## Consequences
- Changes the hashed plan content, so `hash_version` must be bumped and the proof bundle format extended; this overlaps with the proof and review work and must follow it.
- Needs a Revit run to verify document identity on workshared, detached and linked models (UNVERIFIED).
- Plans drafted before the change must be drafted again.

## As built
Done, and only ever stricter:

- **Expiry.** `approval_ttl` (`MCP_REVIT_APPROVAL_TTL`, seconds, default 28800, 0 disables) and a separate `pending_ttl` (`MCP_REVIT_PENDING_TTL`, default 14 days, 0 disables). Checked at claim time from the stored times, never by a timer. An approval older than the TTL, with no `approved_at`, or dated in the future (clock set back) moves the plan to `expired` and is refused with a message that a person must approve again. TTL settings accept whole seconds. Invalid values, including fractions, fall back to the default, never to "off". Expiry blocks new claims while already claimed actions can finish or be recovered. Their final proof is preserved: fully successful plans become `executed`, and plans with failed or unstarted actions become `partial`. Expired pending plans are hidden from `list` and `list_pending_plans` (count in `expired_hidden`, `--all` / `include_expired` shows them), cannot be approved, can still be rejected, and are never deleted.
- **Binding.** `binding` (doc guid, central path hash, title, Revit version, active view id for plans whose actions carry `view_id`/`view_ids`) is stored in the hashed plan and compared with the live `revit_get_context` when an action is claimed, and up front in `execute_plan`. A mismatch, or a bound plan whose live document cannot be read, is refused.
- **Hash.** `binding` is hashed only when the key is present, in version 1 and 2 plans alike, so no stored plan changes its hash and `hash_version` is unchanged. Stripping or editing the key breaks the hash.

Differences from the proposal:

- **Null binding is allowed.** When no live document can be identified at drafting (mock mode, no Revit, Revit busy, no guid or central path) the binding is `null` and the plan is not refused for its document. This is looser than "plans without a binding cannot be approved", chosen so mock mode and drafting while Revit is busy keep working; it is the one place this feature does not fail closed. The CLI prints "NOT BOUND".
- **No process id or start time.** `revit_get_context` does not report them. The document identity is what is compared.
- **Panel page** does not display the binding or the expired count yet; the data is in the list API and `show` prints it.
- Plans drafted before this change need no redraft; they simply carry no binding.
