"""
Dynamic Tool Registry.

Central registry for discovering, registering, and managing tools.
Follows Singleton pattern for global access.
"""
import inspect
from typing import Any, Callable, Dict, List, Optional

from merlya.utils.logger import logger

from .base import BaseTool, ToolCategory, ToolMetadata


class ToolRegistry:
    """
    Global tool registry with dynamic discovery.

    Singleton pattern ensures one registry instance.
    Open/Closed Principle: New tools don't require code changes.
    """

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls):
        """Singleton implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize registry (once)."""
        if self._initialized:
            return

        self._tools: Dict[str, BaseTool] = {}
        self._functions: Dict[str, Callable] = {}  # For non-class tools
        self._categories: Dict[ToolCategory, List[str]] = {cat: [] for cat in ToolCategory}
        self._initialized = True

        logger.debug("ToolRegistry initialized")

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool instance.

        Args:
            tool: BaseTool instance to register
        """
        metadata = tool.get_metadata()
        name = metadata.name

        if name in self._tools:
            logger.warning(f"Tool '{name}' already registered, overwriting")

        self._tools[name] = tool

        # Add to category
        if metadata.category not in self._categories[metadata.category]:
            self._categories[metadata.category].append(name)

        logger.debug(f"Registered tool: {name} (category: {metadata.category.value})")

    def register_function(
        self,
        func: Callable,
        metadata: ToolMetadata
    ) -> None:
        """
        Register a standalone function as a tool.

        Useful for wrapping existing functions without creating a class.

        Args:
            func: Function to register
            metadata: Tool metadata
        """
        name = metadata.name

        if name in self._functions:
            logger.warning(f"Function tool '{name}' already registered, overwriting")

        self._functions[name] = func

        # Create a pseudo-tool for metadata
        class _FunctionTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return metadata

            def execute(self, **kwargs) -> Any:
                return func(**kwargs)

        # Register as regular tool
        self.register(_FunctionTool())

    def get(self, name: str) -> Optional[BaseTool]:
        """
        Get a tool by name.

        Args:
            name: Tool name

        Returns:
            BaseTool instance or None
        """
        return self._tools.get(name)

    def get_function(self, name: str) -> Optional[Callable]:
        """
        Get tool as a callable function.

        Args:
            name: Tool name

        Returns:
            Callable function or None
        """
        tool = self.get(name)
        if tool:
            return lambda **kwargs: tool(**kwargs)
        return self._functions.get(name)

    def list_tools(self, category: Optional[ToolCategory] = None) -> List[str]:
        """
        List all registered tools.

        Args:
            category: Optional category filter

        Returns:
            List of tool names
        """
        if category:
            return self._categories.get(category, [])
        return list(self._tools.keys())

    def get_autogen_schemas(self, category: Optional[ToolCategory] = None) -> List[Dict[str, Any]]:
        """
        Get AutoGen-compatible schemas for all tools.

        Args:
            category: Optional category filter

        Returns:
            List of AutoGen function schemas
        """
        tools = self.list_tools(category)
        schemas = []

        for name in tools:
            tool = self.get(name)
            if tool:
                metadata = tool.get_metadata()
                schemas.append(metadata.to_autogen_schema())

        return schemas

    def get_function_map(self, category: Optional[ToolCategory] = None) -> Dict[str, Callable]:
        """
        Get a function map for AutoGen user_proxy.

        Args:
            category: Optional category filter

        Returns:
            Dict mapping tool names to callable functions
        """
        tools = self.list_tools(category)
        function_map = {}

        for name in tools:
            func = self.get_function(name)
            if func:
                function_map[name] = func

        return function_map

    def discover_tools(self, package_path: str) -> int:
        """
        Discover and auto-register tools from a package.

        Scans for classes inheriting from BaseTool and auto-registers them.

        Args:
            package_path: Python package path (e.g., "merlya.tools")

        Returns:
            Number of tools discovered
        """
        try:
            import importlib
            module = importlib.import_module(package_path)

            count = 0
            # Get all classes in module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Check if it's a BaseTool subclass (but not BaseTool itself)
                if issubclass(obj, BaseTool) and obj != BaseTool:
                    try:
                        tool_instance = obj()
                        self.register(tool_instance)
                        count += 1
                    except Exception as e:
                        logger.error(f"Failed to instantiate tool {name}: {e}")

            logger.info(f"Discovered {count} tools from {package_path}")
            return count

        except ImportError as e:
            logger.error(f"Failed to import package {package_path}: {e}")
            return 0

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._functions.clear()
        for cat in self._categories:
            self._categories[cat].clear()
        logger.debug("ToolRegistry cleared")


# Global registry instance
registry = ToolRegistry()
