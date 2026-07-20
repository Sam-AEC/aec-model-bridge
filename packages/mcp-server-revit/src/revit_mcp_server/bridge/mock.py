from __future__ import annotations

from datetime import datetime, timezone


class MockBridge:
    def send_tool(self, tool_name: str, payload: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "tool": tool_name,
            "mock": True,
            "timestamp": now,
            "payload": payload,
            "result": {"status": "mock-response"},
        }
