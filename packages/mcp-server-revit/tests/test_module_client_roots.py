"""Client roots narrow the paths these modules accept; with no roots nothing changes."""
import json
import os
from pathlib import Path

import pytest

from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.modules.bcf_exchange import module as bcf
from revit_mcp_server.modules.ifc_diff import module as ifc_diff
from revit_mcp_server.modules.naming_checker import module as naming
from revit_mcp_server.modules.qaqc_checker import module as qaqc
from revit_mcp_server.modules.recipe_runner import module as recipes
from revit_mcp_server.security.workspace import CLIENT_ROOTS, WorkspaceMonitor

IFC = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
RECIPE = "id: r\nname: r\nsteps: []\n"


@pytest.fixture
def tree(tmp_path):
    ws = tmp_path / "ws"
    (ws / "a").mkdir(parents=True)
    (ws / "b").mkdir()
    for folder in (ws / "a", ws / "b"):
        (folder / "f.ifc").write_text(IFC)
        (folder / "f.bcfzip").write_bytes(b"x")
        (folder / "f.json").write_text(json.dumps({"rules": []}))
        (folder / "f.yaml").write_text(RECIPE)
    return ws


@pytest.fixture
def narrowed(tree):
    token = CLIENT_ROOTS.set((os.path.realpath(tree / "a"),))
    yield WorkspaceMonitor([tree])
    CLIENT_ROOTS.reset(token)


def _paths(tree):
    return tree / "a", tree / "b"


def test_bcf_refuses_outside_the_root(tree, narrowed):
    inside, outside = _paths(tree)
    with pytest.raises(bcf.BcfError, match="outside the allowed workspace"):
        bcf.BcfExchangeModule().import_bcf(str(outside / "f.bcfzip"), workspace=narrowed)
    with pytest.raises(bcf.BcfError, match="not a valid zip"):  # passed the path check, failed on content
        bcf.BcfExchangeModule().import_bcf(str(inside / "f.bcfzip"), workspace=narrowed)


def test_bcf_relative_paths_start_in_the_root(tree, narrowed):
    assert bcf._resolve_in_workspace("f.bcfzip", narrowed) == Path(os.path.realpath(tree / "a" / "f.bcfzip"))


def test_bcf_without_roots_reaches_both_folders(tree):
    monitor = WorkspaceMonitor([tree])
    for folder in _paths(tree):
        assert bcf._resolve_in_workspace(str(folder / "f.bcfzip"), monitor).is_file()


def test_ifc_diff_refuses_outside_the_root(tree, narrowed):
    inside, outside = _paths(tree)
    with pytest.raises(WorkspaceViolation, match="outside the allowed workspace"):
        ifc_diff._input_file(narrowed, str(outside / "f.ifc"), "older_ifc_path")
    assert ifc_diff._input_file(narrowed, str(inside / "f.ifc"), "older_ifc_path").is_file()
    assert ifc_diff._input_file(narrowed, "f.ifc", "older_ifc_path").parent == Path(os.path.realpath(inside))


def test_naming_checker_refuses_outside_the_root(tree, narrowed):
    inside, outside = _paths(tree)
    module = naming.NamingCheckerModule()
    with pytest.raises(ValueError, match="inside the workspace"):
        module._load_convention_file(str(outside / "f.json"), narrowed)
    assert module._load_convention_file(str(inside / "f.json"), narrowed) == {"rules": []}
    assert module._load_convention_file("f.json", narrowed) == {"rules": []}


def test_recipe_runner_refuses_outside_the_root(tree, narrowed):
    inside, outside = _paths(tree)
    with pytest.raises(ValueError, match="outside the allowed workspace"):
        recipes._load_recipe(str(outside / "f.yaml"), narrowed)
    assert recipes._load_recipe(str(inside / "f.yaml"), narrowed)["id"] == "r"
    assert recipes._load_recipe("f.yaml", narrowed)["id"] == "r"


def test_recipe_runner_without_roots_reaches_both_folders(tree):
    monitor = WorkspaceMonitor([tree])
    for folder in _paths(tree):
        assert recipes._load_recipe(str(folder / "f.yaml"), monitor)["id"] == "r"


def test_roots_that_overlap_nothing_refuse_everything(tree, tmp_path):
    token = CLIENT_ROOTS.set((os.path.realpath(tmp_path / "elsewhere"),))
    try:
        monitor = WorkspaceMonitor([tree])
        with pytest.raises(WorkspaceViolation):
            ifc_diff._input_file(monitor, str(tree / "a" / "f.ifc"), "older_ifc_path")
        with pytest.raises(bcf.BcfError):
            bcf._resolve_in_workspace(str(tree / "a" / "f.bcfzip"), monitor)
        with pytest.raises(ValueError):
            recipes._load_recipe("f.yaml", monitor)
    finally:
        CLIENT_ROOTS.reset(token)


class _NarrowedOnly:
    """A workspace that narrows but has no assert_in_workspace: the qaqc fallback path."""

    def __init__(self, allowed, effective):
        self.allowed_directories = [allowed]
        self._effective = effective

    def effective_directories(self):
        return [self._effective]


def test_qaqc_fallback_uses_the_narrowed_directories(tree):
    inside, outside = _paths(tree)
    workspace = _NarrowedOnly(tree, inside)
    with pytest.raises(WorkspaceViolation):
        qaqc._assert_in_workspace(workspace, outside / "f.json")
    assert qaqc._assert_in_workspace(workspace, inside / "f.json") == (inside / "f.json").resolve()
