"""clash_triage_import_clash_report: Navisworks XML and BCF clash reports (#180). Fixtures only."""
import importlib
import zipfile

import pytest

mod_ = importlib.import_module("revit_mcp_server.modules.clash_triage.module")

WALL = "c0326e0e-473d-4952-b8ec-f23696541f43-wall-1"
DOOR = "c0326e0e-473d-4952-b8ec-f23696541f44-door-1"


class WS:
    def __init__(self, p):
        self.allowed_directories = [p]


def _obj(guid=None, name="Item", layer="Level 1", element_id=None, attr="IfcGUID"):
    attrs = ""
    if guid:
        attrs += f"<objectattribute><name>{attr}</name><value>{guid}</value></objectattribute>"
    if element_id:
        attrs += f"<objectattribute><name>Element ID</name><value>{element_id}</value></objectattribute>"
    return (f"<clashobject>{attrs}<layer>{layer}</layer>"
            f"<smarttags><smarttag><name>Item Name</name><value>{name}</value></smarttag></smarttags></clashobject>")


def _result(guid, a, b, status="new"):
    return (f'<clashresult name="Clash {guid}" guid="{guid}" status="{status}" distance="-0.040">'
            f"<clashobjects>{a}{b}</clashobjects></clashresult>")


def _xml(*results):
    return ('<?xml version="1.0" encoding="UTF-8"?><exchange><batchtest name="b"><clashtests>'
            '<clashtest name="Walls vs Doors"><clashresults>' + "".join(results) +
            "</clashresults></clashtest></clashtests></batchtest></exchange>")


@pytest.fixture
def ws(tmp_path):
    return WS(tmp_path)


def _run(ws, name, content, **kw):
    path = ws.allowed_directories[0] / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return mod_.ClashTriageModule().import_clash_report(report_path=name, workspace=ws, record_issues=False, **kw)


def test_navisworks_xml_groups_by_pair_and_level(ws):
    out = _run(ws, "report.xml", _xml(
        _result("g1", _obj(WALL, "Wall"), _obj(DOOR, "Door")),
        _result("g2", _obj(DOOR, "Door"), _obj(WALL, "Wall")),
        _result("g3", _obj(WALL, "Wall", "Level 2"), _obj(DOOR, "Door", "Level 2")),
    ))
    assert out["format"] == "navisworks_xml" and out["total_clashes"] == 3
    groups = sorted((g["level"], g["clash_count"], tuple(sorted(g["clash_guids"]))) for g in out["groups"])
    assert groups == [("Level 1", 2, ("g1", "g2")), ("Level 2", 1, ("g3",))]
    assert all(sorted(g["element_uids"]) == sorted([WALL, DOOR]) for g in out["groups"])
    assert out["unmatched"] == []
    assert out["read_only"] is True and out["fix_plans"] == []


def test_unmatched_items_are_reported_not_dropped(ws):
    out = _run(ws, "report.xml", _xml(
        _result("g1", _obj(WALL, "Wall"), _obj("no-such-guid", "Ghost")),
        _result("g2", _obj(None, "Pipe", element_id="200"), _obj(DOOR, "Door")),
    ))
    assert out["total_clashes"] == 2
    assert sorted(u["clash_guid"] for u in out["unmatched"]) == ["g1", "g2"]
    by = {u["clash_guid"]: u for u in out["unmatched"]}
    assert "Element ID" in by["g2"]["reason"]  # an element id alone is never matched
    assert sum(g["clash_count"] for g in out["groups"]) == 2


def test_bcf_topics_load_into_groups(ws):
    buf = ws.allowed_directories[0] / "issues.bcfzip"
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bcf.version", '<?xml version="1.0" encoding="UTF-8"?><Version VersionId="2.1"/>')
        for tid, comps in (("t1", [WALL, DOOR]), ("t2", [WALL])):
            zf.writestr(f"{tid}/markup.bcf", '<?xml version="1.0" encoding="UTF-8"?><Markup>'
                        f'<Topic Guid="{tid}" TopicStatus="Open"><Title>Clash {tid}</Title></Topic></Markup>')
            parts = "".join(f'<Component IfcGuid="{c}"/>' for c in comps)
            zf.writestr(f"{tid}/viewpoint.bcfv", '<?xml version="1.0" encoding="UTF-8"?><VisualizationInfo>'
                        f"<Components><Selection>{parts}</Selection></Components></VisualizationInfo>")
    out = mod_.ClashTriageModule().import_clash_report(report_path="issues.bcfzip", workspace=ws, record_issues=False)
    assert out["format"] == "bcf" and out["total_clashes"] == 2
    assert [g["clash_guids"] for g in out["groups"] if sorted(g["element_uids"]) == sorted([WALL, DOOR])] == [["t1"]]
    assert [u["clash_guid"] for u in out["unmatched"]] == ["t2"]


@pytest.mark.parametrize("name,content,match", [
    ("x.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><exchange/>', "DOCTYPE"),
    ("x.xml", "<exchange><clashtest>", "not valid XML"),
    ("x.xml", '<?xml version="1.0" encoding="UTF-8"?><exchange/>', "no clash results"),
    ("x.txt", "hello", ".xml or .bcfzip"),
])
def test_bad_reports_are_refused(ws, name, content, match):
    with pytest.raises(ValueError, match=match):
        _run(ws, name, content)


def test_paths_outside_the_workspace_are_refused(ws, tmp_path):
    with pytest.raises(ValueError):
        mod_.ClashTriageModule().import_clash_report(report_path="../outside.xml", workspace=ws)
