import time
import pytest
from revit_mcp_server.config import Config, BridgeMode
from helpers import MCPServer

@pytest.mark.perf
def test_dispatch_overhead(tmp_path):
    """
    Asserts the hub tool-dispatch overhead budget defined in ADR 0007.
    Average dispatch time must be < 10 ms.
    """
    cfg = Config(
        workspace_dir=tmp_path,
        allowed_directories=[tmp_path],
        audit_log=tmp_path / "audit.log",
        mode=BridgeMode.mock,
    )
    server = MCPServer(config=cfg)
    try:
        # Warmup
        server.handle_tool("revit.health", {"request_id": "warmup"})
        
        # Measure 100 iterations
        iterations = 100
        start_time = time.perf_counter()
        for i in range(iterations):
            server.handle_tool("revit.health", {"request_id": f"perf-{i}"})
        end_time = time.perf_counter()
        
        avg_overhead_ms = ((end_time - start_time) / iterations) * 1000
        assert avg_overhead_ms < 10.0, f"Dispatch overhead {avg_overhead_ms:.2f}ms exceeds 10ms budget"
    finally:
        server.shutdown()
