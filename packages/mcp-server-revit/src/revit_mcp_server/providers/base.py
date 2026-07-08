from abc import ABC, abstractmethod
from typing import Dict, Any, FrozenSet, List
from pydantic import BaseModel, Field


def enrich_mutation_metadata(
    tools: List["ProviderTool"],
    mutating_verbs: FrozenSet[str] = frozenset(),
    mutating_names: FrozenSet[str] = frozenset(),
    destructive: FrozenSet[str] = frozenset(),
) -> None:
    """Flag tools as `is_mutating` (and optionally `destructive`) in place.

    Two matching strategies, usable together: `mutating_verbs` matches any
    underscore-split part of the tool name (works well for providers whose tool
    names follow a `<provider>_<verb>_<noun>` convention, e.g. `revit_create_wall`);
    `mutating_names` matches exact tool names (safer for tool sets — e.g. Speckle/APS —
    where a generic verb list would either miss real mutations or false-positive on
    read verbs like `list`). `destructive` tool names get both flags set, mirroring
    how escape hatches like `revit_execute_python` are treated: mutating AND destructive.

    Every provider's write-capable tools MUST run through one of these so the
    ApprovalGate in mcp_server.py actually sees them — a tool that keeps the
    default `is_mutating=False` silently bypasses the approval gate entirely.
    """
    for tool in tools:
        name_parts = tool.name.split("_")
        if tool.name in mutating_names or any(verb in name_parts for verb in mutating_verbs):
            tool.is_mutating = True
        if tool.name in destructive:
            tool.is_mutating = True
            tool.destructive = True


class ProviderTool(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any] = Field(..., alias="inputSchema")
    is_mutating: bool = False
    destructive: bool = False
    execution_mode: str = "sync"
    permissions: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True
        populate_by_field_name = True  # Support both for older Pydantic compatibility if needed

class AECProvider(ABC):
    @abstractmethod
    def get_identity(self) -> str:
        """Return the unique identifier for the provider (e.g. 'revit', 'ifc')."""
        pass

    @abstractmethod
    def get_capabilities(self) -> List[ProviderTool]:
        """Return the list of tools supported by this provider."""
        pass

    @abstractmethod
    async def check_health(self) -> Dict[str, Any]:
        """Check the health status of the provider/connection."""
        pass

    @abstractmethod
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool with the given name and arguments.
        
        Args:
            name: The name of the tool to execute.
            arguments: The inputs to pass to the tool.
            
        Returns:
            A dict containing the execution results.
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Perform cleanup or disconnect from resources."""
        pass
