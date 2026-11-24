"""Optional workspace policy: extra refusals for plans. It never approves or runs anything.

The file is ``<workspace>/policy.yaml`` (or ``policy.yml`` / ``policy.json``), or the file named by
``MCP_REVIT_POLICY_FILE``. It is read each time it is needed, so a change applies to the next
draft and to the next ``execute_plan`` of an already drafted plan. A file that cannot be read or
does not validate refuses every write (fail closed). No file means no policy.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..errors import BridgeError
from . import plan_review

POLICY_ENV = "MCP_REVIT_POLICY_FILE"
DEFAULT_NAMES = ("policy.yaml", "policy.yml", "policy.json")
LIST_RULES = ("blocked_tools", "allowed_tools", "allowed_categories", "blocked_parameters")
INT_RULES = ("max_elements_per_plan", "max_actions_per_plan")
MAX_FILE_BYTES = 256 * 1024


class PolicyError(BridgeError):
    """The policy file is invalid, or a plan breaks one of its rules."""


@dataclass(frozen=True)
class Policy:
    rules: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    hash: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.source is not None

    def effective(self) -> Dict[str, Any]:
        return {"active": self.active, "source": self.source, "policy_hash": self.hash,
                "rules": dict(self.rules)}


def _norm_category(value: str) -> str:
    v = value.strip().lower()
    return v[4:] if v.startswith("ost_") else v


def _validate(data: Any, where: str) -> Dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PolicyError(f"Invalid policy file {where}: the top level must be a mapping. All writes are refused until it is fixed.")
    unknown = sorted(str(k) for k in data if k not in LIST_RULES + INT_RULES)
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
            rules[key] = sorted({i.strip() for i in v})
    for key in INT_RULES:
        if key in data and data[key] is not None:
            v = data[key]
            if type(v) is not int or v < 0:
                raise PolicyError(f"Invalid policy file {where}: '{key}' must be a whole number of 0 or more. All writes are refused until it is fixed.")
            rules[key] = v
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


def load_policy(workspace_dir: Optional[Path]) -> Policy:
    """The effective policy. Raises PolicyError for a file that is named but unusable."""
    path = _find_file(workspace_dir)
    if path is None:
        return Policy()
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
    blob = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return Policy(rules=rules, source=str(path), hash="sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest())


def check_actions(policy: Policy, actions: List[Dict[str, Any]], workspace_dir: Optional[Path] = None,
                  snapshot_id: Optional[str] = None) -> None:
    """Raise PolicyError naming the rule that a list of actions ({tool, arguments, diff?}) breaks."""
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
