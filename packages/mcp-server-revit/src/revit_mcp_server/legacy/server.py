from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import os
import threading
from typing import Callable, Dict, Protocol

from .config import BridgeMode, Config, config
from .security.audit import AuditRecorder, redact_data
from .security.workspace import WorkspaceMonitor
from .providers import (
    ProviderRegistry,
    RevitProvider,
    IfcProvider,
    AECMapperProvider,
    RhinoProvider,
    NavisworksProvider,
    SemanticGraphProvider,
    AutodeskDataProvider,
    JobProvider,
    SQLiteExporterProvider,
    SpeckleProvider,
    McpProxyProvider,
)
from .jobs import JobManager

logger = logging.getLogger(__name__)


class BridgeTransport(Protocol):
    def send_tool(self, tool_name: str, payload: dict) -> dict:
        ...


class MCPServer:
    def __init__(
        self,
        config_obj: Config | None = None,
        bridge_factory: Callable[[str], BridgeTransport] | None = None,
        **kwargs,
    ) -> None:
        if "config" in kwargs:
            if config_obj is not None:
                raise TypeError("Pass either config_obj or config, not both")
            config_obj = kwargs.pop("config")
        if kwargs:
            unexpected = ", ".join(kwargs)
            raise TypeError(f"Unexpected keyword argument(s): {unexpected}")
        self.config = config_obj if config_obj is not None else config
        self.workspace = WorkspaceMonitor(self.config.allowed_directories)
        self.audit = AuditRecorder(self.config.audit_log)

        # Initialize the persistent background event loop for job execution survival
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        # Initialize and register providers behind the scenes
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

        # Register Job Provider
        self.job_manager = JobManager()
        self.registry.register(JobProvider(manager=self.job_manager))

        # Register other providers conditionally
        try:
            self.registry.register(RhinoProvider(workspace=self.workspace))
        except Exception as e:
            logger.warning("Could not initialize RhinoProvider: %s", e)

        try:
            self.registry.register(NavisworksProvider(workspace=self.workspace))
        except Exception as e:
            logger.warning("Could not initialize NavisworksProvider: %s", e)

        try:
            self.registry.register(SemanticGraphProvider())
        except Exception as e:
            logger.warning("Could not initialize SemanticGraphProvider: %s", e)

        try:
            self.registry.register(SpeckleProvider(workspace=self.workspace))
        except Exception as e:
            logger.warning("Could not initialize SpeckleProvider: %s", e)

        try:
            self.registry.register(AutodeskDataProvider())
        except Exception as e:
            logger.warning("Could not initialize AutodeskDataProvider: %s. Please set APS_CLIENT_ID.", e)

        try:
            proxy_url = os.getenv("MCP_PROXY_URL")
            if proxy_url:
                proxy = McpProxyProvider(proxy_url)
                self._loop.create_task(proxy._connect())
                self.registry.register(proxy)
        except Exception as e:
            logger.warning("Could not initialize McpProxyProvider: %s", e)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def handle_tool(self, tool_name: str, payload: dict) -> dict:
        # Resolve the provider for the tool
        normalized_name = tool_name.replace(".", "_")
        provider = self.registry.lookup_tool_provider(normalized_name)
        if not provider:
            if tool_name.startswith("ifc") or tool_name.startswith("ifc."):
                provider = self.registry.get_provider("ifc")
            else:
                provider = self.registry.get_provider("revit")

        if provider is None:
            raise ValueError(f"Unknown tool {tool_name}")

        # Check if deferred execution is requested
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

                # Submit the job on the background loop
                future = asyncio.run_coroutine_threadsafe(
                    self.job_manager.submit(run_tool_job, idempotency_key=idempotency_key),
                    self._loop
                )
                job_ref = future.result()
                response = job_ref.to_dict()
            else:
                # Run normally on the background loop
                future = asyncio.run_coroutine_threadsafe(
                    provider.execute_tool(tool_name, payload),
                    self._loop
                )
                response = future.result()

            response = redact_data(response)
        except Exception as exc:
            response = {"status": "error", "message": redact_data(str(exc))}

        self.audit.record(tool_name, payload.get("request_id", ""), payload, response)
        return response

    def run(
        self,
        *,
        stdin: io.TextIOBase | None = None,
        stdout: io.TextIOBase | None = None,
    ) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        stdout.write("AEC Model Bridge server started. Awaiting JSON requests.\n")
        stdout.flush()

        try:
            while line := stdin.readline():
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                    tool = request.get("tool")
                    payload = request.get("payload", {})
                    response = self.handle_tool(tool, payload)
                except Exception as exc:  # noqa: BLE001
                    response = {"status": "error", "message": redact_data(str(exc))}
                stdout.write(json.dumps({"tool": tool, "response": response}) + "\n")
                stdout.flush()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        # Gracefully stop the JobManager and any running jobs
        future = asyncio.run_coroutine_threadsafe(
            self.job_manager.shutdown(cancel_running=True),
            self._loop
        )
        try:
            future.result(timeout=2.0)
        except Exception:
            pass

        # Close provider clients
        for p in self.registry._providers.values():
            if hasattr(p, "shutdown"):
                try:
                    asyncio.run_coroutine_threadsafe(p.shutdown(), self._loop).result(timeout=1.0)
                except Exception:
                    pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=2.0)


def run_server() -> None:
    server = MCPServer()
    server.run()
