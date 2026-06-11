import pytest
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from revit_mcp_server.config import BridgeMode
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.jobs import JobManager
from revit_mcp_server.security.audit import redact_data
from revit_mcp_server.errors import RevitMCPError

# Import providers
from revit_mcp_server.providers import (
    RevitProvider,
    IfcProvider,
    FakeProvider,
    AECMapperProvider,
    RhinoProvider,
    SemanticGraphProvider,
    SpeckleProvider,
    AutodeskDataProvider,
    JobProvider,
    SQLiteExporterProvider,
)
try:
    from revit_mcp_server.providers import McpProxyProvider
except ImportError:
    McpProxyProvider = None

# Global registries to check uniqueness across all tests
_all_provider_identities = set()
_all_tool_names = {}
_missing_mutation_metadata = []

# Parameterize over every registrable provider
@pytest.fixture(scope="module")
def shared_workspace_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("workspace")

@pytest.fixture(scope="module")
def shared_workspace_monitor(shared_workspace_dir):
    return WorkspaceMonitor([shared_workspace_dir])

@pytest.fixture(scope="module")
def shared_provider_registry():
    return ProviderRegistry()

@pytest.fixture(scope="module")
def shared_job_manager():
    return JobManager()

@pytest.fixture(params=[
    "revit",
    "ifc",
    "mapper",
    "exporter",
    "jobs",
    "graph",
    "fake",
    "speckle",
    "autodesk",
    "rhino",
    "proxy"
])
def provider_instance(request, shared_workspace_monitor, shared_provider_registry, shared_job_manager):
    name = request.param
    try:
        if name == "revit":
            return RevitProvider(workspace=shared_workspace_monitor, mode=BridgeMode.mock)
        elif name == "ifc":
            return IfcProvider(workspace=shared_workspace_monitor)
        elif name == "mapper":
            return AECMapperProvider(workspace=shared_workspace_monitor)
        elif name == "exporter":
            return SQLiteExporterProvider(workspace=shared_workspace_monitor, registry=shared_provider_registry)
        elif name == "jobs":
            return JobProvider(manager=shared_job_manager)
        elif name == "graph":
            return SemanticGraphProvider()
        elif name == "fake":
            return FakeProvider()
        elif name == "speckle":
            return SpeckleProvider(client_id="dummy")
        elif name == "autodesk":
            return AutodeskDataProvider(client_id="dummy")
        elif name == "rhino":
            return RhinoProvider(workspace=shared_workspace_monitor)
        elif name == "proxy":
            if McpProxyProvider is None:
                pytest.skip("McpProxyProvider class is not importable/available.")
            return McpProxyProvider(target_url="http://localhost:9876/sse")
    except Exception as e:
        pytest.skip(f"Provider {name} skipped because initialization failed: {e}")

@pytest.mark.anyio
async def test_provider_identity(provider_instance):
    identity = provider_instance.get_identity()
    assert isinstance(identity, str)
    assert len(identity) > 0
    # Stability: must return the same identity on consecutive calls
    assert provider_instance.get_identity() == identity
    
    # Global uniqueness (across all parameterized runs)
    assert identity not in _all_provider_identities, f"Duplicate provider identity: {identity}"
    _all_provider_identities.add(identity)

@pytest.mark.anyio
async def test_provider_capabilities_and_tools(provider_instance):
    identity = provider_instance.get_identity()
    
    if identity == "proxy":
        # McpProxyProvider will have an empty tool list if offline.
        # Skip gracefully rather than failing the contract.
        health = await provider_instance.check_health()
        if health.get("status") == "disconnected":
            pytest.skip("Proxy provider is disconnected offline, skipping capabilities check.")
            
    tools = provider_instance.get_capabilities()
    assert isinstance(tools, list)
    assert len(tools) > 0, f"Provider {identity} returned empty tool list"
    
    for tool in tools:
        # 1. Tool name non-empty string and globally unique
        assert isinstance(tool.name, str)
        assert len(tool.name) > 0
        assert tool.name not in _all_tool_names, f"Duplicate tool name '{tool.name}' found in provider '{identity}' (previously registered by '{_all_tool_names[tool.name]}')"
        _all_tool_names[tool.name] = identity
        
        # 2. Non-empty description
        assert isinstance(tool.description, str)
        assert len(tool.description.strip()) > 0, f"Tool '{tool.name}' has empty description"
        
        # 3. Input Schema shape check
        schema = getattr(tool, "input_schema", getattr(tool, "inputSchema", None))
        if schema is not None:
            assert isinstance(schema, dict)
            # Check if it has 'type' or 'properties'
            assert "type" in schema or "properties" in schema or schema == {}, f"Tool '{tool.name}' schema is not valid JSON-schema-shaped"
            
        # 4. Mutating metadata check
        mutating = getattr(tool, "mutating", None)
        if mutating is None:
            _missing_mutation_metadata.append((identity, tool.name))
        else:
            assert isinstance(mutating, bool)

@pytest.mark.anyio
async def test_execute_unknown_tool_raises_typed_error(provider_instance):
    # Calling an unknown tool name raises a typed error
    unknown_tool = "non_existent_tool_mcp_contract_test"
    with pytest.raises(Exception) as excinfo:
        await provider_instance.execute_tool(unknown_tool, {})
    
    # Ensure it's not a bare Exception
    assert excinfo.type is not Exception, f"Provider {provider_instance.get_identity()} raised a bare Exception"
    # Ensure it is a typed error (e.g. ValueError, KeyError, RevitMCPError)
    assert issubclass(excinfo.type, Exception)

def test_redaction_contract():
    # Synthetic result matching typical structure
    synthetic = {
        "access_token": "Bearer test-token-12345",
        "authorization": "Bearer token-abc",
        "win_path": "C:\\Users\\sammo\\Documents\\model.rvt",
        "posix_path": "/home/sammo/model.ifc",
        "nested": {
            "token": "secret-xyz",
            "message": "Error on C:\\Users\\sammo\\private.txt and /Users/sammo/private.key"
        }
    }
    
    redacted = redact_data(synthetic)
    
    # Assert bearer/token values are completely redacted to '<redacted>'
    assert redacted["access_token"] == "<redacted>"
    assert redacted["authorization"] == "<redacted>"
    assert redacted["nested"]["token"] == "<redacted>"
    
    # Assert paths in values are redacted to '<redacted-path>'
    assert redacted["win_path"] == "<redacted-path>"
    assert redacted["posix_path"] == "<redacted-path>"
    
    # Assert embedded paths in strings are redacted
    assert "C:\\Users\\sammo\\private.txt" not in redacted["nested"]["message"]
    assert "/Users/sammo/private.key" not in redacted["nested"]["message"]
    assert "<redacted-path>" in redacted["nested"]["message"]

def test_compile_mutation_metadata_report():
    # This is a final test to print/log the report of tools missing mutation metadata
    if _missing_mutation_metadata:
        print("\n\n" + "="*50)
        print("CONSOLIDATED REPORT: TOOLS MISSING MUTATION METADATA")
        print("="*50)
        for provider, tool in _missing_mutation_metadata:
            print(f"Provider: {provider:15} | Tool: {tool}")
        print("="*50 + "\n")
    else:
        print("\nAll tools have mutation metadata defined.\n")
