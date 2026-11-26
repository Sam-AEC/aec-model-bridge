from types import SimpleNamespace
from unittest.mock import MagicMock

import ifcopenshell
import pytest

from revit_mcp_server.providers import ifc as ifc_module
from revit_mcp_server.providers.ifc import IfcProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

# Every IFC tool reads a file; none may be gated as a write.
EXPECTED_MUTATING = {
    "ifc_health": False,
    "ifc_get_metadata": False,
    "ifc_get_spatial_structure": False,
    "ifc_query_elements": False,
    "ifc_get_properties": False,
    "ifc_get_bounding_box": False,
    "ifc_validate": False,
}

WALL_GUID = "2O2Fr$t4X7Zf8NOew3FNld"
OTHER_GUID = "3O2Fr$t4X7Zf8NOew3FNld"


def _guid(n):
    return f"{n:022d}"


def _write(model, path):
    model.write(str(path))
    return path


def _model(schema="IFC4"):
    return ifcopenshell.file(schema=schema)


@pytest.fixture
def provider(tmp_path):
    return IfcProvider(workspace=WorkspaceMonitor([tmp_path]))


@pytest.fixture
def rich_ifc(tmp_path):
    f = _model()
    project = f.create_entity("IfcProject", GlobalId=_guid(1), Name="Proj")
    site = f.create_entity(
        "IfcSite",
        GlobalId=_guid(2),
        Name="Site",
        RefLatitude=(52, 30, 0, 0),
        RefLongitude=(4, 45, 0, 0),
        RefElevation=3.5,
    )
    building = f.create_entity("IfcBuilding", GlobalId=_guid(3), Name="Bld")
    storey = f.create_entity("IfcBuildingStorey", GlobalId=_guid(4), Name="L1")
    f.create_entity("IfcRelAggregates", GlobalId=_guid(5), RelatingObject=project, RelatedObjects=[site])
    f.create_entity("IfcRelAggregates", GlobalId=_guid(6), RelatingObject=site, RelatedObjects=[building])
    f.create_entity("IfcRelAggregates", GlobalId=_guid(7), RelatingObject=building, RelatedObjects=[storey])

    wall = f.create_entity("IfcWall", GlobalId=WALL_GUID, Name="Brick Wall")
    other = f.create_entity("IfcWall", GlobalId=OTHER_GUID, Name="Glass Wall")
    door = f.create_entity("IfcDoor", GlobalId=_guid(8), Name=None)
    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(9),
        RelatingStructure=storey,
        RelatedElements=[wall, other, door],
    )

    pset = f.create_entity("IfcPropertySet", GlobalId=_guid(10), Name="Pset_WallCommon")
    pset.HasProperties = [
        f.create_entity("IfcPropertySingleValue", Name="FireRating", NominalValue=f.create_entity("IfcLabel", "EI60")),
        f.create_entity("IfcPropertySingleValue", Name="Empty", NominalValue=None),
        f.create_entity(
            "IfcPropertyBoundedValue",
            Name="Range",
            UpperBoundValue=f.create_entity("IfcReal", 2.0),
        ),
        f.create_entity("IfcPropertyReferenceValue", Name="Ref"),
    ]
    f.create_entity(
        "IfcRelDefinesByProperties", GlobalId=_guid(11), RelatedObjects=[wall], RelatingPropertyDefinition=pset
    )
    qset = f.create_entity("IfcElementQuantity", GlobalId=_guid(12), Name="Qto_WallBaseQuantities")
    qset.Quantities = [
        f.create_entity("IfcQuantityLength", Name="Length", LengthValue=4.0),
        f.create_entity("IfcQuantityArea", Name="Area", AreaValue=8.0),
        f.create_entity("IfcQuantityVolume", Name="Volume", VolumeValue=1.6),
        f.create_entity("IfcQuantityCount", Name="Count", CountValue=2.0),
        f.create_entity("IfcQuantityWeight", Name="Weight", WeightValue=90.0),
        f.create_entity("IfcQuantityTime", Name="Ignored", TimeValue=1.0),
    ]
    f.create_entity(
        "IfcRelDefinesByProperties", GlobalId=_guid(13), RelatedObjects=[wall], RelatingPropertyDefinition=qset
    )
    # A non-pset, non-quantity definition is skipped.
    other_def = f.create_entity("IfcPropertySetTemplate", GlobalId=_guid(14), Name="Template")
    f.create_entity(
        "IfcRelDefinesByProperties", GlobalId=_guid(15), RelatedObjects=[other], RelatingPropertyDefinition=other_def
    )

    # Header, units and map conversion
    f.header.file_name.name = "model.ifc"
    f.header.file_name.author = ("Ann",)
    mm = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    area = f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
    inch = f.create_entity(
        "IfcConversionBasedUnit",
        UnitType="LENGTHUNIT",
        Name="INCH",
        ConversionFactor=f.create_entity(
            "IfcMeasureWithUnit", ValueComponent=f.create_entity("IfcReal", 25.4), UnitComponent=mm
        ),
    )
    derived = f.create_entity("IfcDerivedUnit", UnitType="USERDEFINED")
    f.create_entity("IfcUnitAssignment", Units=[mm, area, inch, derived])
    f.create_entity(
        "IfcMapConversion",
        Eastings=100.0,
        Northings=200.0,
        OrthogonalHeight=5.0,
        XAxisAbscissa=1.0,
        XAxisOrdinate=0.0,
        Scale=1.0,
    )
    return _write(f, tmp_path / "rich.ifc")


def _args(path, **extra):
    return {"ifc_path": str(path), **extra}


def test_identity(provider):
    assert provider.get_identity() == "ifc"


def test_expected_table_covers_every_tool(provider):
    assert {t.name for t in provider.get_capabilities()} == set(EXPECTED_MUTATING)


@pytest.mark.parametrize("name, expected", sorted(EXPECTED_MUTATING.items()))
def test_is_mutating_matches_expected_table(provider, name, expected):
    tools = {t.name: t for t in provider.get_capabilities()}
    assert tools[name].is_mutating is expected
    assert tools[name].destructive is False


@pytest.mark.anyio
async def test_health_reports_versions(provider):
    result = await provider.execute_tool("ifc_health", {})
    assert result["status"] == "healthy"
    assert result["provider"] == "ifc"
    assert result["ifcopenshell_version"] == ifcopenshell.__version__
    assert isinstance(result["has_geom"], bool)
    assert isinstance(result["has_validate"], bool)


@pytest.mark.anyio
async def test_health_reports_missing_submodules(provider, monkeypatch):
    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: False)
    monkeypatch.setattr(ifc_module, "_ifcopenshell", lambda: SimpleNamespace())
    result = await provider.check_health()
    assert result["has_geom"] is False
    assert result["has_validate"] is False
    assert result["ifcopenshell_version"] == "0.7.0"


def test_has_submodule():
    assert ifc_module._has_submodule("util") is True
    assert ifc_module._has_submodule("no_such_submodule_xyz") is False


@pytest.mark.anyio
async def test_shutdown_is_a_noop(provider):
    assert await provider.shutdown() is None


@pytest.mark.anyio
async def test_file_tools_require_ifc_path(provider):
    with pytest.raises(ValueError, match="'ifc_path' is required"):
        await provider.execute_tool("ifc_get_metadata", {})


@pytest.mark.anyio
async def test_path_outside_workspace_is_refused(provider, tmp_path_factory):
    outside = _write(_model(), tmp_path_factory.mktemp("outside") / "o.ifc")
    with pytest.raises(Exception, match="outside the allowed workspace"):
        await provider.execute_tool("ifc_get_metadata", _args(outside))


@pytest.mark.anyio
async def test_missing_file_is_refused(provider, tmp_path):
    with pytest.raises(FileNotFoundError, match="IFC file not found"):
        await provider.execute_tool("ifc_get_metadata", _args(tmp_path / "missing.ifc"))


@pytest.mark.anyio
async def test_unreadable_file_reports_open_failure(provider, tmp_path):
    bad = tmp_path / "bad.ifc"
    bad.write_text("not an ifc file")
    with pytest.raises(ValueError, match="Failed to open IFC file"):
        await provider.execute_tool("ifc_get_metadata", _args(bad))


@pytest.mark.anyio
async def test_unknown_tool_with_valid_file_is_refused(provider, rich_ifc):
    with pytest.raises(ValueError, match="Unknown IFC tool 'ifc_nope'"):
        await provider.execute_tool("ifc_nope", _args(rich_ifc))


@pytest.mark.anyio
async def test_metadata(provider, rich_ifc):
    meta = await provider.execute_tool("ifc_get_metadata", _args(rich_ifc))
    assert meta["schema"] == "IFC4"
    assert meta["project_name"] == "Proj"
    assert meta["project_guid"] == _guid(1)
    assert meta["header"]["name"] == "model.ifc"
    assert meta["header"]["author"] == ("Ann",)
    assert meta["units"][0] == {"type": "LENGTHUNIT", "name": "MILLIMETRE"}
    assert meta["units"][1] == {"type": "AREAUNIT", "name": "SQUARE_METRE"}
    assert meta["units"][2]["name"] == "INCH"
    assert meta["units"][2]["conversion_factor"] == 25.4
    assert len(meta["units"]) == 3
    geo = meta["georeferencing"]
    assert geo["latitude"] == pytest.approx(52.5)
    assert geo["longitude"] == pytest.approx(4.75)
    assert geo["elevation"] == 3.5
    assert geo["map_conversion"]["eastings"] == 100.0
    assert geo["map_conversion"]["scale"] == 1.0


@pytest.mark.anyio
async def test_metadata_of_empty_file(provider, tmp_path):
    empty = _write(_model("IFC2X3"), tmp_path / "empty.ifc")
    meta = await provider.execute_tool("ifc_get_metadata", _args(empty))
    assert meta["schema"] == "IFC2X3"
    assert meta["project_name"] == "N/A"
    assert meta["project_guid"] == "N/A"
    assert meta["units"] == []
    assert meta["georeferencing"] == {}


def test_metadata_tolerates_schema_without_map_conversion(provider):
    f = MagicMock()
    f.schema = "IFC2X3"
    f.header = None

    def by_type(name):
        if name == "IfcMapConversion":
            raise RuntimeError("not in schema")
        return []

    f.by_type.side_effect = by_type
    assert provider._get_metadata(f)["georeferencing"] == {}


def test_metadata_unit_without_conversion_factor(provider):
    unit = MagicMock(spec=["is_a", "UnitType", "Name"])
    unit.is_a.side_effect = lambda c: c == "IfcConversionBasedUnit"
    unit.UnitType = "LENGTHUNIT"
    unit.Name = "FOOT"
    assignment = SimpleNamespace(Units=[unit])
    f = MagicMock()
    f.schema = "IFC4"
    f.header = None
    f.by_type.side_effect = lambda n: [assignment] if n == "IfcUnitAssignment" else []
    assert provider._get_metadata(f)["units"] == [{"type": "LENGTHUNIT", "name": "FOOT", "conversion_factor": None}]


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ((52, 30, 36, 0), 52 + 30 / 60 + 36 / 3600),
        ((52,), 52.0),
        ([52, 30], 52.5),
        ((52, 30, 0, 500000), 52.5 + 0.5 / 3600),
        (("x", 1), "('x', 1)"),
        ((), "()"),
        (12, 12.0),
        (1.5, 1.5),
        ("N", "N"),
    ],
)
def test_parse_coord_tuple(provider, value, expected):
    result = provider._parse_coord_tuple(value)
    if isinstance(expected, float):
        assert result == pytest.approx(expected)
    else:
        assert result == expected


@pytest.mark.anyio
async def test_spatial_structure(provider, rich_ifc):
    result = await provider.execute_tool("ifc_get_spatial_structure", _args(rich_ifc))
    root = result["spatial_structure"]
    assert (root["class"], root["name"]) == ("IfcProject", "Proj")
    storey = root["children"][0]["children"][0]["children"][0]
    assert (storey["class"], storey["name"]) == ("IfcBuildingStorey", "L1")
    assert storey["contained_elements_summary"] == {"IfcWall": 2, "IfcDoor": 1}
    assert "contained_elements_summary" not in root


@pytest.mark.anyio
async def test_spatial_structure_without_project(provider, tmp_path):
    empty = _write(_model(), tmp_path / "empty.ifc")
    result = await provider.execute_tool("ifc_get_spatial_structure", _args(empty))
    assert result == {"message": "No IfcProject found."}


@pytest.mark.anyio
async def test_query_by_class_and_default_class(provider, rich_ifc):
    walls = await provider.execute_tool("ifc_query_elements", _args(rich_ifc, ifc_class="IfcWall"))
    assert {e["name"] for e in walls["elements"]} == {"Brick Wall", "Glass Wall"}
    assert all(e["class"] == "IfcWall" for e in walls["elements"])
    products = await provider.execute_tool("ifc_query_elements", _args(rich_ifc))
    assert {e["class"] for e in products["elements"]} >= {"IfcWall", "IfcDoor", "IfcSite"}
    door = next(e for e in products["elements"] if e["class"] == "IfcDoor")
    assert door["name"] == ""


@pytest.mark.anyio
async def test_query_by_guid(provider, rich_ifc):
    hit = await provider.execute_tool("ifc_query_elements", _args(rich_ifc, guid=WALL_GUID))
    assert [e["guid"] for e in hit["elements"]] == [WALL_GUID]
    miss = await provider.execute_tool("ifc_query_elements", _args(rich_ifc, guid="1" * 22))
    assert miss["elements"] == []
    assert "No element found" in miss["message"]


@pytest.mark.anyio
async def test_query_name_filter_is_case_insensitive_and_skips_unnamed(provider, rich_ifc):
    result = await provider.execute_tool(
        "ifc_query_elements", _args(rich_ifc, ifc_class="IfcProduct", name_filter="GLASS")
    )
    assert [e["name"] for e in result["elements"]] == ["Glass Wall"]


@pytest.mark.anyio
async def test_query_property_filter(provider, rich_ifc):
    by_name = await provider.execute_tool(
        "ifc_query_elements", _args(rich_ifc, ifc_class="IfcWall", property_name="firerating")
    )
    assert [e["guid"] for e in by_name["elements"]] == [WALL_GUID]
    by_value = await provider.execute_tool(
        "ifc_query_elements",
        _args(rich_ifc, ifc_class="IfcWall", property_name="FireRating", property_value="ei60"),
    )
    assert [e["guid"] for e in by_value["elements"]] == [WALL_GUID]
    wrong_value = await provider.execute_tool(
        "ifc_query_elements",
        _args(rich_ifc, ifc_class="IfcWall", property_name="FireRating", property_value="EI90"),
    )
    assert wrong_value["elements"] == []
    unknown = await provider.execute_tool(
        "ifc_query_elements", _args(rich_ifc, ifc_class="IfcWall", property_name="Nope")
    )
    assert unknown["elements"] == []


@pytest.mark.anyio
async def test_query_rejects_invalid_class(provider, rich_ifc):
    with pytest.raises(ValueError, match="Invalid IFC class 'IfcNotAClass'"):
        await provider.execute_tool("ifc_query_elements", _args(rich_ifc, ifc_class="IfcNotAClass"))


@pytest.mark.anyio
async def test_query_truncates_at_200(provider, tmp_path):
    f = _model()
    for i in range(205):
        f.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name=f"W{i}")
    path = _write(f, tmp_path / "many.ifc")
    result = await provider.execute_tool("ifc_query_elements", _args(path, ifc_class="IfcWall"))
    assert len(result["elements"]) == 200
    assert result["truncated"] is True
    assert "first 200" in result["message"]


@pytest.mark.anyio
async def test_properties_by_guid_and_express_id(provider, rich_ifc):
    by_guid = await provider.execute_tool("ifc_get_properties", _args(rich_ifc, element_id=WALL_GUID))
    assert by_guid["element"]["name"] == "Brick Wall"
    assert by_guid["attributes"]["Name"] == "Brick Wall"
    psets = by_guid["property_sets"]["Pset_WallCommon"]
    assert psets["FireRating"] == "EI60"
    assert psets["Empty"] is None
    assert "Range" in psets and "Ref" in psets
    assert by_guid["quantities"]["Qto_WallBaseQuantities"] == {
        "Length": 4.0,
        "Area": 8.0,
        "Volume": 1.6,
        "Count": 2.0,
        "Weight": 90.0,
    }
    express_id = by_guid["element"]["id"]
    by_id = await provider.execute_tool("ifc_get_properties", _args(rich_ifc, element_id=str(express_id)))
    assert by_id["element"]["guid"] == WALL_GUID


@pytest.mark.anyio
async def test_properties_of_element_without_definitions(provider, rich_ifc):
    result = await provider.execute_tool("ifc_get_properties", _args(rich_ifc, element_id=OTHER_GUID))
    assert result["property_sets"] == {}
    assert result["quantities"] == {}


@pytest.mark.anyio
@pytest.mark.parametrize("element_id", [None, "", "no-such-guid", "999999"])
async def test_properties_unknown_element_is_refused(provider, rich_ifc, element_id):
    with pytest.raises(ValueError, match="Element not found"):
        await provider.execute_tool("ifc_get_properties", _args(rich_ifc, element_id=element_id))


def test_properties_survive_get_info_failure(provider):
    element = MagicMock()
    element.get_info.side_effect = RuntimeError("boom")
    element.IsDefinedBy = []
    element.id.return_value = 7
    element.GlobalId = "g"
    element.is_a.return_value = "IfcWall"
    element.Name = "W"
    f = MagicMock()
    f.by_id.return_value = element
    result = provider._get_properties(f, {"element_id": "7"})
    assert result["attributes"] == {}
    assert result["element"]["id"] == 7


def test_properties_attribute_filtering(provider):
    nested = SimpleNamespace(id=lambda: 1)
    element = MagicMock()
    element.get_info.return_value = {
        "id": 5,
        "type": "IfcWall",
        "Name": "W",
        "Tag": None,
        "Parts": [1],
        "Owner": nested,
        "Length": 3.0,
    }
    element.IsDefinedBy = []
    f = MagicMock()
    f.by_id.return_value = element
    assert provider._get_properties(f, {"element_id": 5})["attributes"] == {"Name": "W", "Length": 3.0}


def test_find_element_scans_for_malformed_guid(provider):
    root = SimpleNamespace(GlobalId="bad guid")
    f = MagicMock()
    f.by_id.side_effect = RuntimeError("no id")
    f.by_guid.side_effect = RuntimeError("invalid guid")
    f.by_type.return_value = [SimpleNamespace(), root]
    assert provider._find_element(f, "bad guid") is root
    f.by_type.assert_called_with("IfcRoot")


def test_find_element_returns_none_when_missing(provider):
    f = MagicMock()
    f.by_id.side_effect = RuntimeError("no id")
    f.by_guid.side_effect = RuntimeError("no guid")
    f.by_type.return_value = [SimpleNamespace(GlobalId="other")]
    assert provider._find_element(f, "x") is None
    assert provider._find_element(f, None) is None


def _fake_import(monkeypatch, name, module):
    real = ifc_module.importlib.import_module

    def fake(target, *a, **k):
        return module if target == name else real(target, *a, **k)

    monkeypatch.setattr(ifc_module.importlib, "import_module", fake)


@pytest.fixture
def placed_wall_ifc(tmp_path):
    f = _model()
    origin = f.create_entity("IfcCartesianPoint", Coordinates=(1.0, 2.0, 3.0))
    axis = f.create_entity("IfcAxis2Placement3D", Location=origin)
    placement = f.create_entity("IfcLocalPlacement", RelativePlacement=axis)
    f.create_entity("IfcWall", GlobalId=WALL_GUID, Name="Placed", ObjectPlacement=placement)
    return _write(f, tmp_path / "placed.ifc")


@pytest.mark.anyio
async def test_bounding_box_from_geometry_and_placement(provider, placed_wall_ifc, monkeypatch):
    geom = SimpleNamespace(
        settings=lambda: object(),
        create_shape=lambda settings, element: SimpleNamespace(
            geometry=SimpleNamespace(verts=(0.0, 0.0, 0.0, 1.0, 2.0, 3.0, 0.5, 1.0, 1.5))
        ),
    )
    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: True)
    _fake_import(monkeypatch, "ifcopenshell.geom", geom)
    result = await provider.execute_tool("ifc_get_bounding_box", _args(placed_wall_ifc, element_id=WALL_GUID))
    assert result["bounding_box"] == {"min": [0.0, 0.0, 0.0], "max": [1.0, 2.0, 3.0], "size": [1.0, 2.0, 3.0]}
    assert result["placement"]["matrix"][0][3] == pytest.approx(1.0)
    assert result["placement"]["matrix"][2][3] == pytest.approx(3.0)
    assert "bounding_box_error" not in result


@pytest.mark.anyio
async def test_bounding_box_geometry_without_vertices_stays_empty(provider, placed_wall_ifc, monkeypatch):
    geom = SimpleNamespace(
        settings=lambda: object(),
        create_shape=lambda s, e: SimpleNamespace(geometry=SimpleNamespace(verts=())),
    )
    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: True)
    _fake_import(monkeypatch, "ifcopenshell.geom", geom)
    result = await provider.execute_tool("ifc_get_bounding_box", _args(placed_wall_ifc, element_id=WALL_GUID))
    assert result["bounding_box"] is None


@pytest.mark.anyio
async def test_bounding_box_geometry_failure_is_reported(provider, placed_wall_ifc, monkeypatch):
    def boom(settings, element):
        raise RuntimeError("no shape")

    geom = SimpleNamespace(settings=lambda: object(), create_shape=boom)
    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: True)
    _fake_import(monkeypatch, "ifcopenshell.geom", geom)
    result = await provider.execute_tool("ifc_get_bounding_box", _args(placed_wall_ifc, element_id=WALL_GUID))
    assert result["bounding_box"] is None
    assert "Failed to compute geometry: no shape" in result["bounding_box_error"]


@pytest.mark.anyio
async def test_bounding_box_without_geom_module(provider, placed_wall_ifc, monkeypatch):
    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: False)
    result = await provider.execute_tool("ifc_get_bounding_box", _args(placed_wall_ifc, element_id=WALL_GUID))
    assert result["bounding_box"] is None
    assert "not available" in result["bounding_box_error"]


@pytest.mark.anyio
async def test_bounding_box_placement_failure_is_reported(provider, placed_wall_ifc, monkeypatch):
    def boom(placement):
        raise RuntimeError("bad placement")

    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: False)
    monkeypatch.setattr(ifcopenshell.util.placement, "get_local_placement", boom)
    result = await provider.execute_tool("ifc_get_bounding_box", _args(placed_wall_ifc, element_id=WALL_GUID))
    assert result["placement"] is None
    assert result["placement_error"] == "bad placement"


@pytest.mark.anyio
async def test_bounding_box_falls_back_to_bounding_box_representation(provider, tmp_path, monkeypatch):
    f = _model()
    corner = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    box = f.create_entity("IfcBoundingBox", Corner=corner, XDim=4.0, YDim=5.0, ZDim=6.0)
    skipped = f.create_entity("IfcShapeRepresentation", RepresentationType="Body", Items=[corner])
    rep = f.create_entity("IfcShapeRepresentation", RepresentationType="BoundingBox", Items=[corner, box])
    shape = f.create_entity("IfcProductDefinitionShape", Representations=[skipped, rep])
    f.create_entity("IfcWall", GlobalId=WALL_GUID, Name="Boxed", Representation=shape)
    path = _write(f, tmp_path / "boxed.ifc")
    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: False)
    result = await provider.execute_tool("ifc_get_bounding_box", _args(path, element_id=WALL_GUID))
    assert result["placement"] is None
    assert result["bounding_box"] == {
        "corner": (0.0, 0.0, 0.0),
        "x_dim": 4.0,
        "y_dim": 5.0,
        "z_dim": 6.0,
        "source": "IfcBoundingBox representation",
    }


@pytest.mark.anyio
async def test_bounding_box_unknown_element_is_refused(provider, rich_ifc):
    with pytest.raises(ValueError, match="Element not found: nope"):
        await provider.execute_tool("ifc_get_bounding_box", _args(rich_ifc, element_id="nope"))


@pytest.mark.anyio
async def test_validate_clean_file(provider, tmp_path):
    f = _model()
    f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new())
    path = _write(f, tmp_path / "ok.ifc")
    result = await provider.execute_tool("ifc_validate", _args(path))
    assert result == {"is_valid": True, "errors": [], "error_count": 0}


@pytest.mark.anyio
async def test_validate_without_validate_module(provider, rich_ifc, monkeypatch):
    monkeypatch.setattr(ifc_module, "_has_submodule", lambda name: False)
    result = await provider.execute_tool("ifc_validate", _args(rich_ifc))
    assert result["is_valid"] is False
    assert "not available" in result["errors"][0]["message"]


class _FakeLogger:
    def __init__(self, statements):
        self.statements = statements


def _fake_validate(statements, fail=False):
    def validate(model, logger):
        if fail:
            raise RuntimeError("engine down")

    return SimpleNamespace(json_logger=lambda: _FakeLogger(statements), validate=validate)


@pytest.mark.anyio
async def test_validate_keeps_only_errors_and_describes_instances(provider, rich_ifc, monkeypatch):
    class Instance:
        def id(self):
            return 12

        def is_a(self):
            return "IfcWall"

        def __str__(self):
            return "#12=IfcWall"

    instance = Instance()
    statements = [
        {"level": "warning", "message": "ignored"},
        {"level": "error", "message": "m" * 600, "instance": instance, "attribute": "Name"},
        {"level": "critical", "message": "no instance"},
        {"level": "error", "message": "plain instance", "instance": "text"},
    ]
    _fake_import(monkeypatch, "ifcopenshell.validate", _fake_validate(statements))
    result = await provider.execute_tool("ifc_validate", _args(rich_ifc))
    assert result["is_valid"] is False
    assert result["error_count"] == 3
    first, second, third = result["errors"]
    assert len(first["message"]) == 500
    assert (first["element_id"], first["element_class"], first["attribute"]) == (12, "IfcWall", "Name")
    assert second["instance"] is None and second["element_id"] is None
    assert third["instance"] == "text" and third["element_id"] is None


@pytest.mark.anyio
async def test_validate_caps_errors_at_100(provider, rich_ifc, monkeypatch):
    statements = [{"level": "error", "message": f"e{i}"} for i in range(150)]
    _fake_import(monkeypatch, "ifcopenshell.validate", _fake_validate(statements))
    result = await provider.execute_tool("ifc_validate", _args(rich_ifc))
    assert result["error_count"] == 100


@pytest.mark.anyio
async def test_validate_reports_engine_failure(provider, rich_ifc, monkeypatch):
    _fake_import(monkeypatch, "ifcopenshell.validate", _fake_validate([], fail=True))
    result = await provider.execute_tool("ifc_validate", _args(rich_ifc))
    assert result["is_valid"] is False
    assert "Validation engine execution failed: engine down" in result["errors"][0]["message"]
