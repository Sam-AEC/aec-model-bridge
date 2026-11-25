import contextlib
import contextvars
import getpass
import os
import re
import tempfile
import threading
import time
import uuid
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Any, Iterator, List, Optional, Tuple
from ..config import APPROVAL_MODES, config, normalize_approval_mode  # noqa: F401 (re-exported)
from ..errors import BridgeError
from . import approval_signing as signing_mod
from . import binding as binding_mod
from . import file_binding
from . import proof as proof_mod
from . import rollback_preview as rollback_preview_mod
from .approval_override import active_override
from .dev_mode import active_dev, audit_dev_event
from .recipe_store import RecipeStore, standing_authorizes
from .safe_paths import PLAN_ID_RE, safe_child
from .workspace import WorkspaceMonitor

logger = logging.getLogger(__name__)

# Tools that move a plan between approval states. They stay registered (the Revit
# panel and the command-line tool use them) but are never offered to a model: an
# agent that can approve its own plan has no human gate at all. Every internal
# dispatch path refuses them too (see security/dispatch.py); only
# ApprovalProvider.execute_human_tool, called by the panel route, runs them.
HUMAN_ONLY_TOOLS = frozenset({"approve_plan", "reject_plan", "rollback_plan"})

# Channels that may record an approval. Set by the code path, never by tool arguments.
APPROVAL_CHANNELS = frozenset({"panel", "cli"})

# Arguments that identify or schedule a call rather than describe the change, so
# they are ignored when matching a call to an approved action.
VOLATILE_ARGUMENT_KEYS = frozenset({"plan_id", "run_async", "idempotency_key"})

# Plan keys the caller of create_plan(extra=...) may not set: the hash fields and the
# hashed review block (which has its own validated parameter).
_RESERVED_EXTRA_KEYS = frozenset({
    "review", "hash_version", "plan_hash", "approved_hash", "plan_id", "created_at", "actions", "binding",
    "rollback_preview",
}) | proof_mod.STATE_PLAN_KEYS | proof_mod.DERIVED_PLAN_KEYS

ACTION_ID_RE = re.compile(r"act_[0-9a-f]{12}")
INFLIGHT_KEY_RE = re.compile(r"[A-Za-z0-9_-]{1,80}")
_CLAIM_NAME_RE = re.compile(PLAN_ID_RE.pattern + r"\." + ACTION_ID_RE.pattern)

# Action states. Only "pending" is open; "running", "executed" and "failed" are consumed.
OPEN_ACTION_STATES = frozenset({"pending", None})
DONE_ACTION_STATES = frozenset({"executed", "failed", "abandoned"})
# A running action older than this is shown as STALE to the person; nothing is ever
# recovered automatically, only the human `recover` command changes it.
STALE_RUNNING_SECONDS = 15 * 60
# os.replace can raise PermissionError on Windows while a reader holds the target.
REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF_SECONDS = 0.01

_PROCESS_LOCK = threading.RLock()


LOOK_ONLY_MESSAGE = (
    "Look only mode: this tool changes the model. Switch to Ask me first in the panel or settings."
)


def _refuse_plan_id(reason: str) -> BridgeError:
    if reason == "outside":
        return BridgeError("Invalid plan_id: the plan file is outside the plans folder.")
    return BridgeError(
        "Invalid plan_id: expected the id returned by plan_actions ('plan_' followed by 12 hex characters)."
    )


class ApprovalExpired(BridgeError):
    """An approval is older than approval_ttl. Only a new plan that a person approves renews anything."""


BINDING_PROBE_REUSE_S = 10.0  # one execute_plan reads the live document again after this many seconds
_PROBE_REUSE: "contextvars.ContextVar[Optional[Dict[str, Any]]]" = contextvars.ContextVar("binding_probe_reuse", default=None)
_UNBOUND = object()  # create_plan(binding=...) default: the plan carries no binding key (older format)


def _age_seconds(stamp: Any, now: datetime) -> Optional[float]:
    """Seconds since an ISO timestamp, or None when it is missing or unreadable."""
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now - when).total_seconds()


def _span(seconds: float) -> str:
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            return f"{seconds / size:.1f} {unit}s"
    return f"{int(seconds)} seconds"


def validate_plan_id(plan_id: Any) -> str:
    """Accept only ids of the shape create_plan makes; anything else is refused."""
    if not isinstance(plan_id, str) or not PLAN_ID_RE.fullmatch(plan_id):
        raise _refuse_plan_id("name")
    return plan_id


def local_user() -> str:
    """The OS account running this process. Recorded, not authenticated."""
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _canonical(value: Any) -> Any:
    """Normalise JSON-ish data so equal calls compare equal (key order, 5 vs 5.0)."""
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical_arguments(arguments: Any) -> str:
    if not isinstance(arguments, dict):
        # Never let a malformed (non-object) argument list compare equal to {}.
        return json.dumps({"__not_an_object__": _canonical(arguments)}, sort_keys=True, default=str,
                          separators=(",", ":"))
    kept = {k: v for k, v in arguments.items() if k not in VOLATILE_ARGUMENT_KEYS}
    return json.dumps(_canonical(kept), sort_keys=True, default=str, separators=(",", ":"))


def plan_hash(plan: Dict[str, Any]) -> str:
    """Content hash of what a person reviews: ids, tools, arguments, before values."""
    return proof_mod.plan_content_hash(plan)


@contextlib.contextmanager
def _locked_file(path: Path) -> Iterator[None]:
    """Exclusive lock on ``path`` across processes (fcntl on POSIX, msvcrt on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
        msvcrt = None
    except ImportError:  # pragma: no cover - Windows
        import msvcrt
        fcntl = None
    with open(path, "a+b") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        else:  # pragma: no cover - Windows
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def replace_with_retry(src: Any, dst: Any) -> None:
    """Atomic ``os.replace`` with a bounded retry for transient PermissionError (Windows
    readers such as antivirus or a polling panel). Atomicity is unchanged: the same single
    replace call is retried, never a delete-then-write. Fails with a clear BridgeError."""
    last: Optional[BaseException] = None
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last = e
            if attempt < REPLACE_ATTEMPTS - 1:
                time.sleep(min(0.05, REPLACE_BACKOFF_SECONDS * (attempt + 1)))
    raise BridgeError(
        f"Could not write '{Path(str(dst)).name}': the file stayed locked by another program after "
        f"{REPLACE_ATTEMPTS} attempts ({last}). Nothing was changed; close whatever is reading the "
        "plans folder and try again."
    )


def running_actions(plan: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Actions stuck in 'running', each as {action_id, tool, claimed_at, age_seconds, stale}.
    Information only: nothing here changes a plan."""
    now = now or datetime.now(timezone.utc)
    out = []
    actions = plan.get("actions", [])
    for a in actions if isinstance(actions, list) else []:
        if not isinstance(a, dict) or a.get("state") != "running":
            continue
        age = None
        try:
            claimed = datetime.fromisoformat(str(a.get("claimed_at")))
            if claimed.tzinfo is None:
                claimed = claimed.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - claimed).total_seconds())
        except (TypeError, ValueError):
            pass
        out.append({"action_id": a.get("action_id"), "tool": a.get("tool"), "claimed_at": a.get("claimed_at"),
                    "age_seconds": age, "stale": age is None or age >= STALE_RUNNING_SECONDS})
    return out


def write_rule(mode: str, dev_mode: bool = False) -> Dict[str, Any]:
    """What an AI client must do before a write, in one place, so it does not draft plans it does not need.

    plans_required is True only in ask_first. look_only refuses every write. auto (environment
    Auto, a timed panel window or Dev mode) runs writes directly, audited, with no plan.
    """
    if mode == "look_only":
        return {"plans_required": False, "writes_allowed": False,
                "write_rule": "Look only: every write is refused. Do not draft plans."}
    if mode == "auto":
        why = "Dev mode" if dev_mode else "Auto"
        return {"plans_required": False, "writes_allowed": True,
                "write_rule": f"{why}: call write tools directly with no plan_actions and no plan_id. "
                              "Calls are audited. Check again if a write is refused; the person can switch modes."}
    return {"plans_required": True, "writes_allowed": True,
            "write_rule": "Ask first: draft one plan with plan_actions, ask the person to approve it in the panel "
                          "or with aec-model-bridge-approve, then call execute_plan."}


class ApprovalGate:
    def __init__(self, workspace_dir: Path, approval_mode: str = config.approval_mode,
                 approval_ttl: Optional[int] = None, pending_ttl: Optional[int] = None) -> None:
        self.workspace_dir = workspace_dir
        # Seconds, 0 = no limit. Set from the environment, never from a tool call.
        self.approval_ttl = config.approval_ttl if approval_ttl is None else approval_ttl
        self.pending_ttl = config.pending_ttl if pending_ttl is None else pending_ttl
        # Reads the live Revit context (revit_get_context shape); set by the provider wiring. Without
        # one, a plan that carries a document binding cannot be executed (fail closed).
        self.binding_probe: Optional[Callable[[], Any]] = None
        self.override_token: Optional[str] = None  # tests; normally read from the panel token file
        self.approval_mode = approval_mode
        # Workspace check for files whose content is bound to a plan (file_binding.py). The
        # provider wiring sets the server's monitor; the default allows only the plan workspace.
        self.workspace_monitor: WorkspaceMonitor = WorkspaceMonitor([workspace_dir])
        self.plans_dir = workspace_dir / "plans"
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    @property
    def approval_mode(self) -> str:
        """The mode in force right now: the mode this process started with, unless the panel has
        switched approvals to timed Auto or explicit Dev mode. Neither override
        relaxes configured look_only."""
        if self.dev_mode:
            return "auto"
        if self._approval_mode == "ask_first" and active_override(self.workspace_dir, token=self.override_token):
            return "auto"
        return self._approval_mode

    @approval_mode.setter
    def approval_mode(self, value: Any) -> None:
        self._approval_mode = normalize_approval_mode(value)

    @property
    def baseline_approval_mode(self) -> str:
        """The mode this process started with, ignoring any temporary 'auto' window."""
        return self._approval_mode

    @property
    def dev_mode(self) -> bool:
        return self._approval_mode != "look_only" and active_dev(self.workspace_dir, token=self.override_token)

    def audit_dev_call(self, tool_name: str, arguments: Any, *, mutating: bool) -> None:
        if self.dev_mode:
            audit_dev_event(self.workspace_dir, "call", tool=tool_name, mutating=mutating, arguments=arguments)

    def auto_window(self) -> Optional[Dict[str, int]]:
        """{"set_at", "expires_at"} while a temporary 'auto' window is in force, else None."""
        if self._approval_mode == "ask_first" and not self.dev_mode:
            return active_override(self.workspace_dir, token=self.override_token)
        return None

    def approval_state(self) -> Dict[str, Any]:
        """What is in force right now, for read-only reporting: the live mode (including a
        signed temporary 'auto' window), the mode this process started with, and the window."""
        window = self.auto_window()
        mode = self.approval_mode
        return {
            "mode": mode,
            "configured_mode": self.baseline_approval_mode,
            "dev_mode": self.dev_mode,
            **write_rule(mode, self.dev_mode),
            "auto_window": dict(window) if isinstance(window, dict) else None,
            "auto_expires_at": window.get("expires_at") if isinstance(window, dict) and mode == "auto" else None,
        }

    def refuse_if_look_only(self) -> None:
        """Raise when the mode is look_only. Called for every mutating tool, on every path."""
        if self.approval_mode == "look_only":
            raise BridgeError(LOOK_ONLY_MESSAGE)

    def _get_plan_path(self, plan_id: str) -> Path:
        return safe_child(self.plans_dir, plan_id, ".json", PLAN_ID_RE, _refuse_plan_id)

    @contextlib.contextmanager
    def _plan_lock(self, plan_id: str) -> Iterator[None]:
        """Serialise read-modify-write of one plan across threads and processes."""
        lock_path = safe_child(self.plans_dir, plan_id, ".lock", PLAN_ID_RE, _refuse_plan_id, subdir=".locks")
        with _PROCESS_LOCK, _locked_file(lock_path):
            yield

    def load_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_plan_path(plan_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                plan = json.load(f)
        except Exception as e:
            logger.error("Failed to load a plan file: %s", type(e).__name__)
            return None
        if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
            raise BridgeError(f"Plan file for '{plan_id}' does not hold that plan; refusing to use it.")
        return plan

    def save_plan(self, plan: Dict[str, Any]) -> None:
        plan_id = plan["plan_id"]
        path = self._get_plan_path(plan_id)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{plan_id}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2)
            replace_with_retry(tmp, path)
        except Exception as e:
            logger.error("Failed to save plan %s: %s", plan_id, e)
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    @staticmethod
    def validate_actions(actions: Any) -> None:
        """Refuse action lists a person could not review faithfully or that name human-only tools."""
        if not isinstance(actions, list):
            raise BridgeError("'actions' must be a list.")
        for i, action in enumerate(actions):
            if not isinstance(action, dict) or not isinstance(action.get("tool"), str) or not action.get("tool"):
                raise BridgeError(f"Action {i + 1} must be an object with a 'tool' name.")
            if action["tool"] in HUMAN_ONLY_TOOLS:
                raise BridgeError(f"Action {i + 1}: '{action['tool']}' cannot be part of a plan; a person runs it.")
            if not isinstance(action.get("arguments", {}), dict):
                raise BridgeError(f"Action {i + 1} ('{action['tool']}'): 'arguments' must be an object.")

    def create_plan(
        self,
        actions: List[Dict[str, Any]],
        before_states: List[Dict[str, Any]],
        snapshot_id: Optional[str] = None,
        skipped: Optional[List[Dict[str, Any]]] = None,
        extra: Optional[Dict[str, Any]] = None,
        before_storage_types: Optional[List[Optional[str]]] = None,
        review: Optional[Dict[str, Any]] = None,
        binding: Any = _UNBOUND,
        policy_hash: Optional[str] = None,
        rollback_preview: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Draft a plan. ``review`` (summary, reasoning, citations, ...) is validated,
        canonicalised and covered by the plan hash. ``binding`` (a dict, or None when the live
        document could not be identified) is stored inside the hashed plan; leave it out for the
        older, unbound format. ``extra`` is metadata only: it is NOT
        hashed and must not be presented as approved content (see proof.unhashed_metadata_keys).
        ``rollback_preview`` (security/rollback_preview.py, #293) is the result of running the plan in a
        group that was rolled back. It is stored inside the hashed plan; it is never an approval."""
        self.validate_actions(actions)
        # A file a tool reads at run time is bound by its sha256 in the hashed arguments.
        actions = file_binding.bind_actions(actions, self.workspace_monitor)
        if proof_mod.has_nonfinite_float(actions) or proof_mod.has_nonfinite_float(review):
            raise BridgeError("A plan cannot hold NaN or Infinity.")
        reserved = sorted(k for k in (extra or {}) if k in _RESERVED_EXTRA_KEYS)
        if reserved:
            raise BridgeError("'extra' cannot set: " + ", ".join(reserved)
                              + ". Use the review block for reviewable content.")
        if review is not None:
            try:
                review = proof_mod.normalize_review(review)
            except ValueError as e:
                raise BridgeError(f"Invalid review block: {e}")
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        plan_actions = []
        for i, action in enumerate(actions):
            act_id = f"act_{uuid.uuid4().hex[:12]}"
            before = before_states[i] if i < len(before_states) else {}

            arguments = action.get("arguments", {})
            diff = {
                "type": "parameter_change" if "parameter_name" in arguments else "model_modification",
                "before": before,
                "after": arguments,
                "element_count": 1
            }
            if before_storage_types and i < len(before_storage_types) and before_storage_types[i]:
                # Revit StorageType of the parameter when the before value was captured, so a
                # revert can rebuild a correctly typed value (the live read returns strings).
                diff["before_storage_type"] = before_storage_types[i]
            plan_actions.append({
                "action_id": act_id,
                "tool": action.get("tool"),
                "arguments": arguments,
                "diff": diff,
                "state": "pending"
            })

        plan = {
            "plan_id": plan_id,
            "state": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actions": plan_actions,
            "is_reversible": True,
            "reversible_strategy": "inverse"
        }
        if snapshot_id:
            plan["snapshot_id"] = snapshot_id
        if skipped:
            plan["skipped"] = skipped
        if extra:
            plan.update({k: v for k, v in extra.items() if k not in ("plan_id", "state", "actions")})
        if policy_hash:
            plan["policy_hash"] = policy_hash  # bookkeeping, not hashed
        if review is not None:
            plan["review"] = review
            plan["hash_version"] = proof_mod.HASH_VERSION_REVIEW
        if binding is not _UNBOUND:
            try:
                binding_mod.validate_binding(binding)
            except ValueError as e:
                raise BridgeError(str(e))
            plan["binding"] = binding
        if rollback_preview is not None:
            try:
                plan["rollback_preview"] = rollback_preview_mod.validate(rollback_preview)
            except ValueError as e:
                raise BridgeError(f"Invalid rollback preview: {e}")
        plan["plan_hash"] = plan_hash(plan)
        self.save_plan(plan)
        return plan

    def expiry_reason(self, plan: Dict[str, Any], now: Optional[datetime] = None) -> Optional[str]:
        """Why a pending or approved plan is too old to use, or None. A pending plan expires
        ``pending_ttl`` seconds after drafting, an approved one ``approval_ttl`` seconds after its
        approval. A missing, unreadable or future timestamp counts as expired (clock set back).
        Computed at check time from the stored times, never by a timer. Read-only."""
        now = now or datetime.now(timezone.utc)
        plan_id = plan.get("plan_id")
        if plan.get("state") == "approved":
            ttl, age, name = self.approval_ttl, _age_seconds(plan.get("approved_at"), now), "approval_ttl"
            if not ttl or (age is not None and 0 <= age <= ttl):
                return None
            when = "its approval time is missing or in the future" if age is None or age < 0 else                 f"it was approved {_span(age)} ago"
            return (f"The approval of plan '{plan_id}' has expired ({when}; an approval lasts {_span(ttl)}, "
                    f"{name}). No new actions can run. A person must approve again: draft a new plan and have it approved.")
        if plan.get("state") == "pending":
            ttl, age, name = self.pending_ttl, _age_seconds(plan.get("created_at"), now), "pending_ttl"
            if not ttl or (age is not None and 0 <= age <= ttl):
                return None
            return (f"Plan '{plan_id}' has expired (drafted more than {_span(ttl)} ago, {name}) and cannot be "
                    "approved. Ask for a new plan.")
        return None

    def _mark_expired(self, plan: Dict[str, Any]) -> None:
        """Stop new claims while preserving accounting for earlier work. Caller holds the lock."""
        plan["state"] = "expired"
        plan["expired_at"] = datetime.now(timezone.utc).isoformat()
        plan["expired_reason"] = "approval_ttl"
        states = [a.get("state") for a in plan.get("actions", [])]
        finished = "running" not in states and any(s in DONE_ACTION_STATES for s in states)
        if finished:
            plan["state"] = "executed" if all(s == "executed" for s in states) else "partial"
            plan["executed_at"] = plan["expired_at"]
        self.save_plan(plan)
        if finished:
            try:
                self.record_proof(plan)
            except Exception:
                logger.exception("Failed to write proof bundle for plan %s", plan.get("plan_id"))

    def expire_plan(self, plan_id: str) -> None:
        """Stop an expired approval and account for completed work (no-op otherwise)."""
        with self._plan_lock(plan_id):
            plan = self.load_plan(plan_id)
            if plan and plan.get("state") == "approved" and self.expiry_reason(plan):
                self._mark_expired(plan)

    def split_pending_plans(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """(live, expired) pending plans. Expired ones are only separated, never changed or deleted."""
        live: List[Dict[str, Any]] = []
        stale: List[Dict[str, Any]] = []
        for plan in self._pending_on_disk():
            (stale if self.expiry_reason(plan) else live).append(plan)
        return live, stale

    def pending_listing(self, include_expired: bool = False) -> Tuple[List[Dict[str, Any]], int]:
        """(plans to show, number of expired pending plans left out of that list)."""
        live, stale = self.split_pending_plans()
        if include_expired:
            return live + [{**p, "expired": True} for p in stale], 0
        return live, len(stale)

    def list_pending_plans(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        return self.pending_listing(include_expired)[0]

    def _pending_on_disk(self) -> List[Dict[str, Any]]:
        plans = []
        for path in self.plans_dir.glob("*.json"):
            if not PLAN_ID_RE.fullmatch(path.stem):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    plan = json.load(f)
            except Exception:
                continue
            if isinstance(plan, dict) and plan.get("plan_id") == path.stem and plan.get("state") == "pending":
                plans.append(plan)
        return plans

    def update_plan_state(self, plan_id: str, state: str, approver: Optional[str] = None,
                          via: Optional[str] = None, expected_hash: Optional[str] = None,
                          only_if_state: Optional[str] = None) -> Dict[str, Any]:
        """Move a plan to ``state``.

        Approving needs ``expected_hash``: the hash of the plan the person was shown. The
        approval is refused if the plan on disk no longer has that content, so a person
        approves exactly what they reviewed. ``via`` is the channel ('panel' or 'cli')
        and is set by the calling code path, never taken from tool arguments.
        ``only_if_state`` makes the change conditional on the plan still being in that
        state when the lock is held (bulk cleanup uses it to touch pending plans only).
        """
        with self._plan_lock(plan_id):
            plan = self.load_plan(plan_id)
            if not plan:
                raise ValueError(f"Plan {plan_id} not found")
            current = plan.get("state")
            if only_if_state is not None and current != only_if_state:
                raise ValueError(f"Plan {plan_id} is in state '{current}', not '{only_if_state}'; left unchanged.")
            if state == "approved":
                if current != "pending":
                    raise ValueError(f"Plan {plan_id} is in state '{current}'; only a pending plan can be approved.")
                if via not in APPROVAL_CHANNELS:
                    raise ValueError("An approval must come from the panel or the command-line tool.")
                expired = self.expiry_reason(plan)
                if expired:
                    raise ValueError(expired)
                now_hash = plan_hash(plan)
                if not expected_hash or expected_hash != now_hash:
                    raise ValueError(
                        f"Plan {plan_id} is not the plan that was shown for approval (its content changed). "
                        "Review it again before approving."
                    )
                if proof_mod.plan_hash_version(plan) == proof_mod.HASH_VERSION_REVIEW:
                    # Same strict schema the command-line tool applies, on every approval channel.
                    if proof_mod.normalize_review(plan["review"]) != plan["review"]:
                        raise ValueError(
                            f"Plan {plan_id} has a review block that is not in canonical form; it cannot be approved."
                        )
                if plan.get("plan_hash") != now_hash:
                    raise ValueError(
                        f"Plan {plan_id} was changed after it was drafted. Ask for a new plan instead of approving it."
                    )
            elif state == "rejected":
                if current not in ("pending", "approved"):
                    raise ValueError(
                        f"Plan {plan_id} is in state '{current}'; only a pending or approved plan can be rejected."
                    )
                if via is not None and via not in APPROVAL_CHANNELS:
                    raise ValueError("A rejection must come from the panel or the command-line tool.")
            plan["state"] = state
            now = datetime.now(timezone.utc).isoformat()
            if state == "approved":
                plan["approved_at"] = now
                plan["approved_hash"] = now_hash
                plan["approved_via"] = via
                plan["approved_by"] = str(approver) if approver else local_user()
                # Every channel approves through here, so every approval is signed (issue #313).
                try:
                    signing_mod.sign_plan(self.plans_dir, plan)
                except signing_mod.ApprovalKeyError as e:
                    raise ValueError(f"{e} The plan was not approved.") from None
            elif state == "rejected":
                plan["rejected_at"] = now
                if current == "approved":
                    plan["rejected_after_approval"] = True
                if via:
                    plan["rejected_via"] = via
            fill_proof = False
            if state == "executed":
                plan["executed_at"] = now
                # execute_plan writes a richer proof itself; only fill in for direct tool calls.
                try:
                    fill_proof = proof_mod.read_proof(self.workspace_dir, plan_id) is None
                except ValueError:
                    fill_proof = False
            self.save_plan(plan)
        if fill_proof:
            try:
                self.record_proof(plan)
            except Exception:
                logger.exception("Failed to write a proof bundle")
        return plan

    def record_proof(self, plan: Dict[str, Any], results: Optional[List[Dict[str, Any]]] = None,
                     outcome: Optional[str] = None) -> Dict[str, Any]:
        """Write proofs/<plan_id>.json for a finished (success / partial / failed) plan."""
        bundle = proof_mod.build_proof(plan, self.workspace_dir, results=results, outcome=outcome)
        proof_mod.write_proof(self.workspace_dir, bundle)
        return bundle

    def load_proof(self, plan_id: str) -> Optional[Dict[str, Any]]:
        return proof_mod.read_proof(self.workspace_dir, plan_id)

    def verify_approved(self, plan: Dict[str, Any]) -> None:
        """Refuse unless the plan is approved and still holds exactly what was approved."""
        plan_id = plan.get("plan_id")
        if plan.get("state") != "approved":
            hint = ""
            if plan.get("state") == "pending" and self.dev_mode:
                hint = " The plan is pending. In Dev mode, omit plan_id to run unplanned, or have a person approve it."
            raise BridgeError(
                f"Plan '{plan_id}' is in state '{plan.get('state')}', not 'approved'. Execution blocked.{hint}")
        self._verify_unchanged_since_approval(plan)
        expired = self.expiry_reason(plan)
        if expired:
            raise ApprovalExpired(expired)

    def _verify_unchanged_since_approval(self, plan: Dict[str, Any]) -> None:
        """Refuse unless the plan still hashes to what a person approved (any state) and its
        approval record carries a signature that verifies (issue #313; unsigned fails closed)."""
        plan_id = plan.get("plan_id")
        approved = plan.get("approved_hash")
        try:
            current_hash = plan_hash(plan)
        except ValueError:
            current_hash = None
        if not approved or current_hash != approved:
            raise BridgeError(
                f"Plan '{plan_id}' changed after it was approved (or has no approval record). Execution blocked; "
                "draft a new plan and ask the person to approve it."
            )
        signing_mod.require_signed(self.plans_dir, plan)

    @contextlib.contextmanager
    def reuse_binding_probe(self, max_age_s: float = BINDING_PROBE_REUSE_S):
        """Inside this block one live-document read is shared by every verify_binding call (one
        execute_plan), and read again once it is older than ``max_age_s`` seconds. Only a
        successful read is kept; a failed one is retried by the next call."""
        token = _PROBE_REUSE.set({"max_age": max_age_s, "at": None, "live": None})
        try:
            yield
        finally:
            _PROBE_REUSE.reset(token)

    def _read_live_binding(self) -> Optional[Dict[str, Any]]:
        reuse = _PROBE_REUSE.get()
        if reuse is not None and reuse["live"] is not None and time.monotonic() - reuse["at"] < reuse["max_age"]:
            return reuse["live"]
        live = binding_mod.live_binding(self.binding_probe()) if self.binding_probe else None
        if reuse is not None and live is not None:
            reuse["at"], reuse["live"] = time.monotonic(), live
        return live

    def verify_binding(self, plan: Dict[str, Any]) -> None:
        """Refuse when the live Revit document is not the one the plan was drafted for. A plan with
        no binding (drafted without a live Revit, or before bindings existed) is never refused here.
        A bound plan whose live document cannot be read is refused: failing open would defeat it."""
        bound = plan.get("binding")
        if bound is None:
            return
        plan_id = plan.get("plan_id")
        try:
            live = self._read_live_binding()
        except Exception as e:  # noqa: BLE001 - any failure to read means "cannot confirm"
            logger.warning("Could not read the live document for plan %s: %s", plan_id, e)
            live = None
        if live is None:
            raise BridgeError(
                f"Plan '{plan_id}' is bound to Revit document {bound.get('doc_title')!r} but the live document "
                "could not be read (Revit busy, closed, or no document open). Nothing ran. Try again when Revit is idle."
            )
        differs = binding_mod.mismatches(bound, live)
        if differs:
            raise BridgeError(
                f"Plan '{plan_id}' was drafted for Revit document {bound.get('doc_title')!r} but the active "
                f"document is {live.get('doc_title')!r} ({'; '.join(differs)}). Nothing ran. Open the right model "
                "or draft a new plan for this one; a person must approve it again."
            )

    def verify_bound_files(self, plan: Dict[str, Any]) -> None:
        """Refuse when a file bound to an open action of ``plan`` no longer matches its approved digest."""
        for action in plan.get("actions", []):
            if action.get("state") in OPEN_ACTION_STATES:
                file_binding.verify_action(action.get("tool"), action.get("arguments"), self.workspace_monitor)

    def check_tool_execution(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        """Read-only check that a call is covered by an approved, unchanged plan.

        Execution paths use claim_action, which makes the same checks and consumes the
        action atomically before the tool runs.
        """
        self.refuse_if_look_only()
        if self.approval_mode == "auto":
            return
        if tool_name in HUMAN_ONLY_TOOLS:
            raise BridgeError(f"'{tool_name}' is run by a person, not through a tool call.")

        plan_id = arguments.get("plan_id") if isinstance(arguments, dict) else None
        if not plan_id:
            raise BridgeError(f"Approval mode is enabled. Mutating tool '{tool_name}' requires a valid 'plan_id' parameter.")

        plan = self.load_plan(plan_id)
        if not plan:
            raise BridgeError(f"Plan '{plan_id}' does not exist.")
        self.verify_approved(plan)

        if self._find_open_action(plan, tool_name, arguments) is None:
            raise self._no_action_error(plan_id, tool_name)

    @staticmethod
    def _no_action_error(plan_id: str, tool_name: str) -> BridgeError:
        return BridgeError(
            f"Plan '{plan_id}' does not approve this call: it has no remaining approved action for "
            f"'{tool_name}' with these arguments (an action can only run once, exactly as approved). "
            "Draft a new plan for this change and ask the person to approve it."
        )

    @staticmethod
    def _find_open_action(plan: Dict[str, Any], tool_name: str, arguments: Any,
                          skip: Optional[set] = None) -> Optional[Dict[str, Any]]:
        wanted = canonical_arguments(arguments)
        for action in plan.get("actions", []):
            if action.get("state") not in OPEN_ACTION_STATES or action.get("tool") != tool_name:
                continue
            if skip and action.get("action_id") in skip:
                continue
            if canonical_arguments(action.get("arguments", {})) == wanted:
                return action
        return None

    def _claim_marker(self, plan_id: str, action_id: Any, subdir: str = ".claims") -> Path:
        validate_plan_id(plan_id)

        def refuse(_reason: str) -> BridgeError:
            return BridgeError(f"Plan '{plan_id}' has a malformed action id; refusing to run it.")

        return safe_child(self.plans_dir, f"{plan_id}.{action_id}" if isinstance(action_id, str) else None,
                          "", _CLAIM_NAME_RE, refuse, subdir=subdir)

    def claim_action(self, tool_name: str, arguments: Any) -> Optional[Dict[str, str]]:
        """Consume the matching approved action BEFORE the tool runs (at most once).

        Under a per-plan lock, checks the plan (approved, unchanged since approval),
        finds an open action with the same tool and arguments, creates a claim marker
        with O_EXCL (so exactly one caller wins even across processes, and an edited
        action state cannot reopen it) and marks the action 'running'. The action stays
        consumed whatever the tool does next: a failed or interrupted call needs a new plan.

        Returns {"plan_id", "action_id"} or None when the gate is off and the call
        carries no plan. Raises BridgeError when the call is not allowed.
        """
        if tool_name in HUMAN_ONLY_TOOLS:
            raise BridgeError(f"'{tool_name}' is run by a person, not through a tool call.")
        # One authorization snapshot governs this call. Re-reading panel state
        # after an audit or before plan handling could silently allow an unaudited
        # write (Off -> Dev) or downgrade strict Dev plan checks (Dev -> Off).
        baseline = self._approval_mode
        dev_authorized = baseline != "look_only" and active_dev(self.workspace_dir, token=self.override_token)
        timed_auto = baseline == "ask_first" and not dev_authorized and bool(
            active_override(self.workspace_dir, token=self.override_token)
        )
        mode = "auto" if dev_authorized or timed_auto else baseline
        if mode == "look_only":
            raise BridgeError(LOOK_ONLY_MESSAGE)
        if dev_authorized:
            # Persist before permitting execution, even if the person turns Dev
            # off after the snapshot. Failure to audit refuses the call.
            audit_dev_event(self.workspace_dir, "call", tool=tool_name, mutating=True, arguments=arguments)
        plan_id = arguments.get("plan_id") if isinstance(arguments, dict) else None
        # A person's standing approval of one recipe: bound to its id and the sha256 of its code as it is on
        # disk now (security/recipe_store.py). Look only and the audit above have already been applied.
        standing = None if plan_id else standing_authorizes(self.workspace_dir, tool_name, arguments)
        if standing is not None:
            RecipeStore(self.workspace_dir).record_standing_use(standing)
            return None
        if mode == "auto":
            if not plan_id:
                return None
            if dev_authorized:
                # Dev permits unplanned calls; a supplied plan must still be
                # approved, unchanged and consumed at most once.
                return self._claim(plan_id, tool_name, arguments)
            try:  # gate off: keep the plan bookkeeping when we can
                return self._claim(plan_id, tool_name, arguments)
            except BridgeError:
                # The approval checks do not block in Auto, but the claim markers still do:
                # an action of this plan runs at most once in every mode (issue #314).
                return self._auto_claim(plan_id, tool_name, arguments)
        if not plan_id:
            raise BridgeError(f"Approval mode is enabled. Mutating tool '{tool_name}' requires a valid 'plan_id' parameter.")
        return self._claim(plan_id, tool_name, arguments)

    def _claim(self, plan_id: Any, tool_name: str, arguments: Any) -> Dict[str, str]:
        validate_plan_id(plan_id)
        with self._plan_lock(plan_id):
            plan = self.load_plan(plan_id)
            if not plan:
                raise BridgeError(f"Plan '{plan_id}' does not exist.")
            try:
                self.verify_approved(plan)
            except ApprovalExpired:
                self._mark_expired(plan)
                raise
            self.verify_binding(plan)
            # Same policy re-check as execute_plan, so a direct call carrying plan_id
            # cannot run an action the workspace policy has since prohibited.
            from .policy import check_actions, load_policy
            check_actions(load_policy(self.workspace_dir), plan.get("actions", []), self.workspace_dir,
                          plan.get("snapshot_id"), dev_mode=self.dev_mode)
            tried: set = set()
            while True:
                action = self._find_open_action(plan, tool_name, arguments, skip=tried)
                if action is None:
                    raise self._no_action_error(plan_id, tool_name)
                action_id = action.get("action_id")
                tried.add(action_id)
                # Before consuming: a changed bound file refuses the call and leaves the action open.
                file_binding.verify_action(tool_name, action.get("arguments"), self.workspace_monitor)
                marker = self._claim_marker(plan_id, action_id)
                marker.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    continue  # consumed earlier; its recorded state is not trusted
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(datetime.now(timezone.utc).isoformat())
                break
            action["state"] = "running"
            action["claimed_at"] = datetime.now(timezone.utc).isoformat()
            self.save_plan(plan)
        return {"plan_id": plan_id, "action_id": action_id}

    def _auto_claim(self, plan_id: Any, tool_name: str, arguments: Any) -> Optional[Dict[str, str]]:
        """Auto mode (timed or configured, not Dev) for a call that carries a plan_id the full
        claim refused. The approval checks are off, but the claim markers are not: a matching
        action is claimed with the same O_EXCL marker, and a call whose every matching action was
        already consumed is refused, whatever the action state on disk says. Returns None when the
        plan does not exist or holds no action for this call (an unplanned call, allowed in Auto)."""
        try:
            validate_plan_id(plan_id)
        except BridgeError:
            return None
        wanted = canonical_arguments(arguments)
        with self._plan_lock(plan_id):
            try:
                plan = self.load_plan(plan_id)
            except BridgeError:
                plan = None
            actions = plan.get("actions") if isinstance(plan, dict) else None
            matching = [a for a in actions if isinstance(a, dict) and a.get("tool") == tool_name
                        and canonical_arguments(a.get("arguments", {})) == wanted] if isinstance(actions, list) else []
            if not matching:
                return None
            for action in matching:
                if action.get("state") not in OPEN_ACTION_STATES:
                    continue
                action_id = action.get("action_id")
                marker = self._claim_marker(plan_id, action_id)
                marker.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    continue  # consumed earlier; its recorded state is not trusted
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(datetime.now(timezone.utc).isoformat())
                action["state"] = "running"
                action["claimed_at"] = datetime.now(timezone.utc).isoformat()
                self.save_plan(plan)
                return {"plan_id": plan_id, "action_id": action_id}
        raise BridgeError(
            f"Plan '{plan_id}' already ran this '{tool_name}' action. An action runs at most once, in every "
            "approval mode. Nothing ran. Draft a new plan for this change."
        )

    def finish_action(self, claim: Optional[Dict[str, str]], ok: bool, error: Optional[str] = None,
                      only_if_running: bool = False) -> Optional[Dict[str, Any]]:
        """Record how a claimed action ended. Never reopens it.

        ``only_if_running`` leaves an action that is no longer 'running' (already closed, or
        abandoned by a person) untouched; used when a late result closes an in-flight action.

        When no action is left open or running, the plan moves to 'executed' (every
        action succeeded) or 'partial' (some failed), unless a person rejected it.
        Expired plans also finish once their running actions settle; unstarted actions stay blocked.
        """
        if not claim:
            return None
        plan_id = claim["plan_id"]
        finished_all = False
        with self._plan_lock(plan_id):
            plan = self.load_plan(plan_id)
            if not plan:
                return None
            for action in plan.get("actions", []):
                if action.get("action_id") == claim["action_id"]:
                    if action.get("state") == "abandoned":
                        continue  # a person gave this action up; a late finish never revives it
                    if only_if_running and action.get("state") != "running":
                        continue
                    action.pop("in_flight_key", None)
                    action["state"] = "executed" if ok else "failed"
                    if not ok and error:
                        action["error"] = str(error)[:500]
            states = [a.get("state") for a in plan.get("actions", [])]
            all_done = all(s in DONE_ACTION_STATES for s in states)
            if plan.get("state") == "expired" and "running" not in states:
                all_done = True
            if all_done and plan.get("state") in ("approved", "expired"):
                if all(s == "executed" for s in states):
                    finished_all = True
                else:
                    plan["state"] = "partial"
                    plan["executed_at"] = datetime.now(timezone.utc).isoformat()
            self.save_plan(plan)
        if finished_all:
            return self.update_plan_state(plan_id, "executed")
        if plan.get("state") == "partial" and all_done:
            try:
                self.record_proof(plan)
            except Exception:
                logger.exception("Failed to write a proof bundle")
        return plan

    # -- in-flight actions: a call that outlived the wait ------------------------------
    #
    # A mutating call can come back as {"status": "running", "request_id": ...} while Revit
    # keeps working. The claim stays consumed (no replay) and the action stays 'running'; the
    # record below ties the request id to the claim, on disk, so a server restart does not
    # lose it. revit_get_result (or revit_job_status for a job) closes it when the final
    # result arrives. A model never names a plan or action id here.

    @property
    def inflight_dir(self) -> Path:
        return self.plans_dir / ".inflight"

    def _inflight_path(self, key: Any) -> Path:
        return safe_child(self.plans_dir, key, ".json", INFLIGHT_KEY_RE,
                          lambda _reason: BridgeError("Invalid request id."), subdir=".inflight")

    def mark_in_flight(self, claim: Optional[Dict[str, str]], key: str, tool: str) -> bool:
        """Record that the claimed action is still running under ``key`` (a request id, or
        ``job_<id>`` for a background job). Returns False when there is nothing to track."""
        if not claim:
            return False
        path = self._inflight_path(key)
        record = {
            "key": key, "plan_id": claim["plan_id"], "action_id": claim["action_id"], "tool": tool,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f)
            replace_with_retry(tmp, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        with self._plan_lock(claim["plan_id"]):
            plan = self.load_plan(claim["plan_id"])
            if plan:
                for action in plan.get("actions", []):
                    if action.get("action_id") == claim["action_id"] and action.get("state") == "running":
                        action["in_flight_key"] = key
                self.save_plan(plan)
        return True

    def in_flight(self, key: Any) -> Optional[Dict[str, Any]]:
        try:
            path = self._inflight_path(key)
        except BridgeError:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) else None

    def in_flight_records(self) -> List[Dict[str, Any]]:
        out = []
        for path in sorted(self.inflight_dir.glob("*.json")) if self.inflight_dir.exists() else []:
            record = self.in_flight(path.stem)
            if record:
                out.append(record)
        return out

    def rekey_in_flight(self, old_key: str, new_key: str) -> bool:
        """Move a record from a job key to the request id Revit is still running it under."""
        record = self.in_flight(old_key)
        if not record:
            return False
        claim = {"plan_id": record["plan_id"], "action_id": record["action_id"]}
        if not self.mark_in_flight(claim, new_key, str(record.get("tool"))):
            return False
        with contextlib.suppress(OSError, BridgeError):
            os.unlink(self._inflight_path(old_key))
        return True

    def settle_in_flight(self, key: Any, ok: bool, error: Optional[str] = None) -> bool:
        """Close the action behind ``key`` with its final outcome. Safe to call twice: only the
        caller that removes the record closes the action. Returns True when it closed one."""
        record = self.in_flight(key)
        if not record:
            return False
        try:
            os.unlink(self._inflight_path(key))
        except FileNotFoundError:
            return False
        except OSError:
            logger.exception("Could not remove the in-flight record %s", key)
            return False
        claim = {"plan_id": record.get("plan_id"), "action_id": record.get("action_id")}
        try:
            validate_plan_id(claim["plan_id"])
            self.finish_action(claim, ok=ok, error=error, only_if_running=True)
        except Exception:
            logger.exception("Could not close in-flight action %s", claim)
            return False
        return True

    def recover_running_actions(self, plan_id: str, reason: str, by: Optional[str] = None,
                                force: bool = False) -> Dict[str, Any]:
        """Human-only: give up every action stuck in 'running' (its process died mid-call).

        The actions become 'abandoned' with a reason and time. They are NEVER run again (the
        claim marker stays, and 'abandoned' is not an open state), so at-most-once holds. An
        approved plan becomes 'partial': its remaining open actions cannot run either, and
        need a new plan that a person approves. Not reachable through any tool call: only
        the command-line tool calls this. Fresh actions (younger than the stale threshold)
        are refused unless ``force``.
        """
        reason = str(reason or "").strip()
        if not reason:
            raise BridgeError("A reason is required to abandon a running action.")
        now = datetime.now(timezone.utc)
        with self._plan_lock(plan_id):
            plan = self.load_plan(plan_id)
            if not plan:
                raise BridgeError(f"Plan '{plan_id}' does not exist.")
            stuck = running_actions(plan, now)
            if not stuck:
                raise BridgeError(f"Plan '{plan_id}' has no action in state 'running'; nothing to recover.")
            if not force and any(not r["stale"] for r in stuck):
                raise BridgeError(
                    f"An action in plan '{plan_id}' started less than {STALE_RUNNING_SECONDS // 60} minutes ago "
                    "and may still be running. Wait, or pass --force if you are sure it is dead."
                )
            ids = {r["action_id"] for r in stuck}
            for action in plan["actions"]:
                if isinstance(action, dict) and action.get("action_id") in ids and action.get("state") == "running":
                    action["state"] = "abandoned"
                    action["abandoned_at"] = now.isoformat()
                    action["abandoned_reason"] = reason[:500]
                    action["abandoned_by"] = str(by) if by else local_user()
                    action["abandoned_via"] = "cli"
            closed = plan.get("state") in ("approved", "expired")
            if closed:
                plan["state"] = "partial"
                plan["executed_at"] = now.isoformat()
            self.save_plan(plan)
            for record in self.in_flight_records():
                if record.get("plan_id") == plan_id and record.get("action_id") in ids:
                    with contextlib.suppress(OSError, BridgeError):
                        os.unlink(self._inflight_path(record.get("key")))
        if closed:
            try:
                self.record_proof(plan)
            except Exception:
                logger.exception("Failed to write proof bundle for plan %s", plan_id)
        return plan

    def mark_action_executed(self, tool_name: str, arguments: Any) -> Optional[Dict[str, Any]]:
        """Claim and complete the matching action in one step (bookkeeping helper).

        Returns the plan, or None when the call carries no plan_id. A call that matches
        no open action leaves the plan unchanged.
        """
        plan_id = arguments.get("plan_id") if isinstance(arguments, dict) else None
        if not plan_id:
            return None
        try:
            claim = self._claim(plan_id, tool_name, arguments)
        except BridgeError:
            try:
                return self.load_plan(plan_id)
            except BridgeError:
                return None
        return self.finish_action(claim, ok=True)

    def _check_rollback_allowed(self, plan: Optional[Dict[str, Any]], plan_id: str) -> Dict[str, Any]:
        """The one place that decides whether a plan may be rolled back right now.

        Mirrors what claim_action requires of an execution, for state 'executed':
        the plan exists, was executed (so it is not pending, rejected, partial or
        already rolled back) and still holds exactly what a person approved. Called
        before the rollback starts and again, under the plan lock, before each inverse
        action is claimed and before the final state is saved. Further gates (plan
        expiry, document binding) belong here.
        """
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        if plan.get("state") != "executed":
            raise ValueError(f"Plan {plan_id} is in state '{plan.get('state')}', cannot rollback. Only executed plans can be rolled back.")
        self._verify_unchanged_since_approval(plan)
        return plan

    def _claim_rollback_action(self, plan_id: str, action_id: Any) -> None:
        """Consume one inverse action BEFORE its write runs (at most once, across processes).

        Under the plan lock: re-checks the plan, then creates a claim marker with O_EXCL
        in ``.rollback_claims`` (separate from the execution claims in ``.claims``). The
        marker stays whatever the write does next, so an interrupted rollback never
        replays an inverse write blindly; a person inspects the model first.
        """
        with self._plan_lock(plan_id):
            self._check_rollback_allowed(self.load_plan(plan_id), plan_id)
            marker = self._claim_marker(plan_id, action_id, subdir=".rollback_claims")
            marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise BridgeError(
                    f"Rollback of action {action_id} in plan {plan_id} was already claimed by an earlier "
                    "rollback; its write may or may not have run. Inspect the model before trying again."
                ) from None
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(datetime.now(timezone.utc).isoformat())

    async def rollback_plan(self, plan_id: str, execute_fn) -> Dict[str, Any]:
        """Roll back an executed plan.

        `execute_fn` is an async callable `(tool_name, arguments) -> dict`; it MUST be
        awaited here rather than merely invoked, otherwise the inverse tool call never
        actually runs (a bare call just constructs and discards a coroutine object).

        Same discipline as execute_plan: the plan must be 'executed' and unchanged since
        approval (_check_rollback_allowed), and every inverse action is claimed under the
        plan lock (_claim_rollback_action) before its write runs. The plan stays
        'executed' for the whole rollback (it is never written as 'approved'), so a crash
        leaves it 'executed'; only the final outcome is saved, and only while the plan is
        still 'executed'.

        Tools without a registered rollback handler are recorded as warnings (not
        errors) so that a mixed plan (some rollback-able, some not) still rolls back
        what it can and reports clearly what was skipped.
        """
        self.refuse_if_look_only()  # rollback is a model write; look only refuses it before anything else
        validate_plan_id(plan_id)
        plan = self._check_rollback_allowed(self.load_plan(plan_id), plan_id)

        errors = []
        warnings = []
        for action in reversed(plan["actions"]):
            tool = action["tool"]
            before = action["diff"]["before"]
            if tool == "revit_set_parameter_value":
                elem_id = action["arguments"].get("element_id")
                param_name = action["arguments"].get("parameter_name")
                old_val = before.get(str(elem_id), {}).get(param_name)
                if old_val is not None:
                    try:
                        self._claim_rollback_action(plan_id, action.get("action_id"))
                        await execute_fn("revit_set_parameter_value", {
                            "element_id": elem_id,
                            "parameter_name": param_name,
                            "value": old_val,
                            "plan_id": plan_id
                        })
                    except Exception as e:
                        errors.append(f"Failed to rollback action {action.get('action_id')}: {e}")
                else:
                    warnings.append(f"Skipped rollback for action {action.get('action_id')}: no before-value recorded")
            else:
                warnings.append(f"No rollback handler for tool '{tool}' (action {action.get('action_id')}) — skipped")

        with self._plan_lock(plan_id):
            plan = self._check_rollback_allowed(self.load_plan(plan_id), plan_id)
            plan["rollback_warnings"] = warnings
            plan["state"] = "partial_rollback" if errors else "rolled_back"
            self.save_plan(plan)
        if errors:
            raise BridgeError(f"Rollback encountered errors: {'; '.join(errors)}")
        return plan
