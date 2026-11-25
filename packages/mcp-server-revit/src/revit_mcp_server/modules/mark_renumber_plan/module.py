"""
mark_renumber_plan module - read-only mark/number findings and a drafted renumbering plan.

Commands:
  analyze    - findings (duplicate marks, empty marks, gaps, out-of-order sequences) and a
               proposed mapping for doors, rooms and windows. Read-only.
  draft_plan - turns the proposed mapping into ONE `plan_actions`-ready action list of
               `revit_set_parameter_value` calls. Read-only: nothing is written here; the
               list goes through plan_actions, human approval and execute_plan.

Rules come from conventions/mark_rules.json. A file named mark_renumber_rules.json in the
workspace root overrides it per category (only the keys it names).
  doors   room_number_letter: To room number + letter (101A, 101B). A door with no To room
          uses its From room (exterior doors). A door with no usable room is reported and
          is not numbered.
  rooms   level_sequence: level prefix + sequence, per level, sorted by location.
  windows same_as_rooms: the rooms rule, applied to the window Mark, unless configured.

Swaps and chains: an element whose new value is another changing element's current value is
written to a temporary unique value first, then to its final value (see _order_changes).
The draft is refused if the final numbering of a whole category would hold a duplicate, with
elements outside the change set counted.

UNVERIFIED against live Revit: that revit_set_parameter_value writes Mark and room Number
on these categories, and that the snapshot door From/To Room keys match the add-in output.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FROM_KEYS = ("From Room", "FromRoom", "From Room Number")
TO_KEYS = ("To Room", "ToRoom", "To Room Number")


def _pv(el: Dict[str, Any], name: str) -> Any:
    p = (el.get("params") or {}).get(name)
    return p.get("v") if isinstance(p, dict) else p


def _txt(v: Any) -> str:
    if v is None or isinstance(v, (dict, list, tuple)):
        return ""
    return str(v).strip()


def _room_ref(door: Dict[str, Any], keys: Tuple[str, ...]) -> Tuple[bool, str]:
    params = door.get("params") or {}
    for k in keys:
        if k in params:
            v = _pv(door, k)
            if isinstance(v, dict):
                v = v.get("uid") or v.get("number")
            return True, _txt(v)
    return False, ""


CATEGORY_IDS = {"doors": "OST_Doors", "rooms": "OST_Rooms", "windows": "OST_Windows"}
DEFAULT_RULES = Path(__file__).parent / "conventions" / "mark_rules.json"
WORKSPACE_RULES = "mark_renumber_rules.json"
SCHEMES = {"doors": {"room_number_letter"}, "rooms": {"level_sequence"},
           "windows": {"same_as_rooms", "level_sequence"}}
UNVERIFIED = ("UNVERIFIED against live Revit: the parameter writes in this draft have not been "
              "checked in a running Revit.")


MAX_SEQUENCE_SLACK = 1000  # sequence values beyond group size + this are out of range
MAX_GAPS_LISTED = 50  # gap marks listed per group; missing_count gives the full number


def _letters(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    s = ""
    while index > 0:
        index, r = divmod(index - 1, 26)
        s = chr(65 + r) + s
    return s


def _letter_index(text: str) -> int:
    n = 0
    for ch in text:
        n = n * 26 + ord(ch) - 64
    return n


def _load_rules(workspace: Any) -> Dict[str, Dict[str, Any]]:
    rules = json.loads(DEFAULT_RULES.read_text(encoding="utf-8"))
    path = None
    if workspace is not None and getattr(workspace, "allowed_directories", None):
        path = Path(workspace.allowed_directories[0]) / WORKSPACE_RULES
    if path is not None and path.is_file():
        try:
            override = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"{WORKSPACE_RULES} is not valid JSON: {exc}")
        if not isinstance(override, dict):
            raise ValueError(f"{WORKSPACE_RULES} must be a JSON object keyed by category.")
        for cat, vals in override.items():
            if cat not in CATEGORY_IDS or not isinstance(vals, dict):
                raise ValueError(f"{WORKSPACE_RULES}: '{cat}' is not a rule for doors, rooms or windows.")
            rules[cat].update(vals)
    for cat, rule in rules.items():
        if rule.get("scheme") not in SCHEMES[cat]:
            raise ValueError(f"Rule for {cat} has unknown scheme '{rule.get('scheme')}'. "
                             f"Allowed: {', '.join(sorted(SCHEMES[cat]))}.")
        if not _txt(rule.get("parameter")):
            raise ValueError(f"Rule for {cat} needs a parameter name.")
    if rules["windows"]["scheme"] == "same_as_rooms":
        merged = dict(rules["rooms"])
        merged.update({k: v for k, v in rules["windows"].items() if k != "scheme"})
        merged["scheme"] = "level_sequence"
        rules["windows"] = merged
    for cat in ("rooms", "windows"):
        r = rules[cat]
        for key, lo in (("start", 0), ("step", 1), ("digits", 1)):
            if not isinstance(r.get(key), int) or isinstance(r.get(key), bool) or r[key] < lo:
                raise ValueError(f"Rule for {cat}: '{key}' must be a whole number of at least {lo}.")
        if r.get("sort") not in ("location", "element_id"):
            raise ValueError(f"Rule for {cat}: 'sort' must be 'location' or 'element_id'.")
    return rules


def _location_key(el: Dict[str, Any]) -> Tuple[float, float, int]:
    xyz = ((el.get("location") or {}).get("xyz")) or [0.0, 0.0, 0.0]
    return (float(xyz[0]), float(xyz[1]), el.get("element_id") or 0)


def _has_location(el: Dict[str, Any]) -> bool:
    xyz = (el.get("location") or {}).get("xyz")
    return isinstance(xyz, (list, tuple)) and len(xyz) >= 2


def _label(el: Dict[str, Any]) -> str:
    return str(el.get("type_name") or el.get("category") or "")


def _level_prefix(level: Optional[Dict[str, Any]], rule: Dict[str, Any]) -> Optional[str]:
    if level is None:
        return None
    name = str(level.get("type_name") or level.get("name") or "")
    mapping = rule.get("level_prefix_map") or {}
    if name in mapping:
        return str(mapping[name])
    m = re.search(r"-?\d+", name)
    return m.group(0) if m else None


class MarkRenumberPlanModule:

    # ------------------------------------------------------------------ commands

    def analyze(self, snapshot_id: str = "", categories: Optional[List[str]] = None,
                workspace: Any = None, **_) -> Dict[str, Any]:
        cats = self._cats(categories)
        elements, partial = self._get_data(snapshot_id, workspace)
        rules = _load_rules(workspace)
        built = self._build(elements, cats, rules, None)
        findings = [f for c in cats for f in built[c]["findings"]]
        changes = [ch for c in cats for ch in built[c]["changes"]]
        unnumbered = [u for c in cats for u in built[c]["unnumbered"]]
        return {
            "read_only": True,
            "snapshot_id": snapshot_id or "(mock)",
            "categories": cats,
            "rules": {c: rules[c] for c in cats},
            "counts": {c: built[c]["total"] for c in cats},
            "finding_count": len(findings),
            "findings": findings,
            "proposed_mapping": changes,
            "not_numbered": unnumbered,
            **({"warning": f"{partial} Findings may be incomplete and draft_plan refuses until a full snapshot is taken."}
               if partial else {}),
            "summary": (f"{len(findings)} finding(s), {len(changes)} proposed change(s), "
                        f"{len(unnumbered)} element(s) not numbered. Nothing was changed; "
                        "call draft_plan to get a plan for approval."),
        }

    def draft_plan(self, snapshot_id: str = "", categories: Optional[List[str]] = None,
                   only_unique_ids: Optional[List[str]] = None, workspace: Any = None,
                   **_) -> Dict[str, Any]:
        cats = self._cats(categories)
        elements, partial = self._get_data(snapshot_id, workspace)
        if partial:
            raise ValueError(
                f"Plan refused: {partial} Marks outside the capture cannot be checked for duplicates, "
                "so nothing was drafted. Take a full snapshot and ask again.")
        rules = _load_rules(workspace)
        only = set(only_unique_ids) if only_unique_ids else None
        built = self._build(elements, cats, rules, only)

        problems = []
        for c in cats:
            for mark, uids in sorted(built[c]["final_duplicates"].items()):
                problems.append(f"{c}: the mark '{mark}' would be used by {len(uids)} elements ({', '.join(uids)})")
        if problems:
            raise ValueError(
                "Plan refused: the final numbering would still contain duplicates, so nothing was "
                "drafted. " + "; ".join(problems) + ". Fix the duplicates (for example renumber "
                "those elements too) and ask again.")

        actions: List[Dict[str, Any]] = []
        phases: List[Dict[str, Any]] = []
        for c in cats:
            changes = built[c]["changes"]
            if only is not None:
                changes = [ch for ch in changes if ch["unique_id"] in only]
            reserved = set(built[c]["final_marks"]) | {ch["old_mark"] for ch in changes if ch["old_mark"]}
            for phase, items in _order_changes(changes, reserved):
                phases.append({"category": c, "phase": phase, "count": len(items)})
                for it in items:
                    if it["element_id"] is None:
                        raise ValueError(f"Plan refused: element {it['unique_id']} has no element_id.")
                    actions.append({
                        "tool": "revit_set_parameter_value",
                        "arguments": {"element_id": it["element_id"],
                                      "parameter_name": it["parameter"], "value": it["value"]},
                    })
        n_changes = sum(p["count"] for p in phases if p["phase"] == "final")
        return {
            "plan_type": "action_plan_draft",
            "tool": "mark_renumber_plan_draft_plan",
            "arguments": {"snapshot_id": snapshot_id, "categories": cats},
            "preview": {"changed_elements": n_changes, "phases": phases,
                        "note": ("Elements whose new value is another changing element's current "
                                 "value are first set to a temporary value, then to the final value.")},
            "requires_approval": True,
            "actions": actions,
            "skipped": [u for c in cats for u in built[c]["unnumbered"]],
            "snapshot_id": snapshot_id,
            "next_step": ("Pass actions and snapshot_id to plan_actions. A person must approve the "
                          "plan before execute_plan writes anything."),
            "unverified": UNVERIFIED,
            "read_only": True,
        }

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _cats(categories: Optional[List[str]]) -> List[str]:
        if not categories:
            return ["doors", "rooms", "windows"]
        bad = [c for c in categories if c not in CATEGORY_IDS]
        if bad:
            raise ValueError(f"Unknown categories {bad}. Use doors, rooms or windows.")
        return [c for c in ("doors", "rooms", "windows") if c in categories]

    def _build(self, elements: List[Dict[str, Any]], cats: List[str],
               rules: Dict[str, Dict[str, Any]], only: Optional[set]) -> Dict[str, Dict[str, Any]]:
        # The add-in writes level_uid as the level's element id; mock snapshots use the UniqueId.
        levels: Dict[Any, Dict[str, Any]] = {}
        for e in elements:
            if e.get("category") == "OST_Levels":
                levels[e.get("uid")] = e
                if e.get("element_id") is not None:
                    levels[str(e.get("element_id"))] = e
        all_rooms = sorted((e for e in elements if e.get("category") == "OST_Rooms"),
                           key=lambda e: e.get("element_id") or 0)
        out: Dict[str, Dict[str, Any]] = {}
        room_final: Dict[str, str] = {}  # room uid -> number after the (filtered) room changes
        for r in all_rooms:
            room_final[r.get("uid")] = _txt(_pv(r, "Number"))

        for cat in ("rooms", "windows", "doors"):
            if cat not in cats:
                continue
            rule = rules[cat]
            param = rule["parameter"]
            els = sorted((e for e in elements if e.get("category") == CATEGORY_IDS[cat]),
                         key=lambda e: e.get("element_id") or 0)
            if cat == "doors":
                groups, unnumbered = self._door_groups(els, all_rooms, room_final, rule)
            else:
                groups, unnumbered = self._level_groups(els, levels, rule, cat)
            findings = self._findings(cat, els, groups, param, rule)
            changes: List[Dict[str, Any]] = []
            for gkey, (prefix, members) in groups.items():
                for i, el in enumerate(members):
                    new = self._mark_for(cat, rule, prefix, i)
                    old = _txt(_pv(el, param))
                    if new != old:
                        changes.append({"unique_id": el.get("uid"), "element_id": el.get("element_id"),
                                        "label": _label(el), "group": gkey, "parameter": param,
                                        "old_mark": old, "new_mark": new})
            if only is not None:
                changes = [c for c in changes if c["unique_id"] in only]
            new_by_uid = {c["unique_id"]: c["new_mark"] for c in changes}
            final: Dict[str, List[str]] = {}
            for el in els:
                m = new_by_uid.get(el.get("uid"), _txt(_pv(el, param)))
                if m:
                    final.setdefault(m, []).append(str(el.get("uid")))
            if cat == "rooms":
                for r in els:
                    room_final[r.get("uid")] = new_by_uid.get(r.get("uid"), _txt(_pv(r, param)))
            out[cat] = {
                "total": len(els), "findings": findings, "changes": changes,
                "unnumbered": unnumbered, "final_marks": set(final),
                "final_duplicates": {m: u for m, u in final.items() if len(u) > 1},
            }
        return out

    @staticmethod
    def _mark_for(cat: str, rule: Dict[str, Any], prefix: str, i: int) -> str:
        if cat == "doors":
            return f"{prefix}{_letters(i + 1)}"
        return f"{prefix}{rule['start'] + i * rule['step']:0{rule['digits']}d}"

    def _level_groups(self, els, levels, rule, cat):
        groups: Dict[str, Tuple[str, List[Dict[str, Any]]]] = {}
        unnumbered: List[Dict[str, Any]] = []
        by_level: Dict[str, List[Dict[str, Any]]] = {}
        for el in els:
            lv = levels.get(el.get("level_uid"))
            if lv is None and el.get("level_uid") is not None:
                lv = levels.get(str(el.get("level_uid")))
            prefix = _level_prefix(lv, rule)
            if prefix is None:
                reason = ("no level" if lv is None else
                          f"level '{lv.get('type_name') or lv.get('name')}' has no number (add level_prefix_map to the rules)")
                unnumbered.append(self._skip(el, reason))
            elif rule["sort"] == "location" and not _has_location(el):
                unnumbered.append(self._skip(el, "no location, so it cannot be sorted"))
            else:
                by_level.setdefault(str(lv.get("uid") or lv.get("element_id")), []).append(el)
        level_by_key = {str(v.get("uid") or v.get("element_id")): v for v in levels.values()}
        for uid, members in by_level.items():
            members.sort(key=_location_key if rule["sort"] == "location" else (lambda e: e.get("element_id") or 0))
            lv = level_by_key[uid]
            groups[str(lv.get("type_name") or lv.get("name") or uid)] = (_level_prefix(lv, rule), members)
        return groups, unnumbered

    def _door_groups(self, doors, rooms, room_final, rule):
        by_uid = {r.get("uid"): r for r in rooms}
        by_number: Dict[str, List[Dict[str, Any]]] = {}
        for r in rooms:
            n = _txt(_pv(r, "Number"))
            if n:
                by_number.setdefault(n, []).append(r)

        def number_of(ref: str) -> Optional[str]:
            room = by_uid.get(ref)
            if room is None:
                m = by_number.get(ref, [])
                room = m[0] if len(m) == 1 else None
            if room is None:
                return None
            return room_final.get(room.get("uid")) or None

        groups: Dict[str, Tuple[str, List[Dict[str, Any]]]] = {}
        unnumbered: List[Dict[str, Any]] = []
        for d in doors:
            _, frm = _room_ref(d, FROM_KEYS)
            _, to = _room_ref(d, TO_KEYS)
            if to:
                ref, side = to, "To"
            elif frm and rule.get("exterior_uses_from_room", True):
                ref, side = frm, "From"
            else:
                unnumbered.append(self._skip(d, "door has no room"))
                continue
            num = number_of(ref)
            if num is None:
                unnumbered.append(self._skip(d, f"{side} room '{ref}' was not found or has no number"))
                continue
            groups.setdefault(num, (num, []))[1].append(d)
        for _, members in groups.values():
            members.sort(key=lambda e: e.get("element_id") or 0)
        return groups, unnumbered

    @staticmethod
    def _skip(el: Dict[str, Any], reason: str) -> Dict[str, Any]:
        return {"unique_id": el.get("uid"), "element_id": el.get("element_id"),
                "label": _label(el), "reason": reason}

    def _findings(self, cat, els, groups, param, rule) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        def add(kind: str, msg: str, items: List[Dict[str, Any]], **extra: Any) -> None:
            if items:
                findings.append({"category": cat, "check_id": kind, "message": msg,
                                 "unique_ids": [i.get("uid") for i in items], **extra})

        add("empty_mark", f"{cat[:-1].capitalize()} has an empty {param}.",
            [e for e in els if not _txt(_pv(e, param))])
        marks: Dict[str, List[Dict[str, Any]]] = {}
        for e in els:
            m = _txt(_pv(e, param))
            if m:
                marks.setdefault(m, []).append(e)
        for m, group in sorted(marks.items()):
            if len(group) > 1:
                add("duplicate_mark", f"{len(group)} {cat} share the {param} '{m}'.", group, mark=m)

        for gkey, (prefix, members) in sorted(groups.items()):
            seqs: List[Tuple[Dict[str, Any], int]] = []
            for e in members:
                m = _txt(_pv(e, param))
                if not m.startswith(prefix):
                    continue
                rest = m[len(prefix):]
                if cat == "doors" and re.fullmatch(r"[A-Z]+", rest):
                    seqs.append((e, _letter_index(rest)))
                elif cat != "doors" and re.fullmatch(r"\d+", rest):
                    start, step = rule["start"], rule["step"]
                    v = int(rest)
                    if v >= start and (v - start) % step == 0:
                        seqs.append((e, (v - start) // step + 1))
            # A mark far beyond the group size (for example 101ENTRY read as letters) is reported,
            # not used for gaps, so one odd mark cannot make the gap list huge.
            limit = len(members) + MAX_SEQUENCE_SLACK
            far = [(e, q) for e, q in seqs if q > limit]
            if far:
                add("out_of_range", f"Marks in {gkey} are far outside the sequence for {len(members)} element(s).",
                    [e for e, _ in far], group=gkey)
            seqs = [(e, q) for e, q in seqs if q <= limit]
            have = {q for _, q in seqs}
            if have:
                missing = [q for q in range(1, max(have) + 1) if q not in have]
                if missing:
                    findings.append({
                        "category": cat, "check_id": "gap", "group": gkey,
                        "message": f"Sequence in {gkey} skips {len(missing)} value(s).",
                        "missing": [self._mark_for(cat, rule, prefix, q - 1) for q in missing[:MAX_GAPS_LISTED]],
                        "missing_count": len(missing),
                        "unique_ids": []})
            order = [s for _, s in seqs]
            if order != sorted(order):
                add("out_of_order", f"Marks in {gkey} do not follow the sort order.",
                    [e for e, _ in seqs], group=gkey)
        return findings

    def _get_data(self, snapshot_id: str, workspace: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Elements and, for a partial capture, a sentence saying so (else None)."""
        if not snapshot_id:
            from revit_mcp_server.semantic.engine import generate_mock_snapshot, require_snapshot_or_mock
            require_snapshot_or_mock(snapshot_id, "mark_renumber_plan")
            snap = generate_mock_snapshot()
            return [el.model_dump(by_alias=True) for el in snap.elements], None
        from revit_mcp_server.security.safe_paths import snapshot_file

        path = snapshot_file(workspace.allowed_directories[0] / "snapshots", snapshot_id)
        if not path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found.")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        counts = data.get("counts") or {}
        partial = None
        if isinstance(counts, dict) and (counts.get("truncated") or counts.get("params")):
            partial = f"Snapshot '{snapshot_id}' is a partial capture (truncated)."
        return data.get("elements", []), partial


def _order_changes(changes: List[Dict[str, Any]], reserved: set) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Order writes so no value is ever held by two elements at once.

    An element is entangled when its new value is the current value of another changing
    element (a swap or a chain). Entangled elements go to a temporary unique value first;
    the others then move to their final value; the entangled ones finish last.
    """
    if not changes:
        return []
    vacated = {c["old_mark"] for c in changes if c["old_mark"]}
    tangled = [c for c in changes if c["new_mark"] in vacated]
    plain = [c for c in changes if c["new_mark"] not in vacated]
    phases: List[Tuple[str, List[Dict[str, Any]]]] = []
    used = set(reserved) | {c["new_mark"] for c in changes}
    n = 0
    temps = []
    for c in tangled:
        while True:
            n += 1
            tmp = f"__renum_{n}"
            if tmp not in used:
                break
        used.add(tmp)
        temps.append({**c, "value": tmp})
    if temps:
        phases.append(("temporary", temps))
    if plain:
        phases.append(("final", [{**c, "value": c["new_mark"]} for c in plain]))
    if tangled:
        phases.append(("final", [{**c, "value": c["new_mark"]} for c in tangled]))
    return phases
