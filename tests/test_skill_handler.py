"""Tests for /skill command handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.commands.handlers.skill import (
    cmd_skill_list,
    cmd_skill_run,
    cmd_skill_show,
    cmd_skill_template,
)
from merlya.skills.models import SkillConfig
from merlya.skills.registry import get_registry, reset_registry


@pytest.fixture(autouse=True)
def reset_skill_registry() -> None:
    """Reset global skill registry for isolation."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def mock_context() -> MagicMock:
    """Minimal context for skill handlers."""
    ctx = MagicMock()
    ctx.ui = MagicMock()
    ctx.ui.confirm = AsyncMock(return_value=True)
    ctx.ui.spinner = MagicMock()
    ctx.ui.warning = MagicMock()
    ctx.ui.info = MagicMock()
    ctx.hosts = AsyncMock()
    ctx.hosts.get_by_name = AsyncMock()
    ctx.hosts.get_all = AsyncMock()
    return ctx


class TestSkillList:
    """Tests for cmd_skill_list."""

    @pytest.mark.asyncio
    async def test_list_no_skills(self, mock_context: MagicMock) -> None:
        result = await cmd_skill_list(mock_context, [])

        assert result.success is True
        assert "No skills registered" in result.message

    @pytest.mark.asyncio
    async def test_list_with_tag_filter_splits_builtin_and_user(
        self, mock_context: MagicMock
    ) -> None:
        registry = get_registry()
        registry.register(
            SkillConfig(
                name="disk_audit",
                description="Audit disks",
                builtin=True,
                tags=["web"],
                intent_patterns=[r"disk.*"],
            )
        )
        registry.register(
            SkillConfig(
                name="nginx_restart",
                description="Restart nginx",
                builtin=False,
                tags=["web"],
                intent_patterns=[r"nginx.*restart"],
            )
        )

        result = await cmd_skill_list(mock_context, ["web"])

        assert result.success is True
        assert "Skills tagged" in result.message
        assert "**Builtin:**" in result.message
        assert "**User:**" in result.message
        assert result.data["count"] == 2


class TestSkillShow:
    """Tests for cmd_skill_show."""

    @pytest.mark.asyncio
    async def test_show_without_name_returns_help(self, mock_context: MagicMock) -> None:
        result = await cmd_skill_show(mock_context, [])
        assert result.success is False
        assert result.show_help

    @pytest.mark.asyncio
    async def test_show_not_found(self, mock_context: MagicMock) -> None:
        result = await cmd_skill_show(mock_context, ["missing"])
        assert result.success is False
        assert "Skill not found" in result.message

    @pytest.mark.asyncio
    async def test_show_success(self, mock_context: MagicMock) -> None:
        registry = get_registry()
        skill = SkillConfig(
            name="disk_audit",
            description="Audit disks",
            builtin=True,
            tools_allowed=["ssh_execute"],
            tags=["infra"],
            intent_patterns=[r"disk.*audit"],
        )
        registry.register(skill)

        result = await cmd_skill_show(mock_context, ["disk_audit"])

        assert result.success is True
        assert "disk_audit" in result.message
        assert "Type: builtin" in result.message
        assert result.data == skill


class TestSkillTemplate:
    """Tests for cmd_skill_template."""

    @pytest.mark.asyncio
    async def test_template_rejects_invalid_name(self, mock_context: MagicMock) -> None:
        result = await cmd_skill_template(mock_context, ["../bad"])
        assert result.success is False
        assert "Invalid skill name" in result.message

    @pytest.mark.asyncio
    async def test_template_writes_file_under_home(
        self, mock_context: MagicMock, tmp_path: Path
    ) -> None:
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = await cmd_skill_template(mock_context, ["my_skill", "desc"])

        assert result.success is True
        path = Path(result.data["path"])
        assert path.exists()
        content = path.read_text()
        assert content
        assert "name: my_skill" in content


class TestSkillRun:
    """Tests for cmd_skill_run."""

    @pytest.mark.asyncio
    async def test_run_without_args_returns_help(self, mock_context: MagicMock) -> None:
        result = await cmd_skill_run(mock_context, [])
        assert result.success is False
        assert result.show_help
