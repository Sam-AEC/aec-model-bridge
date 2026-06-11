import os
import pytest
from pathlib import Path
from typing import Dict, Any

import ifcopenshell
from revit_mcp_server.config import BridgeMode, Config
from revit_mcp_server.providers import ProviderRegistry, RevitProvider, IfcProvider, FakeProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor


def create_sample_ifc(path: Path):
    """Programmatically generate a minimal valid IFC2X3 file for testing."""
    file = ifcopenshell.file(schema="IFC2X3")
    
    project = file.create_entity("IfcProject", GlobalId="0000000000000000000001", Name="Test Project")
    site = file.create_entity(
        "IfcSite", 
        GlobalId="0000000000000000000002", 
        Name="Test Site", 
        RefLatitude=(52, 30, 0, 0), 
        RefLongitude=(4, 45, 0, 0), 
        RefElevation=10.0
    )
    building = file.create_entity("IfcBuilding", GlobalId="0000000000000000000003", Name="Test Building")
    storey = file.create_entity("IfcBuildingStorey", GlobalId="0000000000000000000004", Name="Test Storey")
    
    file.create_entity("IfcRelAggregates", GlobalId="0000000000000000000005", RelatingObject=project, RelatedObjects=[site])
    file.create_entity("IfcRelAggregates", GlobalId="0000000000000000000006", RelatingObject=site, RelatedObjects=[building])
    file.create_entity("IfcRelAggregates", GlobalId="0000000000000000000007", RelatingObject=building, RelatedObjects=[storey])
    
    # Create a wall
    wall = file.create_entity("IfcWall", GlobalId="0x1234567890abcdef123456", Name="Sample Wall")
    file.create_entity("IfcRelContainedInSpatialStructure", GlobalId="0000000000000000000008", RelatingStructure=storey, RelatedElements=[wall])
    
    # Add some properties to the wall
    pset = file.create_entity("IfcPropertySet", GlobalId="0000000000000000000009", Name="Pset_WallCommon")
    prop = file.create_entity("IfcPropertySingleValue", Name="LoadBearing", NominalValue=file.create_entity("IfcBoolean", True))
    pset.HasProperties = [prop]
    file.create_entity("IfcRelDefinesByProperties", GlobalId="0000000000000000000010", RelatedObjects=[wall], RelatingPropertyDefinition=pset)
    
    file.write(str(path))


def test_provider_registry():
    registry = ProviderRegistry()
    fake = FakeProvider()
    registry.register(fake)
    
    assert registry.get_provider("fake") is fake
    assert len(registry.get_all_providers()) == 1
    assert len(registry.get_all_tools()) == 1
    assert registry.get_all_tools()[0].name == "fake_tool"
    
    provider = registry.lookup_tool_provider("fake_tool")
    assert provider is fake


@pytest.mark.anyio
async def test_revit_provider_mock_mode(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RevitProvider(workspace=workspace, mode=BridgeMode.mock)
    
    health = await provider.check_health()
    assert health["status"] == "healthy"
    
    capabilities = provider.get_capabilities()
    assert len(capabilities) >= 100
    
    # Verify execution of legacy dot notation
    res1 = await provider.execute_tool("revit.health", {"request_id": "test-1"})
    assert res1["status"] == "healthy"
    
    # Verify execution of underscore notation
    res2 = await provider.execute_tool("revit_health", {"request_id": "test-2"})
    assert res2["status"] == "healthy"


@pytest.mark.anyio
async def test_ifc_provider_tools(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = IfcProvider(workspace=workspace)
    
    # Generate fixture file
    ifc_file_path = tmp_path / "model.ifc"
    create_sample_ifc(ifc_file_path)
    
    # Health
    health = await provider.execute_tool("ifc_health", {})
    assert health["status"] == "healthy"
    
    # Metadata
    meta = await provider.execute_tool("ifc_get_metadata", {"ifc_path": str(ifc_file_path)})
    assert meta["schema"] == "IFC2X3"
    assert meta["project_name"] == "Test Project"
    assert "georeferencing" in meta
    assert meta["georeferencing"]["latitude"] is not None
    
    # Spatial structure
    spatial = await provider.execute_tool("ifc_get_spatial_structure", {"ifc_path": str(ifc_file_path)})
    struct = spatial["spatial_structure"]
    assert struct["name"] == "Test Project"
    assert len(struct["children"]) == 1  # Site
    assert struct["children"][0]["name"] == "Test Site"
    
    # Query elements
    query = await provider.execute_tool("ifc_query_elements", {
        "ifc_path": str(ifc_file_path),
        "ifc_class": "IfcWall"
    })
    elements = query["elements"]
    assert len(elements) == 1
    assert elements[0]["name"] == "Sample Wall"
    assert elements[0]["guid"] == "0x1234567890abcdef123456"
    
    # Properties
    props = await provider.execute_tool("ifc_get_properties", {
        "ifc_path": str(ifc_file_path),
        "element_id": "0x1234567890abcdef123456"
    })
    assert "property_sets" in props
    assert "Pset_WallCommon" in props["property_sets"]
    assert props["property_sets"]["Pset_WallCommon"]["LoadBearing"] is True
    
    # Bounding Box
    bbox = await provider.execute_tool("ifc_get_bounding_box", {
        "ifc_path": str(ifc_file_path),
        "element_id": "0x1234567890abcdef123456"
    })
    assert "element" in bbox
    
    # Validation
    val = await provider.execute_tool("ifc_validate", {"ifc_path": str(ifc_file_path)})
    assert "is_valid" in val


@pytest.mark.anyio
async def test_ifc_provider_path_traversal_protection(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = IfcProvider(workspace=workspace)
    
    # File outside workspace
    outside_dir = tmp_path.parent / "outside"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "unauthorized.ifc"
    
    with pytest.raises(Exception) as exc:
        await provider.execute_tool("ifc_get_metadata", {"ifc_path": str(outside_file)})
    
    # Pydantic or WorkspaceMonitor raises ValueError or related custom errors for paths outside workspace
    assert "outside the allowed workspace" in str(exc.value).lower()
