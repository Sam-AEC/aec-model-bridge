from typing import Dict, Any, List
import logging
from .base import AECProvider, ProviderTool

logger = logging.getLogger(__name__)

class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, AECProvider] = {}

    def register(self, provider: AECProvider) -> None:
        identity = provider.get_identity()
        if identity in self._providers:
            logger.warning(f"Overwriting already registered provider '{identity}'")
        self._providers[identity] = provider
        logger.info(f"Registered provider '{identity}'")

    def get_provider(self, identity: str) -> AECProvider | None:
        return self._providers.get(identity)

    def get_all_providers(self) -> List[AECProvider]:
        return list(self._providers.values())

    def get_all_tools(self) -> List[ProviderTool]:
        tools: List[ProviderTool] = []
        for provider in self._providers.values():
            tools.extend(provider.get_capabilities())
        return tools

    def lookup_tool_provider(self, tool_name: str) -> AECProvider | None:
        for provider in self._providers.values():
            for tool in provider.get_capabilities():
                if tool.name == tool_name:
                    return provider
        return None

    def lookup_tool(self, tool_name: str) -> ProviderTool | None:
        for provider in self._providers.values():
            for tool in provider.get_capabilities():
                if tool.name == tool_name:
                    return tool
        return None
