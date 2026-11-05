from typing import Dict, List
import logging
from .base import AECProvider, ProviderTool
from ..tool_profiles import ToolProfile

logger = logging.getLogger(__name__)

class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, AECProvider] = {}
        self._tool_profile: ToolProfile | None = None
        self._tool_snapshot: tuple[tuple[AECProvider, ProviderTool], ...] | None = None
        self._hidden_tools: frozenset[str] = frozenset()

    def freeze_tool_profile(self, profile: ToolProfile) -> None:
        """Snapshot discovery/lookup once for this MCP process, without altering providers.

        Panel registries never call this method and retain their complete tool set.
        ModuleProvider declares manifest ownership explicitly, even for aliased tools.
        """
        if self._tool_snapshot is not None:
            raise RuntimeError("MCP tool profile is static; restart the server to change it")
        visible = []
        hidden = set()
        for provider in self._providers.values():
            for tool in provider.get_capabilities():
                if profile.allows(provider.get_identity(), tool.module_id):
                    visible.append((provider, tool.model_copy(deep=True)))
                else:
                    hidden.add(tool.name)
        self._tool_profile = profile
        self._tool_snapshot = tuple(visible)
        self._hidden_tools = frozenset(hidden - {tool.name for _, tool in visible})
        # Revit jobs dispatch native tools directly, so resolve their nested target
        # through this same snapshot before approval and again before queueing.
        from .revit_jobs import RevitJobProvider
        for provider in self._providers.values():
            if isinstance(provider, RevitJobProvider):
                provider.tool_registry = self

    def is_tool_visible(self, tool_name: str) -> bool:
        return tool_name not in self._hidden_tools

    def validate_profile_call(self, tool_name: str, arguments: object) -> None:
        """Refuse hidden plan/job targets before an approved action is consumed."""
        self._refuse_hidden(tool_name)
        if self._hidden_tools and tool_name == "revit_run_job":
            from .revit_jobs import RevitJobProvider
            provider = self.lookup_tool_provider(tool_name)
            if isinstance(provider, RevitJobProvider) and isinstance(arguments, dict):
                provider._resolve(arguments)

    def _refuse_hidden(self, tool_name: str) -> None:
        if tool_name in self._hidden_tools:
            raise self._tool_profile.refusal(tool_name)

    def get_tools_with_providers(self) -> list[tuple[AECProvider, ProviderTool]]:
        if self._tool_snapshot is not None:
            return list(self._tool_snapshot)
        return [(provider, tool) for provider in self._providers.values()
                for tool in provider.get_capabilities()]

    def register(self, provider: AECProvider) -> None:
        if self._tool_snapshot is not None:
            raise RuntimeError("Cannot register providers after the MCP tool profile is frozen")
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
        return [tool for _, tool in self.get_tools_with_providers()]

    def lookup_tool_provider(self, tool_name: str) -> AECProvider | None:
        self._refuse_hidden(tool_name)
        for provider, tool in self.get_tools_with_providers():
            if tool.name == tool_name:
                return provider
        return None

    def lookup_tool(self, tool_name: str) -> ProviderTool | None:
        self._refuse_hidden(tool_name)
        for _, tool in self.get_tools_with_providers():
            if tool.name == tool_name:
                return tool
        return None
