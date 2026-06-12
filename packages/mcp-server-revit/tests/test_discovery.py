import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from revit_mcp_server.bridge.discovery import SwitchInfo, discover_switches


@pytest.fixture
def registry_dir(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    return registry


def create_mock_registry(path: Path, provider: str, pid: int, age_days: int = 0, is_malformed: bool = False):
    file_path = path / f"{provider}-{pid}.json"
    if is_malformed:
        file_path.write_text("{ malformed json", encoding="utf-8")
        return file_path

    started_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    data = {
        "provider_id": provider,
        "endpoint": f"http://127.0.0.1:{3000 + pid}",
        "pid": pid,
        "host_version": "2024",
        "connector_version": "1.0",
        "protocol_version": 2,
        "capability_digest": "abcdef",
        "session_token": "secret-token",
        "started_at": started_at.isoformat()
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return file_path


def test_discover_valid_switch(registry_dir):
    with mock.patch("revit_mcp_server.bridge.discovery.is_pid_alive", return_value=True):
        create_mock_registry(registry_dir, "revit", 1234)
        switches = discover_switches(registry_dir)
        assert "revit" in switches
        assert switches["revit"].pid == 1234
        assert switches["revit"].session_token == "secret-token"


def test_prune_stale_pid(registry_dir):
    with mock.patch("revit_mcp_server.bridge.discovery.is_pid_alive", return_value=False):
        file_path = create_mock_registry(registry_dir, "revit", 1234)
        switches = discover_switches(registry_dir)
        assert "revit" not in switches
        assert not file_path.exists(), "Stale file should be pruned"


def test_prune_stale_age(registry_dir):
    with mock.patch("revit_mcp_server.bridge.discovery.is_pid_alive", return_value=True):
        file_path = create_mock_registry(registry_dir, "revit", 1234, age_days=10)
        switches = discover_switches(registry_dir)
        assert "revit" not in switches
        assert not file_path.exists(), "Old file should be pruned even if PID is alive"


def test_ignore_malformed_json(registry_dir):
    file_path = create_mock_registry(registry_dir, "revit", 1234, is_malformed=True)
    switches = discover_switches(registry_dir)
    assert "revit" not in switches
    assert file_path.exists(), "Malformed file should be ignored, not pruned"


def test_acl_denied(registry_dir):
    with mock.patch("revit_mcp_server.bridge.discovery.is_pid_alive", return_value=True):
        file_path = create_mock_registry(registry_dir, "revit", 1234)
        with mock.patch("builtins.open", side_effect=PermissionError("Access denied")):
            switches = discover_switches(registry_dir)
            assert "revit" not in switches
