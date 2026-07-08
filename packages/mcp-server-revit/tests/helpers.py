import asyncio
import threading
from typing import Callable, Any

from revit_mcp_server.config import Config, config
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.security.audit import redact_data
from revit_mcp_server.providers import (
    ProviderRegistry,
    RevitProvider,
    IfcProvider,
    AECMapperProvider,
    JobProvider,
    SQLiteExporterProvider,
)
from revit_mcp_server.jobs import JobManager

class MCPServer:
    def __init__(
        self,
        config_obj: Config | None = None,
        bridge_factory: Callable[[str], Any] | None = None,
        **kwargs,
    ) -> None:
        if "config" in kwargs:
            config_obj = kwargs.pop("config")
        self.config = config_obj if config_obj is not None else config
        self.workspace = WorkspaceMonitor(self.config.allowed_directories)
        
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        self.registry = ProviderRegistry()
        self.revit_provider = RevitProvider(
            workspace=self.workspace,
            mode=self.config.mode,
            bridge_url=self.config.bridge_url,
            bridge_factory=bridge_factory
        )
        self.registry.register(self.revit_provider)
        self.registry.register(IfcProvider(workspace=self.workspace))
        self.registry.register(AECMapperProvider(workspace=self.workspace))
        self.registry.register(SQLiteExporterProvider(workspace=self.workspace, registry=self.registry))

        self.job_manager = JobManager()
        self.registry.register(JobProvider(manager=self.job_manager))

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def handle_tool(self, tool_name: str, payload: dict) -> dict:
        normalized_name = tool_name.replace(".", "_")
        provider = self.registry.lookup_tool_provider(normalized_name)
        if not provider:
            if tool_name.startswith("ifc") or tool_name.startswith("ifc."):
                provider = self.registry.get_provider("ifc")
            else:
                provider = self.registry.get_provider("revit")

        if provider is None:
            raise ValueError(f"Unknown tool {tool_name}")

        run_async = False
        idempotency_key = None
        if isinstance(payload, dict):
            args_copy = dict(payload)
            run_async = args_copy.pop("run_async", False)
            if isinstance(run_async, str):
                run_async = run_async.lower() in ("true", "1", "yes")
            run_async = bool(run_async)
            idempotency_key = args_copy.get("idempotency_key")

        try:
            if run_async:
                async def run_tool_job(context=None):
                    return await provider.execute_tool(tool_name, payload)

                future = asyncio.run_coroutine_threadsafe(
                    self.job_manager.submit(run_tool_job, idempotency_key=idempotency_key),
                    self._loop
                )
                response = future.result()
                response = response.to_dict()
            else:
                future = asyncio.run_coroutine_threadsafe(
                    provider.execute_tool(tool_name, payload),
                    self._loop
                )
                response = future.result()

            response = redact_data(response)
        except Exception as exc:
            response = {"status": "error", "message": redact_data(str(exc))}

        return response

    def shutdown(self) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self.job_manager.shutdown(cancel_running=True),
            self._loop
        )
        try:
            future.result(timeout=2.0)
        except Exception:
            pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=2.0)
