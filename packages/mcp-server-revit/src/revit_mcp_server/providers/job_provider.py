from __future__ import annotations

from typing import Any, Dict, List

from ..jobs import JobManager
from .base import AECProvider, ProviderTool


class JobProvider(AECProvider):
    def __init__(self, manager: JobManager) -> None:
        self.manager = manager
        self._capabilities = [
            ProviderTool(
                name="job_status",
                description="Get the status, progress, results, or error details of a background job.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "The unique ID of the job to query.",
                        }
                    },
                    "required": ["job_id"],
                    "additionalProperties": False,
                },
            ),
            ProviderTool(
                name="job_cancel",
                description="Cancel a running or queued background job.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "The unique ID of the job to cancel.",
                        }
                    },
                    "required": ["job_id"],
                    "additionalProperties": False,
                },
            ),
        ]

    def get_identity(self) -> str:
        return "jobs"

    def get_capabilities(self) -> List[ProviderTool]:
        return self._capabilities

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy", "provider": "jobs"}

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        normalized = name.replace(".", "_")
        if normalized == "job_status":
            job_id = arguments["job_id"]
            ref = await self.manager.get(job_id)
            if ref is None:
                raise ValueError(f"Job not found: {job_id}")
            return ref.to_dict()
        elif normalized == "job_cancel":
            job_id = arguments["job_id"]
            ref = await self.manager.cancel(job_id)
            if ref is None:
                raise ValueError(f"Job not found: {job_id}")
            return ref.to_dict()
        raise ValueError(f"Unknown job tool: {name}")

    async def shutdown(self) -> None:
        pass
