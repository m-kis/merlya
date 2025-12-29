"""Tests for merlya.core.result module."""

import pytest

from merlya.core.result import (
    BoolResult,
    DictResult,
    IntResult,
    ListResult,
    Result,
    StringResult,
)


class TestResultOk:
    """Tests for successful Result creation."""

    def test_ok_creates_success(self) -> None:
        result = Result.ok("hello")
        assert result.success is True
        assert result.failed is False

    def test_ok_stores_value(self) -> None:
        result = Result.ok(42)
        assert result.value == 42

    def test_ok_has_no_error(self) -> None:
        result = Result.ok("test")
        assert result.error_or_none is None

    def test_value_or_none_returns_value(self) -> None:
        result = Result.ok("test")
        assert result.value_or_none == "test"


class TestResultFail:
    """Tests for failed Result creation."""

    def test_fail_creates_failure(self) -> None:
        result = Result.fail("something went wrong")
        assert result.success is False
        assert result.failed is True

    def test_fail_stores_error(self) -> None:
        result = Result.fail("error message")
        assert result.error == "error message"

    def test_fail_has_no_value(self) -> None:
        result: Result[str] = Result.fail("error")
        assert result.value_or_none is None

    def test_error_or_none_returns_error(self) -> None:
        result: Result[str] = Result.fail("error")
        assert result.error_or_none == "error"


class TestResultAccess:
    """Tests for Result value/error access."""

    def test_value_raises_on_failure(self) -> None:
        result: Result[str] = Result.fail("error")
        with pytest.raises(ValueError, match="Cannot get value from failed result"):
            _ = result.value

    def test_error_raises_on_success(self) -> None:
        result = Result.ok("value")
        with pytest.raises(ValueError, match="Cannot get error from successful result"):
            _ = result.error


class TestResultMap:
    """Tests for Result.map transformation."""

    def test_map_transforms_success(self) -> None:
        result = Result.ok(5)
        mapped = result.map(lambda x: x * 2)
        assert mapped.value == 10

    def test_map_propagates_failure(self) -> None:
        result: Result[int] = Result.fail("error")
        mapped = result.map(lambda x: x * 2)
        assert mapped.failed is True
        assert mapped.error == "error"


class TestResultFlatMap:
    """Tests for Result.flat_map chaining."""

    def test_flat_map_chains_success(self) -> None:
        result = Result.ok(5)
        chained = result.flat_map(lambda x: Result.ok(x * 2))
        assert chained.value == 10

    def test_flat_map_propagates_first_failure(self) -> None:
        result: Result[int] = Result.fail("first error")
        chained = result.flat_map(lambda x: Result.ok(x * 2))
        assert chained.failed is True
        assert chained.error == "first error"

    def test_flat_map_propagates_second_failure(self) -> None:
        result = Result.ok(5)
        chained = result.flat_map(lambda x: Result.fail("second error"))
        assert chained.failed is True
        assert chained.error == "second error"


class TestResultOrElse:
    """Tests for Result.or_else default value."""

    def test_or_else_returns_value_on_success(self) -> None:
        result = Result.ok(42)
        assert result.or_else(0) == 42

    def test_or_else_returns_default_on_failure(self) -> None:
        result: Result[int] = Result.fail("error")
        assert result.or_else(0) == 0


class TestResultOrRaise:
    """Tests for Result.or_raise exception conversion."""

    def test_or_raise_returns_value_on_success(self) -> None:
        result = Result.ok("value")
        assert result.or_raise() == "value"

    def test_or_raise_raises_on_failure(self) -> None:
        result: Result[str] = Result.fail("error message")
        with pytest.raises(ValueError, match="error message"):
            result.or_raise()

    def test_or_raise_uses_custom_exception(self) -> None:
        result: Result[str] = Result.fail("error")
        with pytest.raises(RuntimeError, match="error"):
            result.or_raise(RuntimeError)


class TestResultFromException:
    """Tests for Result.from_exception factory."""

    def test_from_exception_creates_failure(self) -> None:
        exc = ValueError("something broke")
        result: Result[str] = Result.from_exception(exc)
        assert result.failed is True
        assert result.error == "something broke"


class TestResultRepr:
    """Tests for Result string representation."""

    def test_repr_success(self) -> None:
        result = Result.ok(42)
        assert repr(result) == "Result.ok(42)"

    def test_repr_failure(self) -> None:
        result: Result[int] = Result.fail("error")
        assert repr(result) == "Result.fail('error')"


class TestTypeAliases:
    """Tests for type alias convenience."""

    def test_string_result(self) -> None:
        result: StringResult = Result.ok("hello")
        assert result.value == "hello"

    def test_bool_result(self) -> None:
        result: BoolResult = Result.ok(True)
        assert result.value is True

    def test_int_result(self) -> None:
        result: IntResult = Result.ok(42)
        assert result.value == 42

    def test_dict_result(self) -> None:
        result: DictResult = Result.ok({"key": "value"})
        assert result.value == {"key": "value"}

    def test_list_result(self) -> None:
        result: ListResult = Result.ok([1, 2, 3])
        assert result.value == [1, 2, 3]
