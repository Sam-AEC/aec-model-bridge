#!/usr/bin/env python3
"""Generate the canonical AEC Model Bridge Revit test model via the bridge."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "canonical-model"
DEFAULT_OUTPUT = FIXTURE_DIR / "generated" / "canonical_test_model.rvt"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"

LEVELS = [("L1", 0.0), ("L2", 10.0), ("L3", 20.0), ("L4", 30.0), ("L5", 40.0)]
EXPECTED_COUNTS = {
    "levels": 5,
    "walls": 200,
    "doors": 60,
    "windows": 40,
    "rooms": 25,
    "floor_plan_views": 30,
    "sheets": 10,
    "model_groups": 4,
}
SUPPORTED_SEEDED_RULES = {
    "door_missing_mark": 12,
    "room_missing_number": 3,
}
KNOWN_GAPS = {
    "room_not_placed": "No current bridge command creates an unplaced room.",
    "room_missing_name": "Revit assigns a default room name when the create-room payload omits one.",
    "inplace_family_used": "No current bridge command creates in-place families.",
    "duplicate_sheet_numbers": "Revit rejects duplicate sheet numbers at creation time.",
}


@dataclass(frozen=True)
class BridgeSwitch:
    endpoint: str
    token: str | None = None
    source: str = "explicit"


class BridgeCallError(RuntimeError):
    pass


class BridgeClient:
    def __init__(self, switch: BridgeSwitch, timeout: int = 60) -> None:
        self.endpoint = switch.endpoint.rstrip("/")
        self.token = switch.token
        self.timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def execute(self, tool: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {
            "tool": tool,
            "payload": payload or {},
            "request_id": str(uuid.uuid4()),
        }
        response = self._request("POST", "/execute", body)
        status = response.get("Status") or response.get("status")
        if status == "error":
            message = response.get("Message") or response.get("message") or "Unknown bridge error"
            raise BridgeCallError(f"{tool}: {message}")
        if "Result" in response:
            return response["Result"] or {}
        return response.get("result") or response

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"{self.endpoint}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BridgeCallError(f"HTTP {exc.code} from {path}: {detail}") from exc
        except URLError as exc:
            raise BridgeCallError(f"Bridge unreachable at {self.endpoint}: {exc.reason}") from exc


def discover_switch(url: str | None = None, token: str | None = None, registry_dir: Path | None = None) -> BridgeSwitch:
    if url:
        return BridgeSwitch(url, token, "argument")

    registry_dir = registry_dir or Path(os.environ.get("LOCALAPPDATA", "")) / "AECModelBridge" / "registry"
    if registry_dir.exists():
        files = sorted(
            registry_dir.glob("revit-*.json"),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            endpoint = data.get("endpoint")
            if endpoint:
                return BridgeSwitch(endpoint, data.get("session_token"), str(path))

    env_url = os.environ.get("AEC_MODEL_BRIDGE_REVIT_URL") or os.environ.get("MCP_REVIT_BRIDGE_URL")
    if env_url:
        return BridgeSwitch(env_url, os.environ.get("AEC_MODEL_BRIDGE_REVIT_TOKEN"), "environment")

    return BridgeSwitch("http://127.0.0.1:3000", None, "legacy-default")


def point(x: float, y: float, z: float = 0.0) -> dict[str, float]:
    return {"x": x, "y": y, "z": z}


def wall_payloads() -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for level_name, _ in LEVELS:
        for index in range(20):
            y = index * 6.0
            payloads.append({
                "start_point": point(0.0, y),
                "end_point": point(180.0, y),
                "height": 10.0,
                "level": level_name,
            })
        for index in range(20):
            x = index * 9.0
            payloads.append({
                "start_point": point(x, 0.0),
                "end_point": point(x, 114.0),
                "height": 10.0,
                "level": level_name,
            })
    return payloads


def room_payloads() -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index in range(EXPECTED_COUNTS["rooms"]):
        payload = {
            "level": "L1",
            "location_point": point(12.0 + (index % 5) * 30.0, 12.0 + (index // 5) * 18.0),
            "name": f"Room {index + 1:02d}",
        }
        if index < EXPECTED_COUNTS["rooms"] - SUPPORTED_SEEDED_RULES["room_missing_number"]:
            payload["number"] = f"R-{index + 1:03d}"
        payloads.append(payload)
    return payloads


def view_payloads() -> list[dict[str, Any]]:
    return [
        {"level": level_name, "name": f"FP-{level_name}-{index + 1:02d}"}
        for level_name, _ in LEVELS
        for index in range(6)
    ]


def sheet_payloads(titleblock_name: str | None) -> list[dict[str, Any]]:
    payloads = []
    for index in range(EXPECTED_COUNTS["sheets"]):
        payload = {
            "sheet_number": f"S-{index + 1:03d}",
            "sheet_name": f"Canonical Sheet {index + 1:02d}",
        }
        if titleblock_name:
            payload["titleblock_name"] = titleblock_name
        payloads.append(payload)
    return payloads


def planned_call_counts() -> dict[str, int]:
    return {
        "revit.create_new_document": 1,
        "revit.create_level": len(LEVELS),
        "revit.create_wall": len(wall_payloads()),
        "revit.place_door": EXPECTED_COUNTS["doors"],
        "revit.place_window": EXPECTED_COUNTS["windows"],
        "revit.set_parameter_value": 48 + EXPECTED_COUNTS["windows"],
        "revit.create_room": len(room_payloads()),
        "revit.create_floor_plan_view": len(view_payloads()),
        "revit.create_sheet": EXPECTED_COUNTS["sheets"],
        "revit.place_viewport_on_sheet": 22,
        "revit.create_group": EXPECTED_COUNTS["model_groups"],
        "revit.save_document": 1,
        "revit.extract_snapshot": 1,
    }


def output_label(output_path: Path) -> str:
    try:
        return output_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(output_path)


def manifest(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    return {
        "schema": "amb.fixture.canonical_model/1",
        "name": "canonical_test_model",
        "generator": "scripts/revit/generate_canonical_test_model.py",
        "output_path": output_label(output_path),
        "seeded_defects": "fixtures/canonical-model/seeded-defects.json",
        "goldens": {
            "snapshot_summary": "fixtures/canonical-model/goldens/snapshot-summary.json",
            "qaqc_findings_summary": "fixtures/canonical-model/goldens/qaqc-findings-summary.json",
        },
        "expected_counts": EXPECTED_COUNTS,
        "supported_seeded_rules": SUPPORTED_SEEDED_RULES,
        "known_gaps": KNOWN_GAPS,
        "planned_calls": planned_call_counts(),
    }


def pick_family(bridge: BridgeClient, category: str) -> tuple[str, str]:
    result = bridge.execute("revit.list_families", {"category": category})
    for family in result.get("families", []):
        types = family.get("types") or []
        if types:
            return family["name"], types[0]["name"]
    raise BridgeCallError(f"No loaded {category} family with at least one type was found")


def pick_titleblock(bridge: BridgeClient) -> str | None:
    try:
        result = bridge.execute("revit.list_titleblocks", {})
    except BridgeCallError:
        return None
    titleblocks = result.get("titleblocks") or []
    return titleblocks[0]["family_name"] if titleblocks else None


def on_wall(payload: dict[str, Any], ratio: float) -> dict[str, float]:
    start = payload["start_point"]
    end = payload["end_point"]
    return point(
        start["x"] + (end["x"] - start["x"]) * ratio,
        start["y"] + (end["y"] - start["y"]) * ratio,
        0.0,
    )


def set_mark(bridge: BridgeClient, element_id: int, value: str, allow_partial: bool) -> None:
    try:
        bridge.execute("revit.set_parameter_value", {
            "element_id": element_id,
            "parameter_name": "Mark",
            "value": value,
        })
    except BridgeCallError:
        if not allow_partial:
            raise


def generate(args: argparse.Namespace) -> dict[str, Any]:
    switch = discover_switch(args.url, args.token)
    bridge = BridgeClient(switch, args.timeout)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        return manifest(output_path)

    print(f"Using Revit bridge at {switch.endpoint} ({switch.source})", file=sys.stderr)
    bridge.get("/health")

    if not args.use_active_document:
        payload = {"template_path": args.template} if args.template else {}
        bridge.execute("revit.create_new_document", payload)

    for name, elevation in LEVELS:
        bridge.execute("revit.create_level", {"name": name, "elevation": elevation})

    walls = []
    for payload in wall_payloads():
        result = bridge.execute("revit.create_wall", payload)
        walls.append({"id": result["wall_id"], "payload": payload})

    door_family, door_type = pick_family(bridge, "Doors")
    window_family, window_type = pick_family(bridge, "Windows")

    doors = []
    for index, wall in enumerate(walls[:EXPECTED_COUNTS["doors"]]):
        result = bridge.execute("revit.place_door", {
            "wall_id": wall["id"],
            "location": on_wall(wall["payload"], 0.25 + (index % 3) * 0.2),
            "family_name": door_family,
            "type_name": door_type,
        })
        doors.append(result["door_id"])

    windows = []
    start = EXPECTED_COUNTS["doors"]
    for index, wall in enumerate(walls[start:start + EXPECTED_COUNTS["windows"]]):
        result = bridge.execute("revit.place_window", {
            "wall_id": wall["id"],
            "location": on_wall(wall["payload"], 0.25 + (index % 3) * 0.2),
            "family_name": window_family,
            "type_name": window_type,
        })
        windows.append(result["window_id"])

    marked_doors = EXPECTED_COUNTS["doors"] - SUPPORTED_SEEDED_RULES["door_missing_mark"]
    for index, element_id in enumerate(doors[:marked_doors], start=1):
        set_mark(bridge, element_id, f"D-{index:03d}", args.allow_partial)
    for index, element_id in enumerate(windows, start=1):
        set_mark(bridge, element_id, f"W-{index:03d}", args.allow_partial)

    for payload in room_payloads():
        bridge.execute("revit.create_room", payload)

    view_ids = []
    for payload in view_payloads():
        result = bridge.execute("revit.create_floor_plan_view", payload)
        view_ids.append(result["view_id"])

    titleblock = pick_titleblock(bridge)
    sheet_ids = []
    for payload in sheet_payloads(titleblock):
        result = bridge.execute("revit.create_sheet", payload)
        sheet_ids.append(result["sheet_id"])

    if titleblock:
        for index, view_id in enumerate(view_ids[:22]):
            bridge.execute("revit.place_viewport_on_sheet", {
                "sheet_id": sheet_ids[index % len(sheet_ids)],
                "view_id": view_id,
                "location": point(0.25 + (index % 3) * 0.25, 0.25 + ((index // 3) % 3) * 0.18),
            })
    elif not args.allow_partial:
        raise BridgeCallError("No titleblock family found; cannot place views on sheets")

    for index in range(EXPECTED_COUNTS["model_groups"]):
        group_walls = [wall["id"] for wall in walls[index * 4:(index + 1) * 4]]
        bridge.execute("revit.create_group", {
            "element_ids": group_walls,
            "name": f"Canonical Group {index + 1}",
        })

    bridge.execute("revit.save_document", {"path": str(output_path)})
    snapshot = None if args.skip_snapshot else bridge.execute("revit.extract_snapshot", {"dirty_only": False})

    summary = manifest(output_path)
    summary["snapshot"] = snapshot
    return summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Revit bridge URL. Defaults to registry discovery, then http://127.0.0.1:3000.")
    parser.add_argument("--token", help="Bearer token for Contract v2 bridge mode.")
    parser.add_argument("--template", help="Optional Revit project template path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output RVT path.")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds.")
    parser.add_argument("--use-active-document", action="store_true", help="Build into the active clean document.")
    parser.add_argument("--allow-partial", action="store_true", help="Continue past optional family/titleblock/parameter gaps.")
    parser.add_argument("--skip-snapshot", action="store_true", help="Skip the final snapshot extraction call.")
    parser.add_argument("--dry-run", action="store_true", help="Print the manifest and planned call counts without Revit.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        summary = generate(args)
    except BridgeCallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
