from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import CallToolResult

from .base import AECProvider, ProviderTool
from ..errors import BridgeError

class McpProxyProvider(AECProvider):
    """
    A provider that proxies tool execution requests to a remote MCP server using SSE.
    
    Lifecycle Pattern Chosen:
    - We implement an async `initialize()` method to be called by the owner to fetch remote capabilities 
      and populate `get_capabilities()`.
      This is chosen because `get_capabilities` is synchronous in the AECProvider contract, so we must 
      fetch the tools list before it is called.
    - We also support lazy connection/reconnection on `execute_tool` using exponential backoff 
      if the connection is lost.
    """
    def __init__(self, target_url: str, identity: str = "proxy"):
        self.target_url = target_url
        self._identity = identity
        self._session: ClientSession | None = None
        self._exit_stack = None
        self._tools: List[ProviderTool] = []
        self._connected = False

    def get_identity(self) -> str:
        return self._identity

    def get_capabilities(self) -> List[ProviderTool]:
        return self._tools

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "ok" if self._connected else "disconnected"}

    async def initialize(self) -> None:
        """Initialize connection and fetch remote tools list."""
        await self._connect_with_retry()

    async def _connect_once(self) -> None:
        from contextlib import AsyncExitStack
        
        if self._exit_stack:
            await self._exit_stack.aclose()
            
        self._exit_stack = AsyncExitStack()
        self._tools = []
        self._connected = False
        
        try:
            read, write = await self._exit_stack.enter_async_context(sse_client(self.target_url))
            self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            
            mcp_tools = await self._session.list_tools()
            for t in mcp_tools.tools:
                namespaced_name = f"{self._identity}_{t.name}"
                self._tools.append(ProviderTool(
                    name=namespaced_name,
                    description=t.description or "",
                    inputSchema=t.inputSchema
                ))
            self._connected = True
        except Exception as e:
            self._connected = False
            self._session = None
            if self._exit_stack:
                await self._exit_stack.aclose()
                self._exit_stack = None
            raise e

    async def _connect_with_retry(self) -> None:
        max_retries = 5
        base_delay = 0.5
        max_delay = 8.0
        
        last_exception = None
        for attempt in range(max_retries):
            try:
                await self._connect_once()
                return
            except Exception as e:
                last_exception = e
                delay = min(max_delay, base_delay * (2 ** attempt))
                jitter = random.uniform(0, 0.1 * delay)
                await asyncio.sleep(delay + jitter)
        
        raise BridgeError(
            f"Failed to connect to proxy target {self.target_url} after {max_retries} attempts: {last_exception}"
        )

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        prefix = f"{self._identity}_"
        if not name.startswith(prefix):
            raise ValueError(f"Unknown tool '{name}' on provider '{self._identity}'")

        remote_name = name[len(prefix):]

        if not self._connected or not self._session:
            await self._connect_with_retry()

        try:
            result: CallToolResult = await self._session.call_tool(remote_name, arguments)
            return {
                "result": "\n".join(content.text for content in result.content if hasattr(content, 'text')),
                "is_error": result.isError
            }
        except Exception:
            # Drop connection and try to reconnect once if a tool call fails (SSE drop)
            self._connected = False
            self._session = None
            await self._connect_with_retry()
            try:
                result = await self._session.call_tool(remote_name, arguments)
                return {
                    "result": "\n".join(content.text for content in result.content if hasattr(content, 'text')),
                    "is_error": result.isError
                }
            except Exception as retry_err:
                raise BridgeError(f"Proxy tool execution failed after reconnecting: {retry_err}") from retry_err

    async def shutdown(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._connected = False
        self._session = None
