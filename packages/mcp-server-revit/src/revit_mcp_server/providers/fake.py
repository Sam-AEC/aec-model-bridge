from typing import Dict, Any, List
from .base import AECProvider, ProviderTool

class FakeProvider(AECProvider):
    def get_identity(self) -> str:
        return "fake"

    def get_capabilities(self) -> List[ProviderTool]:
        return [
            ProviderTool(
                name="fake_tool",
                description="A fake tool for testing",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "input_val": {"type": "string"}
                    },
                    "required": ["input_val"]
                }
            )
        ]

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "OK", "provider": "fake"}

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "fake_tool":
            return {"result": f"processed {arguments.get('input_val')}"}
        raise ValueError(f"Unknown fake tool: {name}")

    async def shutdown(self) -> None:
        pass
