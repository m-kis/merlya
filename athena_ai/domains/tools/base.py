"""
Base classes for dynamic tools.

Follows Open/Closed Principle - tools can be added without modifying core.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum


class ToolCategory(Enum):
    """Tool categories for organization."""
    EXECUTION = "execution"
    ANALYSIS = "analysis"
    SECURITY = "security"
    INFRASTRUCTURE = "infrastructure"
    CODE_GENERATION = "codegen"
    PREVIEW = "preview"


@dataclass
class ToolParameter:
    """Tool parameter specification."""
    name: str
    type: str  # "string", "integer", "boolean", "object", "array"
    description: str
    required: bool = False
    default: Any = None


@dataclass
class ToolMetadata:
    """
    Tool metadata for registration and discovery.

    Separation of Concerns: Metadata separate from implementation.
    """
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter] = field(default_factory=list)
    returns: str = "string"
    version: str = "1.0.0"
    author: str = "athena"

    def to_autogen_schema(self) -> Dict[str, Any]:
        """
        Convert to AutoGen tool schema.

        Returns:
            AutoGen-compatible function schema
        """
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description
            }
            if param.default is not None:
                properties[param.name]["default"] = param.default
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }


class BaseTool(ABC):
    """
    Base class for all tools.

    Liskov Substitution Principle: All tools can be used interchangeably.
    """

    def __init__(self):
        self._metadata: Optional[ToolMetadata] = None

    @abstractmethod
    def get_metadata(self) -> ToolMetadata:
        """
        Get tool metadata.

        Returns:
            ToolMetadata instance
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Tool execution result
        """
        pass

    def validate_params(self, **kwargs) -> bool:
        """
        Validate parameters before execution.

        Args:
            **kwargs: Parameters to validate

        Returns:
            True if valid, raises ValueError otherwise
        """
        metadata = self.get_metadata()

        # Check required parameters
        for param in metadata.parameters:
            if param.required and param.name not in kwargs:
                raise ValueError(f"Missing required parameter: {param.name}")

        # Check unknown parameters (Law of Demeter)
        valid_param_names = {p.name for p in metadata.parameters}
        for key in kwargs:
            if key not in valid_param_names:
                raise ValueError(f"Unknown parameter: {key}")

        return True

    def __call__(self, **kwargs) -> Any:
        """
        Make tool callable.

        Args:
            **kwargs: Tool parameters

        Returns:
            Tool execution result
        """
        self.validate_params(**kwargs)
        return self.execute(**kwargs)
