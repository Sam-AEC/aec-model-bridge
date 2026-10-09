"""The draft-only parameter_manager tools run without an approved plan, so every
caller-supplied file name must stay inside the workspace."""
import json
import os

import pytest

from test_parameter_manager import MockWorkspace, ParameterManagerModule  # noqa: E402
from revit_mcp_server.security.workspace import WorkspaceMonitor


@pytest.fixture
def outside(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    secret = tmp_path / "outside"
    secret.mkdir()
    (secret / "secret.json").write_text(json.dumps({"elements": [{"uid": "u1", "params": {}}]}))
    (secret / "secret.csv").write_text("uid,Mark\nu1,X\n")
    return work, secret


@pytest.mark.parametrize("workspace_cls", [MockWorkspace, lambda p: WorkspaceMonitor([p])])
def test_snapshot_id_cannot_escape_workspace(outside, workspace_cls):
    work, _ = outside
    pm = ParameterManagerModule()
    ws = workspace_cls(work)
    (work / "snapshots").mkdir()
    with pytest.raises(Exception, match="outside the allowed workspace"):
        pm.plan_set_params(
            element_filter={}, param_updates={"Mark": "1"},
            snapshot_id="../../outside/secret", workspace=ws,
        )


@pytest.mark.parametrize("workspace_cls", [MockWorkspace, lambda p: WorkspaceMonitor([p])])
@pytest.mark.parametrize("name", ["../outside/secret.csv", None])
def test_csv_filename_cannot_escape_workspace(outside, workspace_cls, name):
    work, secret = outside
    pm = ParameterManagerModule()
    ws = workspace_cls(work)
    target = name or str(secret / "secret.csv")  # absolute path case
    with pytest.raises(Exception, match="outside the allowed workspace"):
        pm.import_params_csv(csv_filename=target, snapshot_id="x", workspace=ws)


def test_export_filename_cannot_escape_workspace(outside):
    work, secret = outside
    pm = ParameterManagerModule()
    ws = MockWorkspace(work)
    (work / "snapshots").mkdir()
    with pytest.raises(Exception):
        pm.export_params_csv(
            element_filter={}, param_names=["Mark"], snapshot_id="",
            output_filename="../outside/leak.csv", workspace=ws,
        )
    assert not (secret / "leak.csv").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_symlink_inside_workspace_cannot_escape(outside):
    work, secret = outside
    (work / "snapshots").mkdir()
    (work / "snapshots" / "link.json").symlink_to(secret / "secret.json")
    pm = ParameterManagerModule()
    with pytest.raises(Exception, match="outside the allowed workspace"):
        pm.plan_set_params(
            element_filter={}, param_updates={"Mark": "1"},
            snapshot_id="link", workspace=MockWorkspace(work),
        )
