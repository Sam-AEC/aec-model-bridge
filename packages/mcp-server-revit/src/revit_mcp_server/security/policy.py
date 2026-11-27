"""Optional workspace policy: extra refusals for plans. It never approves or runs anything.

The file is ``<workspace>/policy.yaml`` (or ``policy.yml`` / ``policy.json``), or the file named by
``MCP_REVIT_POLICY_FILE``. It is read each time it is needed, so a change applies to the next
draft and to the next ``execute_plan`` of an already drafted plan. A file that cannot be read or
does not validate refuses every write (fail closed). No file means no policy.

A machine policy file (``MCP_REVIT_MACHINE_POLICY_FILE``, else a platform default set by an
administrator) is merged with it and the stricter rule wins: blocked lists are joined, allowed lists
are intersected, number limits take the smaller value, and a tier that either file turns off is off.
A workspace policy can therefore only tighten the machine policy. Explicit Dev mode lifts the limits
of both files (see ``check_actions``); every bypass is audited.
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..errors import BridgeError
from . import plan_review
from .tiers import TIERS, resolve_tier

POLICY_ENV = "MCP_REVIT_POLICY_FILE"
DEFAULT_NAMES = ("policy.yaml", "policy.yml", "policy.json")
MACHINE_POLICY_ENV = "MCP_REVIT_MACHINE_POLICY_FILE"
TIER_RULES = ("allowed_tiers", "blocked_tiers")
LIST_RULES = ("blocked_tools", "allowed_tools", "allowed_categories", "blocked_parameters") + TIER_RULES
UNION_RULES = ("blocked_tools", "blocked_parameters", "blocked_tiers")
INTERSECT_RULES = ("allowed_tools", "allowed_categories", "allowed_tiers")
INT_RULES = ("max_elements_per_plan", "max_actions_per_plan")
BOOL_RULES = ("require_second_approver",)
MAX_FILE_BYTES = 256 * 1024


class PolicyError(BridgeError):
    """The policy file is invalid, or a plan breaks one of its rules."""


@dataclass(frozen=True)
class Layer:
    """One policy file that was read: ``level`` is "machine" or "workspace"."""
    level: str
    source: str
    hash: str
    rules: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Policy:
    rules: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    hash: Optional[str] = None
    layers: tuple = ()

    @property
    def active(self) -> bool:
        return self.source is not None

    def effective(self) -> Dict[str, Any]:
        return {"active": self.active, "source": self.source, "policy_hash": self.hash,
                "rules": dict(self.rules),
                "files": [{"level": lay.level, "path": lay.source, "hash": lay.hash} for lay in self.layers],
                "tiers_off": {t: src for t, src in tiers_off(self).items()}}


def _norm_category(value: str) -> str:
    v = value.strip().lower()
    return v[4:] if v.startswith("ost_") else v


def _validate(data: Any, where: str) -> Dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PolicyError(f"Invalid policy file {where}: the top level must be a mapping. All writes are refused until it is fixed.")
    unknown = sorted(str(k) for k in data if k not in LIST_RULES + INT_RULES + BOOL_RULES)
    if unknown:
        raise PolicyError(f"Invalid policy file {where}: unknown key(s) {', '.join(unknown)}. All writes are refused until it is fixed.")
    rules: Dict[str, Any] = {}
    for key in LIST_RULES:
        if key in data:
            v = data[key]
            if v is None:
                v = []
            if not isinstance(v, list) or any(not isinstance(i, str) or not i.strip() for i in v):
                raise PolicyError(f"Invalid policy file {where}: '{key}' must be a list of non-empty strings. All writes are refused until it is fixed.")
            rules[key] = sorted({i.strip().lower() if key in TIER_RULES else i.strip() for i in v})
            bad = [i for i in rules[key] if key in TIER_RULES and i not in TIERS]
            if bad:
                raise PolicyError(f"Invalid policy file {where}: '{key}' has unknown tier(s) {', '.join(bad)}; "
                                  f"use {', '.join(TIERS)}. All writes are refused until it is fixed.")
    for key in INT_RULES:
        if key in data and data[key] is not None:
            v = data[key]
            if type(v) is not int or v < 0:
                raise PolicyError(f"Invalid policy file {where}: '{key}' must be a whole number of 0 or more. All writes are refused until it is fixed.")
            rules[key] = v
    for key in BOOL_RULES:
        if key in data and data[key] is not None:
            if type(data[key]) is not bool:
                raise PolicyError(f"Invalid policy file {where}: '{key}' must be true or false. All writes are refused until it is fixed.")
            rules[key] = data[key]
    return rules


def _find_file(workspace_dir: Optional[Path]) -> Optional[Path]:
    env = os.environ.get(POLICY_ENV)
    if env is not None and env.strip():
        return Path(env.strip())
    if workspace_dir:
        for name in DEFAULT_NAMES:
            p = Path(workspace_dir) / name
            if p.exists():
                return p
    return None


def default_machine_path(windows: bool, programdata: Optional[str]) -> Optional[str]:
    """Platform default of the machine policy file. The Windows path is UNVERIFIED on a live machine."""
    if windows:
        return ntpath.join(programdata, "AECModelBridge", "policy.yaml") if programdata else None
    return "/etc/aec-model-bridge/policy.yaml"


def _platform_default() -> Optional[str]:
    return default_machine_path(os.name == "nt", os.environ.get("PROGRAMDATA"))


def machine_policy_path() -> Optional[Path]:
    """The machine policy file: the env override, else the platform default.

    A path named by the env override is returned even when the file is missing, so reading it
    refuses every write (fail closed: a typo or a deleted file must not switch the policy off).
    A missing file at the platform default means no machine policy."""
    env = os.environ.get(MACHINE_POLICY_ENV)
    if env is not None and env.strip():
        return Path(env.strip())
    default = _platform_default()
    if default is None:
        return None
    path = Path(default)
    try:
        return path if path.exists() else None
    except OSError:
        return path  # present but not even testable: reading it fails closed


def _read_rules(path: Path) -> tuple:
    where = f"'{path}'"
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise PolicyError(f"Invalid policy file {where}: larger than {MAX_FILE_BYTES} bytes. All writes are refused until it is fixed.")
        text = path.read_text(encoding="utf-8-sig")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            import yaml
            data = yaml.safe_load(text)
    except PolicyError:
        raise
    except Exception as e:  # noqa: BLE001 - any read or parse failure refuses writes
        raise PolicyError(f"Invalid policy file {where}: {str(e)[:200]}. All writes are refused until it is fixed.") from e
    rules = _validate(data, where)
    return rules, _hash_rules(rules)


def _hash_rules(rules: Dict[str, Any]) -> str:
    blob = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def merge_rules(layers: List[Layer]) -> Dict[str, Any]:
    """Stricter wins. Blocked lists join, allowed lists intersect, limits take the minimum."""
    merged: Dict[str, Any] = {}
    for key in UNION_RULES:
        vals = [lay.rules[key] for lay in layers if key in lay.rules]
        if vals:
            merged[key] = sorted(set().union(*vals))
    for key in INTERSECT_RULES:
        vals = [lay.rules[key] for lay in layers if key in lay.rules]
        if vals:
            norm = (lambda v: {_norm_category(c) for c in v}) if key == "allowed_categories" else set
            out = norm(vals[0])
            for v in vals[1:]:
                out &= norm(v)
            merged[key] = sorted(out)
    for key in INT_RULES:
        vals = [lay.rules[key] for lay in layers if key in lay.rules]
        if vals:
            merged[key] = min(vals)
    for key in BOOL_RULES:
        vals = [lay.rules[key] for lay in layers if key in lay.rules]
        if vals:
            merged[key] = any(vals)  # on in either file means on
    return merged


def load_policy(workspace_dir: Optional[Path]) -> Policy:
    """The effective policy: machine file merged with the workspace file, stricter wins.

    Raises PolicyError for a file that is named but unusable."""
    layers: List[Layer] = []
    machine = machine_policy_path()
    if machine is not None:
        rules, h = _read_rules(machine)
        layers.append(Layer("machine", str(machine), h, rules))
    path = _find_file(workspace_dir)
    if path is not None:
        rules, h = _read_rules(path)
        layers.append(Layer("workspace", str(path), h, rules))
    if not layers:
        return Policy()
    if len(layers) == 1:
        only = layers[0]
        return Policy(rules=dict(only.rules), source=only.source, hash=only.hash, layers=tuple(layers))
    merged = merge_rules(layers)
    return Policy(rules=merged, source="; ".join(lay.source for lay in layers), hash=_hash_rules(merged),
                  layers=tuple(layers))


def second_approver_required(policy: Policy) -> bool:
    """True when the policy asks for a person other than the plan's requester to approve (#203)."""
    return policy.rules.get("require_second_approver") is True


def tiers_off(policy: Policy) -> Dict[str, str]:
    """{tier: path of the first policy file that turns it off}. Empty when every tier is on."""
    off: Dict[str, str] = {}
    for layer in policy.layers:
        r = layer.rules
        if "allowed_tiers" in r:
            for t in TIERS:
                if t not in r["allowed_tiers"]:
                    off.setdefault(t, layer.source)
        for t in r.get("blocked_tiers", []):
            off.setdefault(t, layer.source)
    return off


def tier_refusal(policy: Policy, name: str, tier: str) -> Optional[str]:
    """The plain refusal for a tool whose tier is off, naming the policy file; else None."""
    source = tiers_off(policy).get(tier)
    if source is None:
        return None
    level = next((lay.level for lay in policy.layers if lay.source == source), "policy")
    # Error text and audit lines hide absolute paths, so the file is named by level and file name;
    # aec-model-bridge-doctor prints the full path.
    return (f"Policy refused '{name}': the {tier} tier is off in the {level} policy file "
            f"({Path(source).name}). Ask the person who manages that file to change it; "
            "aec-model-bridge-doctor shows where it is.")


def check_actions(policy: Policy, actions: List[Dict[str, Any]], workspace_dir: Optional[Path] = None,
                  snapshot_id: Optional[str] = None, dev_mode: bool = False) -> None:
    """Raise PolicyError naming the rule that a list of actions ({tool, arguments, diff?}) breaks.

    With ``dev_mode`` (explicit Dev mode, decided by the caller from the signed record) the rule is
    not enforced: the bypass is audited with the rule text first, and the call proceeds.
    """
    try:
        _check_actions(policy, actions, workspace_dir, snapshot_id)
    except PolicyError as e:
        if not dev_mode or workspace_dir is None:
            raise
        from .dev_mode import audit_dev_event
        audit_dev_event(workspace_dir, "policy_bypassed", rule=str(e), policy_hash=policy.hash,
                        tools=[a.get("tool") for a in actions if isinstance(a, dict)])


def _check_actions(policy: Policy, actions: List[Dict[str, Any]], workspace_dir: Optional[Path] = None,
                   snapshot_id: Optional[str] = None) -> None:
    if not policy.active or not policy.rules:
        return
    r = policy.rules
    shaped = {"actions": [a for a in actions if isinstance(a, dict)], "snapshot_id": snapshot_id}
    index = plan_review.snapshot_index(workspace_dir, snapshot_id)
    radius = plan_review.blast_radius(shaped, index)
    blocked = set(r.get("blocked_tools", []))
    allowed = set(r.get("allowed_tools", []))
    blocked_params = {p.lower() for p in r.get("blocked_parameters", [])}
    for i, action in enumerate(shaped["actions"], 1):
        tool = action.get("tool")
        if tiers_off(policy) and isinstance(tool, str):
            tier = resolve_tier(tool)
            msg = tier_refusal(policy, tool, tier) if tier else None
            if msg:
                raise PolicyError(f"Policy refused action {i}: {msg}")
        if tool in blocked:
            raise PolicyError(f"Policy refused action {i}: tool '{tool}' is in blocked_tools.")
        if "allowed_tools" in r and tool not in allowed:
            raise PolicyError(f"Policy refused action {i}: tool '{tool}' is not in allowed_tools.")
        args = plan_review.action_args(action)
        named = set()
        if isinstance(args.get("parameter_name"), str):
            named.add(args["parameter_name"])
        for key in ("parameters", "params", "values"):
            if isinstance(args.get(key), dict):
                named.update(str(k) for k in args[key])
        for name in sorted(named):
            if name.lower() in blocked_params:
                raise PolicyError(f"Policy refused action {i}: parameter '{name}' is in blocked_parameters.")
    if "allowed_categories" in r:
        ok = {_norm_category(c) for c in r["allowed_categories"]}
        for cat in radius["categories"]:
            if cat == plan_review.UNKNOWN:
                raise PolicyError("Policy refused the plan: allowed_categories is set but the category of some "
                                  "elements is unknown, so it cannot be checked. Name the category in the "
                                  "action arguments or draft from a snapshot that lists it.")
            if _norm_category(cat) not in ok:
                raise PolicyError(f"Policy refused the plan: category '{cat}' is not in allowed_categories.")
    limit = r.get("max_elements_per_plan")
    if limit is not None and radius["element_count"] > limit:
        raise PolicyError(f"Policy refused the plan: it touches {radius['element_count']} elements, "
                          f"more than max_elements_per_plan ({limit}).")
    limit = r.get("max_actions_per_plan")
    if limit is not None and radius["action_count"] > limit:
        raise PolicyError(f"Policy refused the plan: it has {radius['action_count']} actions, "
                          f"more than max_actions_per_plan ({limit}).")
    if "max_elements_per_plan" in r and radius["unidentified_actions"]:
        raise PolicyError("Policy refused the plan: max_elements_per_plan is set but some actions name no "
                          "element, so the number of elements cannot be checked.")


def off_tiers_for_listing(workspace_dir: Optional[Path], dev_mode: bool = False) -> set:
    """Tiers to hide from tools/list now. An unusable policy file hides everything but reads.
    Dev mode lifts valid tier limits, but not an unusable file (fail closed)."""
    try:
        policy = load_policy(workspace_dir)
    except PolicyError:
        return {"write", "script", "export"}
    return set() if dev_mode else set(tiers_off(policy))


def name_in_off_tier(name: str, tool: Any, provider_id: str, off: set) -> bool:
    """True when the tool's tier is in ``off``. Control tools are never in an off tier."""
    from .tiers import CONTROL_TOOLS, tier_of
    return name not in CONTROL_TOOLS and tier_of(name, tool, provider_id) in off


def tool_refusal(workspace_dir: Optional[Path], name: str, tool: Any, provider_id: str = "",
                 dev_mode: bool = False) -> Optional[str]:
    """Plain refusal when the tool's tier is off in the machine or workspace policy, else None.

    Control tools (approve, reject, roll back, list plans) are never refused. Under Dev mode the
    refusal is audited with the rule it bypasses and None is returned."""
    from .tiers import CONTROL_TOOLS, tier_of
    if name in CONTROL_TOOLS:
        return None
    tier = tier_of(name, tool, provider_id)
    try:
        policy = load_policy(workspace_dir)
    except PolicyError as e:
        return None if tier == "read" else str(e)
    msg = tier_refusal(policy, name, tier)
    if msg and dev_mode and workspace_dir is not None:
        from .dev_mode import audit_dev_event
        audit_dev_event(workspace_dir, "policy_bypassed", rule=msg, tier=tier, tool=name, policy_hash=policy.hash)
        return None
    return msg
