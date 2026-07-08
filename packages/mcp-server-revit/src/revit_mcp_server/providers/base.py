from abc import ABC, abstractmethod
from typing import Dict, Any, List
from pydantic import BaseModel, Field

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
