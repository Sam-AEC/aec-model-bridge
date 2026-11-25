"""Shared add-in command contract (contracts/bridge-commands.json), ADR 0022.

Covers: the generated Python and C# files are current; the contract names and IsMutating flags agree
with the [BridgeCommand] attributes in the add-in; every command the Python provider sends is in the
contract; the validator; and the bridge client refusing a bad payload before anything is sent.
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import httpx
import pytest

from revit_mcp_server.bridge import contract_generated as contract
from revit_mcp_server.bridge.client import VALIDATE_ENV, BridgeClient
from revit_mcp_server.bridge.contract_validate import payload_problems
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeContractError, SchemaValidationError
from revit_mcp_server.providers.revit import RevitProvider
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


# Tools whose payload builder does not produce what the add-in reads, found while seeding the contract.
# The add-in fails on these payloads today; the client now refuses them before sending. Fixing a builder
# removes its name from this list.
KNOWN_BUILDER_MISMATCH_FULL_ARGS = {
    "revit_batch_create_sheets_from_csv", "revit_batch_set_parameters", "revit_create_floor_plan_view",
    "revit_create_sheet",
    "revit_duplicate_sheet", "revit_export_dwg", "revit_renumber_sheets", "revit_set_type_parameter",
}
KNOWN_BUILDER_MISMATCH_REQUIRED_ONLY = KNOWN_BUILDER_MISMATCH_FULL_ARGS | {
    "revit_create_tag", "revit_create_text_note", "revit_edit_family", "revit_place_door",
    "revit_place_window", "revit_set_element_material",
}


def _sample(schema: dict, name: str, folder: Path):
    kind = schema.get("type")
    kind = kind[0] if isinstance(kind, list) else kind
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "string":
        if "path" in name or "directory" in name:
            return str(folder / "out.dat")
        return "walls" if "categor" in name else "x"
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if kind == "array":
        return [_sample(schema.get("items", {}), name, folder) for _ in range(3)]
    if kind == "object":
        return {k: _sample(v, k, folder) for k, v in schema.get("properties", {}).items()}
    return "x"


@pytest.mark.parametrize("required_only", [False, True], ids=["all-args", "required-args"])
def test_provider_payload_builders_against_the_contract(tmp_path, required_only) -> None:
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    schemas = {t.name: t.input_schema for t in provider.get_capabilities()}
    mismatched = set()
    for tool, (bridge, builder) in provider._tool_mapping.items():
        if not bridge or contract.COMMANDS[bridge]["params"] == contract.UNCHECKED:
            continue
        props = schemas.get(tool, {}).get("properties", {})
        keys = schemas.get(tool, {}).get("required", []) if required_only else list(props)
        payload = builder({k: _sample(props[k], k, tmp_path) for k in keys})
        if payload_problems(contract.COMMANDS[bridge]["params"], payload, contract.DEFS):
            mismatched.add(tool)
    expected = KNOWN_BUILDER_MISMATCH_REQUIRED_ONLY if required_only else KNOWN_BUILDER_MISMATCH_FULL_ARGS
    assert mismatched == expected


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
