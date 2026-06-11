from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from mcp.types import CallToolResult, Tool
from revit_mcp_server.providers.proxy import McpProxyProvider
from revit_mcp_server.errors import BridgeError

@pytest.mark.anyio
async def test_proxy_provider_flow() -> None:
    provider = McpProxyProvider("http://fake-target/sse")

    # Mock SSE Client stream context manager
    mock_read = MagicMock()
    mock_write = MagicMock()

    # Mock ClientSession
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.initialize = AsyncMock()
    
    # Mock list_tools
    mock_tool = MagicMock(spec=Tool)
    mock_tool.name = "get_info"
    mock_tool.description = "Gets info"
    mock_tool.inputSchema = {"type": "object"}
    
    mock_tools_list = MagicMock()
    mock_tools_list.tools = [mock_tool]
    mock_session.list_tools.return_value = mock_tools_list

    # Mock call_tool
    mock_content = MagicMock()
    mock_content.text = "remote-tool-result"
    mock_call_result = MagicMock(spec=CallToolResult)
    mock_call_result.content = [mock_content]
    mock_call_result.isError = False
    mock_session.call_tool.return_value = mock_call_result

    # Mock sse_client and ClientSession inside proxy
    with patch("revit_mcp_server.providers.proxy.sse_client") as mock_sse_client, \
         patch("revit_mcp_server.providers.proxy.ClientSession", return_value=mock_session):
        
        # Mock sse_client enter/exit stack behavior
        mock_sse_client.return_value.__aenter__.return_value = (mock_read, mock_write)

        # 1. Initialize & verify tools listing
        await provider.initialize()
        assert provider.get_identity() == "proxy"
        assert await provider.check_health() == {"status": "ok"}
        
        capabilities = provider.get_capabilities()
        assert len(capabilities) == 1
        assert capabilities[0].name == "proxy_get_info"
        assert capabilities[0].description == "Gets info"

        # 2. Tool call round-trip
        exec_res = await provider.execute_tool("proxy_get_info", {"arg": "val"})
        assert exec_res["result"] == "remote-tool-result"
        assert exec_res["is_error"] is False
        mock_session.call_tool.assert_called_once_with("get_info", {"arg": "val"})

        # 3. Disconnect and Reconnect cycle
        # We can simulate SSE drop by making call_tool raise an exception,
        # which triggers reconnection and retry
        mock_session.call_tool.reset_mock()
        mock_session.call_tool.side_effect = [Exception("SSE dropped"), mock_call_result]

        exec_res_retry = await provider.execute_tool("proxy_get_info", {"arg": "val"})
        assert exec_res_retry["result"] == "remote-tool-result"
        # Since it raises once, then reconnects, and then retries successfully:
        assert mock_session.call_tool.call_count == 2

        # 4. Unreachable target error path
        # If connect_once fails repeatedly, check BridgeError is raised
        mock_sse_client.side_effect = Exception("Target unreachable")
        
        # Reset provider exit stack and connection state
        await provider.shutdown()
        
        with patch("asyncio.sleep", AsyncMock()): # skip delays in tests
            with pytest.raises(BridgeError, match="Failed to connect to proxy target"):
                await provider.initialize()
