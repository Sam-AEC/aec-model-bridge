"""Shared add-in command contract (contracts/bridge-commands.json), ADR 0022.

Covers: the generated Python and C# files are current; the contract names and IsMutating flags agree
with the [BridgeCommand] attributes in the add-in; every command the Python provider sends is in the
contract; the validator; and the bridge client refusing a bad payload before anything is sent.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path

import httpx
import pytest

from revit_mcp_server.elicitation import EXPORT_PATH_TOOLS
from revit_mcp_server.bridge import contract_generated as contract
from revit_mcp_server.bridge.client import VALIDATE_ENV, BridgeClient
from revit_mcp_server.bridge.contract_validate import payload_problems
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeContractError, SchemaValidationError, WorkspaceViolation
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.security import file_binding
from revit_mcp_server.security.workspace import WorkspaceMonitor

ROOT = Path(__file__).resolve().parents[3]
BRIDGE_SRC = ROOT / "packages" / "revit-bridge-addin" / "src" / "Bridge"
CONTRACT_FILE = ROOT / "contracts" / "bridge-commands.json"
ATTR = re.compile(r'\[BridgeCommand\("([^"]+)"\s*,\s*IsMutating\s*=\s*(true|false)\b')


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_bridge_contract", ROOT / "scripts" / "gen_bridge_contract.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_bridge_contract"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


def _registered_commands() -> dict[str, bool]:
    """name -> IsMutating from every [BridgeCommand] in the partial BridgeCommandFactory class."""
    found: dict[str, bool] = {}
    for path in sorted(BRIDGE_SRC.glob("*.cs")):
        text = path.read_text(encoding="utf-8")
        if "partial class BridgeCommandFactory" not in text:
            continue
        for name, flag in ATTR.findall(text):
            assert name not in found, f"{name} is registered twice"
            found[name] = flag == "true"
    return found


# ---------------------------------------------------------------- generated files and agreement


def test_generated_files_are_current(gen) -> None:
    for path, text in gen.outputs().items():
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert current == text, f"{path.name} is stale. Run: python scripts/gen_bridge_contract.py"


def test_contract_file_is_well_formed(gen) -> None:
    data = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
    assert gen.check_contract(data) == []


def test_contract_checker_names_structural_problems(gen) -> None:
    bad = {
        "contract_version": 1,
        "$defs": {},
        "commands": {
            "revit.b": {"is_mutating": "yes", "params": {"type": "object"}},
            "revit.a": {"is_mutating": False, "params": {"type": "object", "properties": {"x": {"$ref": "#/$defs/nope"}}}},
            "Bad Name": {"is_mutating": True, "params": "sometimes"},
        },
    }
    problems = " | ".join(gen.check_contract(bad))
    assert "sorted" in problems
    assert "revit.b: is_mutating" in problems
    assert "unknown reference #/$defs/nope" in problems
    assert "Bad Name: name must look like" in problems
    assert 'params must be an object schema or "unchecked"' in problems


def test_contract_names_match_the_add_in_registrations() -> None:
    registered = _registered_commands()
    assert len(registered) > 100  # the scan found the attributes
    in_contract = set(contract.COMMANDS)
    assert in_contract - set(registered) == set(), "contract lists commands the add-in does not register"
    assert set(registered) - in_contract == set(), "add-in registers commands the contract does not list"


def test_is_mutating_flags_agree_with_the_add_in() -> None:
    registered = _registered_commands()
    wrong = {n: (contract.COMMANDS[n]["is_mutating"], flag) for n, flag in registered.items()
             if contract.COMMANDS[n]["is_mutating"] != flag}
    assert wrong == {}, f"contract vs [BridgeCommand] IsMutating differ: {wrong}"


def test_generated_csharp_names_and_flags_match_the_add_in() -> None:
    text = (BRIDGE_SRC / "BridgeContract.g.cs").read_text(encoding="utf-8")
    consts = dict(re.findall(r'public const string (\w+)\s*=\s*"([^"]+)";', text))
    flags = dict(re.findall(r"\{ (\w+),\s*(true|false) \}", text))
    registered = _registered_commands()
    assert set(consts.values()) == set(registered)
    assert set(flags) == set(consts)
    for const, name in consts.items():
        assert (flags[const] == "true") == registered[name], name


def test_generated_csharp_stays_simple() -> None:
    """No dotnet in CI: keep the file to constructs that build on net48, net8 and net10."""
    text = (BRIDGE_SRC / "BridgeContract.g.cs").read_text(encoding="utf-8")
    assert "namespace RevitBridge.Bridge;" in text
    assert "public static class BridgeContract" in text
    assert "new Dictionary<string, bool>(StringComparer.Ordinal)" in text
    for construct in ("record ", "init;", "=> ", "new()", "required ", "ImmutableDictionary", "FrozenDictionary"):
        assert construct not in text, construct


def test_every_command_the_provider_sends_is_in_the_contract(tmp_path) -> None:
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    sent = {bridge for bridge, _ in provider._tool_mapping.values() if bridge}
    sent.add("revit.get_context")  # revit_context.live_context
    assert sent - set(contract.COMMANDS) == set()


# Tools whose payload builder does not produce what the add-in reads. Fixing a builder removes its name
# from this list; keep it empty. The client refuses a listed tool's payload before sending.
KNOWN_BUILDER_MISMATCH_FULL_ARGS: set[str] = set()
KNOWN_BUILDER_MISMATCH_REQUIRED_ONLY: set[str] = set()

SAMPLE_CSV = "sheet_number,sheet_name\nA101,Plan\nA102,Section\n"


def _sample(schema: dict, name: str, folder: Path, index: int = 0):
    kind = schema.get("type")
    kind = kind[0] if isinstance(kind, list) else kind
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "string":
        if "path" in name or "directory" in name:
            return str(folder / "out.dat")
        return "walls" if "categor" in name else f"x{index}" if index else "x"
    if kind == "integer":
        return 1 + index
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if kind == "array":
        return [_sample(schema.get("items", {}), name, folder, i) for i in range(3)]
    if kind == "object":
        return {k: _sample(v, k, folder, index) for k, v in schema.get("properties", {}).items()}
    return "x"


def _sample_keys(schema: dict, required_only: bool) -> list[str]:
    """Keys of one valid call: oneOf/anyOf take their first branch; oneOf drops the other branches' keys."""
    props = schema.get("properties", {})
    branches = schema.get("oneOf") or schema.get("anyOf") or []
    first = branches[0].get("required", []) if branches else []
    if required_only:
        return list(dict.fromkeys([*schema.get("required", []), *first]))
    others = {k for b in schema.get("oneOf", [])[1:] for k in b.get("required", [])} - set(first)
    return [k for k in props if k not in others]


@pytest.mark.parametrize("required_only", [False, True], ids=["all-args", "required-args"])
def test_provider_payload_builders_against_the_contract(tmp_path, required_only) -> None:
    (tmp_path / "out.dat").write_text(SAMPLE_CSV, encoding="utf-8", newline="")  # read by the CSV sheet builder
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    schemas = {t.name: t.input_schema for t in provider.get_capabilities()}
    mismatched = set()
    for tool, (bridge, builder) in provider._tool_mapping.items():
        if not bridge or contract.COMMANDS[bridge]["params"] == contract.UNCHECKED:
            continue
        schema = schemas.get(tool, {})
        props = schema.get("properties", {})
        keys = _sample_keys(schema, required_only)
        path_key = EXPORT_PATH_TOOLS.get(tool, (None,))[0]
        if path_key and path_key in props and path_key not in keys:
            # Not in the schema's required list so the MCP layer can ask for it (elicitation), but a
            # call always reaches the builder with it set.
            keys.append(path_key)
        args = {k: _sample(props[k], k, tmp_path) for k in keys}
        if "csv_sha256" in args:  # set by the server in plan_actions: the digest of the CSV it read
            args["csv_sha256"] = file_binding.digest(SAMPLE_CSV.encode("utf-8"))
        payload = builder(args)
        if payload_problems(contract.COMMANDS[bridge]["params"], payload, contract.DEFS):
            mismatched.add(tool)
    expected = KNOWN_BUILDER_MISMATCH_REQUIRED_ONLY if required_only else KNOWN_BUILDER_MISMATCH_FULL_ARGS
    assert mismatched == expected


# ---------------------------------------------------------------- the 16 builders fixed against the contract


@pytest.fixture
def build(tmp_path):
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)

    def run(tool: str, args: dict) -> dict:
        bridge, builder = provider._tool_mapping[tool]
        payload = builder(args)
        assert payload_problems(contract.COMMANDS[bridge]["params"], payload, contract.DEFS) == [], payload
        assert None not in payload.values(), f"{tool} sent a null optional key: {payload}"
        return payload

    run.provider = provider
    return run


def test_create_sheet_payload(build) -> None:
    assert build("revit_create_sheet", {"name": "Plan", "number": "A101"}) == {"sheet_number": "A101", "sheet_name": "Plan"}
    full = build("revit_create_sheet", {"name": "Plan", "number": "A101", "titleblock_name": "A1 metric"})
    assert full["titleblock_name"] == "A1 metric"


def test_create_sheet_refuses_titleblock_id(build) -> None:
    with pytest.raises(ValueError, match="titleblock_name"):
        build("revit_create_sheet", {"name": "Plan", "number": "A101", "titleblock_id": 5})


def test_create_floor_plan_view_payload(build) -> None:
    assert build("revit_create_floor_plan_view", {"level_name": "L1"}) == {"level": "L1"}
    assert build("revit_create_floor_plan_view", {"level_name": "L1", "view_name": "L1 plan"}) == {
        "level": "L1", "name": "L1 plan"}


def test_create_shared_parameter_payload(build) -> None:
    assert build("revit_create_shared_parameter", {"name": "Fire rating", "categories": "Doors"}) == {
        "name": "Fire rating", "parameter_type": "Text", "group_name": "Data", "categories": ["Doors"]}
    full = build("revit_create_shared_parameter",
                 {"name": "R", "type": "Length", "group": "Data", "categories": ["Walls", "Doors"], "is_instance": False})
    assert full["categories"] == ["Walls", "Doors"] and full["is_instance"] is False


def test_create_project_parameter_payload(build) -> None:
    assert build("revit_create_project_parameter", {"name": "Zone", "categories": ["Rooms"]}) == {
        "name": "Zone", "parameter_type": "Text", "group": "Data", "is_instance": True, "categories": ["Rooms"]}
    assert build("revit_create_project_parameter",
                 {"name": "Zone", "categories": ["Rooms"], "is_instance": False})["is_instance"] is False


def test_batch_set_parameters_payload(build) -> None:
    payload = build("revit_batch_set_parameters", {"element_ids": [3, 4], "parameter_name": "Mark", "value": "A"})
    assert payload == {"updates": [{"element_id": 3, "parameter_name": "Mark", "value": "A"},
                                   {"element_id": 4, "parameter_name": "Mark", "value": "A"}]}
    with pytest.raises(ValueError, match="non-empty list"):
        build("revit_batch_set_parameters", {"element_ids": [], "parameter_name": "Mark", "value": "A"})


def test_set_type_parameter_payload(build) -> None:
    payload = build("revit_set_type_parameter", {"type_id": 77, "parameter_name": "Width", "value": 3})
    assert payload == {"type_id": 77, "parameter_name": "Width", "value": 3}
    # The older element_id name still works and maps to type_id.
    assert build("revit_set_type_parameter", {"element_id": 77, "parameter_name": "Width", "value": 3}) == payload
    with pytest.raises(ValueError, match="give one of them"):
        build("revit_set_type_parameter", {"type_id": 1, "element_id": 2, "parameter_name": "W", "value": 3})


def test_duplicate_sheet_payload(build) -> None:
    args = {"sheet_id": 9, "new_sheet_number": "A102", "new_sheet_name": "Copy"}
    assert build("revit_duplicate_sheet", args) == {
        "source_sheet_id": 9, "new_sheet_number": "A102", "new_sheet_name": "Copy"}
    assert build("revit_duplicate_sheet", {**args, "with_views": True})["duplicate_viewports"] is True
    assert "duplicate_viewports" not in build("revit_duplicate_sheet", {**args, "duplicate_option": "Duplicate"})
    with pytest.raises(ValueError, match="plain duplicate"):
        build("revit_duplicate_sheet", {**args, "duplicate_option": "WithDetailing"})
    with pytest.raises(ValueError, match="new_sheet_number"):
        build("revit_duplicate_sheet", {"sheet_id": 9})


def test_renumber_sheets_payload(build) -> None:
    payload = build("revit_renumber_sheets", {"sheet_ids": [5, 6], "start_number": 101, "prefix": "A-"})
    assert payload == {"sheets": [{"sheet_id": 5, "new_sheet_number": "A-101"},
                                  {"sheet_id": 6, "new_sheet_number": "A-102"}]}
    explicit = [{"sheet_id": 5, "new_sheet_number": "B1"}]
    assert build("revit_renumber_sheets", {"sheets": explicit}) == {"sheets": explicit}


@pytest.mark.parametrize("args, needle", [
    ({"start_number": 1, "prefix": "A"}, "needs the sheets to renumber"),
    ({"sheet_ids": [5, 5], "start_number": 1}, "listed twice"),
    ({"sheets": [{"sheet_id": 1, "new_sheet_number": "A"}, {"sheet_id": 2, "new_sheet_number": "A"}]}, "same number"),
    ({"sheets": [{"sheet_id": 1, "new_sheet_number": "A"}], "start_number": 1}, "not both"),
])
def test_renumber_sheets_refusals(build, args, needle) -> None:
    with pytest.raises(ValueError, match=needle):
        build("revit_renumber_sheets", args)


def test_export_dwg_payload(build, tmp_path) -> None:
    folder = os.path.realpath(tmp_path / "dwg")
    assert build("revit_export_dwg", {"view_id": 12, "output_directory": folder}) == {
        "view_ids": [12], "output_directory": folder}
    assert build("revit_export_dwg", {"view_id": 12, "output_path": folder, "dwg_version": "AutoCAD2013"}) == {
        "view_ids": [12], "output_directory": folder, "dwg_version": "AutoCAD2013"}
    with pytest.raises(ValueError, match="needs a folder, not a file name"):
        build("revit_export_dwg", {"view_id": 12, "output_path": str(tmp_path / "A101.dwg")})


def test_export_dwg_sends_the_resolved_absolute_folder(build, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    expected = os.path.join(os.path.realpath(tmp_path), "exports", "dwg")
    for key in ("output_directory", "output_path"):
        payload = build("revit_export_dwg", {"view_id": 12, key: "exports/../exports/dwg"})
        assert payload["output_directory"] == expected and os.path.isabs(payload["output_directory"])
    with pytest.raises(WorkspaceViolation):
        build("revit_export_dwg", {"view_id": 12, "output_directory": "../elsewhere"})
    with pytest.raises(ValueError, match="must be a folder path"):
        build("revit_export_dwg", {"view_id": 12, "output_directory": 5})


@pytest.mark.anyio
async def test_export_dwg_output_directory_is_workspace_checked(tmp_path) -> None:
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    with pytest.raises(WorkspaceViolation):
        await provider.execute_tool("revit_export_dwg", {"view_id": 1, "output_directory": "/outside/dwg"})


def test_batch_create_sheets_from_csv_payload(build, tmp_path) -> None:
    path = tmp_path / "sheets.csv"
    path.write_text("Sheet Number,Sheet Name,Titleblock Name\nA101,Plan,\nA102,Section,A0\n\n", encoding="utf-8-sig", newline="")
    payload = build("revit_batch_create_sheets_from_csv", {"csv_path": str(path), "titleblock_name": "A1"})
    assert payload == {"sheets": [
        {"sheet_number": "A101", "sheet_name": "Plan", "titleblock_name": "A1"},
        {"sheet_number": "A102", "sheet_name": "Section", "titleblock_name": "A0"},
    ]}
    path.write_text("number,name\nA101,Plan\n", encoding="utf-8", newline="")
    assert build("revit_batch_create_sheets_from_csv", {"csv_path": str(path)}) == {
        "sheets": [{"sheet_number": "A101", "sheet_name": "Plan"}]}


@pytest.mark.parametrize("text, needle", [
    ("title\nA101\n", "column named sheet_number"),
    ("sheet_number,sheet_name\nA101,\n", "line 2 needs both"),
    ("sheet_number,sheet_name\nA101,Plan\nA101,Copy\n", "appears twice"),
    ("sheet_number,sheet_name\n", "no sheet rows"),
])
def test_batch_create_sheets_from_csv_refusals(build, tmp_path, text, needle) -> None:
    path = tmp_path / "sheets.csv"
    path.write_text(text, encoding="utf-8", newline="")
    with pytest.raises(ValueError, match=needle):
        build("revit_batch_create_sheets_from_csv", {"csv_path": str(path)})


def test_batch_create_sheets_from_csv_needs_an_existing_workspace_file(build, tmp_path) -> None:
    with pytest.raises(ValueError, match="no CSV file"):
        build("revit_batch_create_sheets_from_csv", {"csv_path": str(tmp_path / "missing.csv")})
    with pytest.raises(WorkspaceViolation):
        build("revit_batch_create_sheets_from_csv", {"csv_path": "/outside/sheets.csv"})


@pytest.mark.anyio
async def test_batch_create_sheets_from_csv_mock_counts_rows(tmp_path) -> None:
    path = tmp_path / "sheets.csv"
    path.write_text(SAMPLE_CSV, encoding="utf-8", newline="")
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    result = await provider.execute_tool("revit_batch_create_sheets_from_csv", {"csv_path": str(path)})
    assert result == {"sheets_created": 2}


@pytest.mark.parametrize("tool, args, optional", [
    ("revit_create_tag", {"element_id": 1, "x": 0, "y": 0}, {"view_id": 4}),
    ("revit_create_text_note", {"text": "Hi", "x": 0, "y": 0}, {"view_id": 4}),
    ("revit_set_element_material", {"element_id": 1, "material_name": "Concrete"}, {"face_index": 2}),
    ("revit_edit_family", {"family_name": "Desk"}, {"family_symbol_id": 3, "family_instance_id": 4}),
    ("revit_place_door", {"wall_id": 1, "x": 0, "y": 0},
     {"family_name": "D", "type_name": "T", "hand_flipped": True, "facing_flipped": False}),
    ("revit_place_window", {"wall_id": 1, "location": {"x": 0, "y": 0}},
     {"family_name": "W", "type_name": "T", "hand_flipped": False, "facing_flipped": True}),
])
def test_optional_arguments_are_omitted_not_null(build, tool, args, optional) -> None:
    bare = build(tool, args)
    assert not set(optional) & set(bare)
    full = build(tool, {**args, **optional})
    assert {k: full[k] for k in optional} == optional


def test_edit_family_needs_one_identifier(build) -> None:
    with pytest.raises(ValueError, match="family_name, family_symbol_id or family_instance_id"):
        build("revit_edit_family", {})


@pytest.mark.parametrize("tool", ["revit_place_door", "revit_place_window"])
def test_openings_refuse_a_missing_position(build, tool) -> None:
    with pytest.raises(ValueError, match="needs a position"):
        build(tool, {"wall_id": 1})
    with pytest.raises(ValueError, match="needs a position"):
        build(tool, {"wall_id": 1, "location": {"x": 1}})


def test_fixed_write_tools_stay_gated(build) -> None:
    tools = {t.name: t for t in build.provider.get_capabilities()}
    fixed = ["revit_batch_create_sheets_from_csv", "revit_batch_set_parameters", "revit_create_floor_plan_view",
             "revit_create_project_parameter", "revit_create_shared_parameter", "revit_create_sheet",
             "revit_duplicate_sheet", "revit_renumber_sheets", "revit_set_type_parameter", "revit_create_tag",
             "revit_create_text_note", "revit_edit_family", "revit_place_door", "revit_place_window",
             "revit_set_element_material"]
    assert [name for name in fixed if not tools[name].is_mutating] == []


# ---------------------------------------------------------------- validator


def _problems(command: str, payload) -> list[str]:
    return payload_problems(contract.COMMANDS[command]["params"], payload, contract.DEFS)


def _wall(**overrides):
    payload = {"start_point": {"x": 0, "y": 0, "z": 0}, "end_point": {"x": 10, "y": 0}, "height": 10, "level": "L1"}
    payload.update(overrides)
    return payload


def test_valid_payload_passes_and_extra_keys_are_allowed() -> None:
    contract.validate_command("revit.create_wall", _wall(request_id="r1", action_id="a1", wall_type=None))
    contract.validate_command("revit.health", {})


def test_missing_required_parameters_are_all_named() -> None:
    with pytest.raises(BridgeContractError) as info:
        contract.validate_command("revit.create_sheet", {"name": "A", "number": "101"})
    text = str(info.value)
    assert "Not sent to Revit" in text and "'revit.create_sheet'" in text
    assert "sheet_number is required and missing" in text and "sheet_name is required and missing" in text
    assert "contracts/bridge-commands.json" in text


def test_contract_error_is_a_value_error_and_a_schema_error() -> None:
    with pytest.raises(ValueError):
        contract.validate_command("revit.delete_element", {})
    with pytest.raises(SchemaValidationError):
        contract.validate_command("revit.delete_element", {})


@pytest.mark.parametrize("payload, needle", [
    (_wall(height="10"), "height must be a number"),
    (_wall(height=True), "height must be a number"),
    (_wall(level=None), "level must be a string"),
    (_wall(start_point={"x": None, "y": 0}), "start_point must be an object or a list"),
    (_wall(start_point=[1]), "start_point must be an object or a list"),
    (_wall(height=math.nan), "height must be a finite number"),
    (_wall(reverse="yes"), "reverse must be true or false or null"),
])
def test_wrong_types_are_refused(payload, needle) -> None:
    assert any(needle in p for p in _problems("revit.create_wall", payload)), _problems("revit.create_wall", payload)


def test_point_accepts_object_or_array() -> None:
    assert _problems("revit.create_wall", _wall(start_point=[0, 0], end_point=[5, 5, 0])) == []


@pytest.mark.parametrize("value, ok", [(5, True), (5.0, False), (True, False), (2**31, False), (-(2**31), True)])
def test_int32_fields_need_whole_numbers_in_range(value, ok) -> None:
    assert (_problems("revit.delete_element", {"element_id": value}) == []) is ok


def test_int64_fields_take_large_ids() -> None:
    assert _problems("revit.get_element_geometry", {"element_id": 2**40}) == []


def test_enum_is_case_insensitive_where_the_add_in_is() -> None:
    assert _problems("revit.check_clashes", {"category1": "Walls", "category2": "DUCTS"}) == []
    problems = _problems("revit.check_clashes", {"category1": "walls", "category2": "spaceships"})
    assert problems and "category2 must be one of: walls" in problems[0]


def test_execute_python_mode() -> None:
    assert _problems("revit.execute_python", {"script": "print(1)", "mode": "read"}) == []
    assert _problems("revit.execute_python", {"script": "print(1)", "mode": None}) == []
    assert "mode must be one of: read, write" in _problems("revit.execute_python", {"script": "x", "mode": "admin"})[0]


def test_bounds_are_enforced() -> None:
    base = {"category1": "walls", "category2": "doors"}
    assert "time_budget_s must be at most 25" in _problems("revit.check_clashes", {**base, "time_budget_s": 60})[0]
    assert "max_pairs must be at least 1" in _problems("revit.check_clashes", {**base, "max_pairs": 0})[0]
    assert "limit must be at most 500" in _problems("revit.get_elements_by_type", {"limit": 1000, "offset": 0})[0]
    assert "needs at least 1 item" in _problems("revit.convert_to_group", {"element_ids": []})[0]


def test_nested_items_report_their_path() -> None:
    payload = {"updates": [{"element_id": 1, "parameter_name": "Mark", "value": "A"}, {"element_id": "2", "value": 1}]}
    problems = _problems("revit.batch_set_parameters", payload)
    assert "updates[1].element_id must be a whole number" in " ".join(problems)
    assert "updates[1].parameter_name is required and missing" in problems


def test_color_any_of() -> None:
    assert _problems("revit.create_material", {"name": "M", "color": "#FF8800"}) == []
    assert _problems("revit.create_material", {"name": "M", "color": {"r": 1, "g": 2, "b": 3}}) == []
    assert _problems("revit.create_material", {"name": "M", "color": None}) == []
    assert _problems("revit.create_material", {"name": "M", "color": {"r": 300, "g": 2, "b": 3}})
    assert _problems("revit.create_material", {"name": "M", "color": "red"})


def test_payload_must_be_an_object() -> None:
    assert _problems("revit.health", ["a"]) == ["the payload must be an object, got ['a']"]


def test_problem_list_is_capped() -> None:
    payload = {"updates": [{"element_id": "x"} for _ in range(20)]}
    assert len(_problems("revit.batch_set_parameters", payload)) == 5


def test_unknown_and_unchecked_commands_pass(monkeypatch) -> None:
    contract.validate_command("navisworks.clash_detective", {"anything": 1})
    contract.validate_command("revit.not_a_command", {"anything": 1})
    monkeypatch.setitem(contract.COMMANDS, "revit.delete_element", {"is_mutating": True, "params": "unchecked"})
    contract.validate_command("revit.delete_element", {})
    assert contract.is_checked("revit.delete_element") is False


def test_is_mutating_lookup() -> None:
    assert contract.is_mutating("revit.create_wall") is True
    assert contract.is_mutating("revit.list_levels") is False
    assert contract.is_mutating("revit.unknown") is None


# ---------------------------------------------------------------- bridge client wiring


def _client(validate=None):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"Status": "ok", "Result": {"done": True}})

    client = BridgeClient("http://127.0.0.1:9", token="t", validate_payloads=validate)
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    client._http_key = (client.token, client.timeout)
    return client, calls


def test_client_refuses_a_bad_payload_before_sending(monkeypatch) -> None:
    monkeypatch.delenv(VALIDATE_ENV, raising=False)
    client, calls = _client()
    with pytest.raises(BridgeContractError, match="sheet_number is required"):
        client.call_tool("revit.create_sheet", {"name": "A"})
    assert calls == []


def test_client_sends_a_valid_payload(monkeypatch) -> None:
    monkeypatch.delenv(VALIDATE_ENV, raising=False)
    client, calls = _client()
    assert client.call_tool("revit.delete_element", {"element_id": 5}) == {"done": True}
    assert calls[0]["tool"] == "revit.delete_element" and calls[0]["payload"] == {"element_id": 5}


@pytest.mark.parametrize("value", ["off", "0", "false", " NO "])
def test_setting_turns_validation_off(monkeypatch, value) -> None:
    monkeypatch.setenv(VALIDATE_ENV, value)
    client, calls = _client()
    client.call_tool("revit.create_sheet", {"name": "A"})
    assert len(calls) == 1


@pytest.mark.parametrize("value", ["on", "1", "true", "maybe", ""])
def test_other_setting_values_keep_validation_on(monkeypatch, value) -> None:
    monkeypatch.setenv(VALIDATE_ENV, value)
    client, calls = _client()
    with pytest.raises(BridgeContractError):
        client.call_tool("revit.create_sheet", {"name": "A"})
    assert calls == []


def test_constructor_flag_wins_over_the_setting(monkeypatch) -> None:
    monkeypatch.setenv(VALIDATE_ENV, "on")
    client, calls = _client(validate=False)
    client.call_tool("revit.create_sheet", {"name": "A"})
    assert len(calls) == 1
    monkeypatch.setenv(VALIDATE_ENV, "off")
    client, calls = _client(validate=True)
    with pytest.raises(BridgeContractError):
        client.call_tool("revit.create_sheet", {"name": "A"})


def test_client_passes_unchecked_and_unlisted_commands(monkeypatch) -> None:
    monkeypatch.delenv(VALIDATE_ENV, raising=False)
    monkeypatch.setitem(contract.COMMANDS, "revit.create_sheet", {"is_mutating": True, "params": "unchecked"})
    client, calls = _client()
    client.call_tool("revit.create_sheet", {"name": "A"})
    client.call_tool("navisworks.clash_detective", {"x": 1})
    assert [c["tool"] for c in calls] == ["revit.create_sheet", "navisworks.clash_detective"]
