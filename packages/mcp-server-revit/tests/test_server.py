from pathlib import Path

from revit_mcp_server.config import BridgeMode, Config
from revit_mcp_server.server import MCPServer


class DummyBridge:
    def __init__(self, url: str) -> None:  # pylint: disable=unused-argument
        self.calls: list[tuple[str, dict]] = []

    def send_tool(self, tool_name: str, payload: dict) -> dict:
        self.calls.append((tool_name, payload))
        return {"echo": tool_name, "payload": payload}


def create_config(tmp_path: Path, **overrides) -> Config:
    return Config(
        workspace_dir=tmp_path,
        allowed_directories=[tmp_path],
        audit_log=tmp_path / "audit.log",
        bridge_url=overrides.get("bridge_url"),
        mode=overrides.get("mode", BridgeMode.mock),
    )


def test_handle_tool_with_mock(tmp_path: Path):
    cfg = create_config(tmp_path)
    server = MCPServer(config=cfg)
    response = server.handle_tool("revit.health", {"request_id": "req-1"})
    assert response["status"] == "healthy"


def test_handle_tool_bridge_mode(tmp_path: Path):
    cfg = create_config(tmp_path, bridge_url="http://bridge", mode=BridgeMode.bridge)
    bridge = DummyBridge(cfg.bridge_url)
    server = MCPServer(config=cfg, bridge_factory=lambda _: bridge)
    try:
        response = server.handle_tool("revit.health", {"request_id": "req-bridge"})
        assert response["echo"] == "revit.health"
        assert bridge.calls
    finally:
        server.shutdown()


def test_deferred_execution_and_job_tools(tmp_path: Path):
    cfg = create_config(tmp_path)
    server = MCPServer(config=cfg)
    try:
        # Trigger a tool call asynchronously (e.g. revit.health)
        response = server.handle_tool("revit.health", {"request_id": "req-async", "run_async": True})
        assert response["status"] in ("queued", "running")
        job_id = response["job_id"]
        assert job_id

        # Wait for the job to complete
        import time
        for _ in range(100):
            status_resp = server.handle_tool("job_status", {"job_id": job_id})
            if status_resp["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            status_resp = server.handle_tool("job_status", {"job_id": job_id})
            assert status_resp["status"] == "completed"

        assert status_resp["result"]["status"] == "healthy"

        # Test cancel a completed/running job
        cancel_resp = server.handle_tool("job_cancel", {"job_id": job_id})
        assert cancel_resp["job_id"] == job_id
    finally:
        server.shutdown()


def test_redaction_in_server(tmp_path: Path):
    cfg = create_config(tmp_path)
    server = MCPServer(config=cfg)
    try:
        # Register mapping with paths and secrets
        register_resp = server.handle_tool(
            "aec_register_mapping",
            {
                "mappings": [
                    {
                        "revit_unique_id": "revit-id",
                        "ifc_guid": "ifc-id",
                        "rhino_uuid": "rhino-id",
                        "token": "sensitive-token-123",
                        "file_path": r"C:\Users\sammo\secret.rvt",
                    }
                ]
            }
        )
        assert register_resp["status"] == "success"

        # Query translation mapping
        response = server.handle_tool(
            "aec_translate_id",
            {
                "source_id": "revit-id",
                "source_format": "revit_unique_id",
                "target_format": "ifc_guid"
            }
        )
        assert response["translated_id"] == "ifc-id"

        # Verify path mapping output redaction
        dummy_file = tmp_path / "test.rvt"
        dummy_file.write_text("dummy")
        path_resp = server.handle_tool(
            "aec_map_workspace_path",
            {
                "path": str(dummy_file),
                "target_format": "absolute_windows"
            }
        )
        assert "test.rvt" not in path_resp["mapped_path"]
        assert "<redacted-path>" in path_resp["mapped_path"]

        # Trigger tool call with path input to check path sanitization in errors
        non_existent_file = tmp_path / "secret.ifc"
        response_err = server.handle_tool(
            "ifc_validate",
            {"ifc_path": str(non_existent_file)}
        )
        assert response_err["status"] == "error"
        err_msg = response_err["message"]
        assert "secret.ifc" not in err_msg
        assert "C:\\" not in err_msg
        assert "<redacted-path>" in err_msg
    finally:
        server.shutdown()


