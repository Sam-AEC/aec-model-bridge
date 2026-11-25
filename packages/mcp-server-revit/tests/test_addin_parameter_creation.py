"""Shared and project parameter creation: add-in source guards and the provider payloads.

No dotnet in CI, so the C# checks read the handler text. Live Revit behaviour is UNVERIFIED.
"""
import re
from pathlib import Path

import pytest

from revit_mcp_server.bridge import contract_generated as contract
from revit_mcp_server.bridge.contract_validate import payload_problems
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

ADDIN_SRC = Path(__file__).resolve().parents[3] / "packages" / "revit-bridge-addin" / "src"
FACTORY = ADDIN_SRC / "Bridge" / "BridgeCommandFactory.cs"


def _method_body(source: str, signature_re: str) -> str:
    match = re.search(signature_re, source)
    assert match, f"method not found: {signature_re}"
    start = source.index("{", match.end())
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError("unbalanced braces")


def _source() -> str:
    return FACTORY.read_text(encoding="utf-8")


def _shared() -> str:
    return _method_body(_source(), r"private static object ExecuteCreateSharedParameter\(UIApplication app, JsonElement payload\)")


def _project() -> str:
    return _method_body(_source(), r"private static object ExecuteCreateProjectParameter\(UIApplication app, JsonElement payload\)")


@pytest.mark.parametrize("body", [_shared, _project], ids=["shared", "project"])
def test_handlers_are_implemented_and_write_inside_a_checked_transaction(body):
    text = body()
    assert "NotImplementedException" not in text
    assert "using (var trans = CreateTransaction(doc," in text
    assert "trans.Start();" in text and "trans.CommitChecked();" in text
    assert "doc.ParameterBindings.Insert(definition, binding, groupTypeId)" in text
    assert "ResolveBindableCategories(doc, ReadCategoryNames(payload))" in text
    assert "doc.IsFamilyDocument" in text
    assert "BuiltInParameterGroup" not in text, "Revit 2025+ removed BuiltInParameterGroup; use GroupTypeId"


def test_handlers_read_exactly_the_contract_keys():
    keys = {
        "revit.create_shared_parameter": set(re.findall(r'payload, "(\w+)"', _shared())),
        "revit.create_project_parameter": set(re.findall(r'payload, "(\w+)"', _project())),
    }
    for command, read in keys.items():
        read.update({"categories", "name"})  # read by ReadCategoryNames and RequireParameterName
        assert read == set(contract.COMMANDS[command]["params"]["properties"]), command


def test_shared_parameter_uses_the_users_file_and_never_switches_it():
    text = _shared()
    assert "application.OpenSharedParameterFile()" in text
    assert "string.IsNullOrWhiteSpace(sharedFilePath)" in text
    assert "SharedParametersFilename setting" in text, "the refusal must name the setting"
    assert "SharedParametersFilename =" not in text, "must not switch the user's shared parameter file"
    assert "File.WriteAllText" not in text and "File.Create" not in text
    assert text.index("ResolveBindableCategories(") < text.index("OpenSharedParameterFile()"), \
        "inputs are checked before the file is opened"
    # Same name and different type is refused; a binding is merged with ReInsert.
    assert "!SameSpec(existing.GetDataType(), spec)" in text
    assert "doc.ParameterBindings.ReInsert(definition, binding, groupTypeId)" in text
    assert "new ExternalDefinitionCreationOptions(parameterName, spec)" in text
    assert "definition.GUID.ToString()" in text and "bound_categories = boundNames" in text and "warnings" in text


def test_project_parameter_restores_the_users_setting_in_finally_and_deletes_the_temp_file():
    text = _project()
    finally_at = text.index("finally")
    finally_block = _method_body(text[finally_at:], r"finally")
    assert "application.SharedParametersFilename = originalSharedParametersFilename" in finally_block
    assert "File.Delete(tempPath)" in finally_block
    assert text.index("var originalSharedParametersFilename = application.SharedParametersFilename;") < \
        text.index("application.SharedParametersFilename = tempPath;")
    assert text.index("application.SharedParametersFilename = tempPath;") < finally_at
    assert "Path.GetTempPath()" in text and "Guid.NewGuid()" in text
    assert "trans.Start();" in text[: text.index("application.SharedParametersFilename = tempPath;")], \
        "CreateTransaction must run (and refuse in a read batch) before the setting changes"
    assert "guid = guid.ToString()" in text and "bound_categories = boundNames" in text


def test_type_and_group_maps_use_forge_type_ids():
    source = _source()
    spec = _method_body(source, r"private static ForgeTypeId ResolveParameterSpec\(")
    for member in ("SpecTypeId.String.Text", "SpecTypeId.Int.Integer", "SpecTypeId.Number", "SpecTypeId.Length",
                   "SpecTypeId.Area", "SpecTypeId.Volume", "SpecTypeId.Boolean.YesNo", "SpecTypeId.String.Url",
                   "SpecTypeId.Reference.Material"):
        assert member in spec, member
    assert "Unknown parameter_type" in spec
    group = _method_body(source, r"private static ForgeTypeId ResolveParameterGroup\(")
    for member in ("GroupTypeId.Data", "GroupTypeId.IdentityData", "GroupTypeId.Text", "GroupTypeId.Constraints"):
        assert member in group, member
    assert 'groupName ?? "Data"' in group, "default group is Data"


def test_unknown_categories_are_refused_with_their_names():
    body = _method_body(_source(), r"private static List<Category> ResolveBindableCategories\(")
    assert 'Unknown categories: {string.Join(", ", unknown)}' in body
    assert "AllowsBoundParameters" in body
    assert "categories is empty" in body


# ---------------------------------------------------------------- provider payloads


@pytest.fixture
def provider(tmp_path):
    return RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)


def test_shared_parameter_payload_fits_the_contract(provider):
    command, payload = provider._bridge_call_for(
        "revit_create_shared_parameter",
        {"name": "Fire Rating", "categories": ["Walls", "Doors"], "type": "Text", "is_instance": False},
    )
    assert command == "revit.create_shared_parameter"
    assert payload == {
        "name": "Fire Rating", "parameter_type": "Text", "group_name": "Data",
        "categories": ["Walls", "Doors"], "is_instance": False,
    }
    assert payload_problems(contract.COMMANDS[command]["params"], payload, contract.DEFS) == []


def test_project_parameter_payload_fits_the_contract(provider):
    command, payload = provider._bridge_call_for(
        "revit_create_project_parameter", {"name": "Zone", "categories": "Rooms", "group": "IdentityData"},
    )
    assert command == "revit.create_project_parameter"
    assert payload == {
        "name": "Zone", "parameter_type": "Text", "group": "IdentityData", "is_instance": True, "categories": ["Rooms"],
    }
    assert payload_problems(contract.COMMANDS[command]["params"], payload, contract.DEFS) == []


@pytest.mark.parametrize("tool", ["revit_create_shared_parameter", "revit_create_project_parameter"])
def test_missing_categories_are_refused_before_sending(provider, tool):
    command, payload = provider._bridge_call_for(tool, {"name": "X"})
    assert payload_problems(contract.COMMANDS[command]["params"], payload, contract.DEFS)


@pytest.mark.parametrize("tool", ["revit_create_shared_parameter", "revit_create_project_parameter"])
def test_tools_require_categories_and_are_gated_writes(provider, tool):
    schema = {t.name: t.input_schema for t in provider.get_capabilities()}[tool]
    assert schema["required"] == ["name", "categories"]
    assert contract.COMMANDS[provider._tool_mapping[tool][0]]["is_mutating"] is True
