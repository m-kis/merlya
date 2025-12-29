"""
Merlya Core - Generic Result Type.

Provides a standardized Result[T] pattern for all tool operations.
This replaces the inconsistent ToolResult/SSHResult/raise patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True, slots=True)
class Result(Generic[T]):
    """
    Generic result type for operations.

    Provides a consistent interface for success/failure handling
    across all tools and services.

    Usage:
        # Success
        result = Result.ok(data)

        # Failure
        result = Result.fail("Something went wrong")

        # Check and use
        if result.success:
            process(result.value)
        else:
            handle_error(result.error)
    """

    _value: T | None
    _error: str | None
    _success: bool

    @property
    def success(self) -> bool:
        """Check if the operation succeeded."""
        return self._success

    @property
    def failed(self) -> bool:
        """Check if the operation failed."""
        return not self._success

    @property
    def value(self) -> T:
        """Get the success value. Raises if failed."""
        if not self._success:
            raise ValueError(f"Cannot get value from failed result: {self._error}")
        return self._value  # type: ignore

    @property
    def error(self) -> str:
        """Get the error message. Raises if succeeded."""
        if self._success:
            raise ValueError("Cannot get error from successful result")
        return self._error  # type: ignore

    @property
    def value_or_none(self) -> T | None:
        """Get the value or None if failed."""
        return self._value if self._success else None

    @property
    def error_or_none(self) -> str | None:
        """Get the error or None if succeeded."""
        return self._error if not self._success else None

    def map(self, fn: Callable[[T], U]) -> Result[U]:
        """Transform the value if successful."""
        if self._success:
            return Result.ok(fn(self._value))  # type: ignore
        return Result.fail(self._error)  # type: ignore

    def flat_map(self, fn: Callable[[T], Result[U]]) -> Result[U]:
        """Chain operations that return Results."""
        if self._success:
            return fn(self._value)  # type: ignore
        return Result.fail(self._error)  # type: ignore

    def or_else(self, default: T) -> T:
        """Get the value or a default if failed."""
        return self._value if self._success else default  # type: ignore

    def or_raise(self, exception_type: type[Exception] = ValueError) -> T:
        """Get the value or raise an exception if failed."""
        if not self._success:
            raise exception_type(self._error)
        return self._value  # type: ignore

    @classmethod
    def ok(cls, value: T) -> Result[T]:
        """Create a successful result."""
        return cls(_value=value, _error=None, _success=True)

    @classmethod
    def fail(cls, error: str) -> Result[T]:
        """Create a failed result."""
        return cls(_value=None, _error=error, _success=False)

    @classmethod
    def from_exception(cls, exc: Exception) -> Result[T]:
        """Create a failed result from an exception."""
        return cls.fail(str(exc))

    def __repr__(self) -> str:
        if self._success:
            return f"Result.ok({self._value!r})"
        return f"Result.fail({self._error!r})"


# Type alias for common result types
StringResult = Result[str]
BoolResult = Result[bool]
IntResult = Result[int]
DictResult = Result[dict[str, Any]]
ListResult = Result[list[Any]]
