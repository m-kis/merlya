"""
Tests for refactored tools module (Phase 2).

Ensures backward compatibility after splitting autogen_tools.py.
"""


class TestBackwardCompatibility:
    """Verify imports from old autogen_tools.py still work."""

    def test_import_from_autogen_tools(self):
        """Old imports should still work."""
        # These were the original imports from autogen_tools.py
        from merlya.agents.autogen_tools import (
            execute_command,
            initialize_autogen_tools,
            list_hosts,
        )

        # Verify they are callable
        assert callable(execute_command)
        assert callable(list_hosts)
        assert callable(initialize_autogen_tools)

    def test_import_from_new_tools_module(self):
        """New imports should also work."""
        from merlya.tools import (
            execute_command,
            initialize_tools,
        )

        assert callable(execute_command)
        assert callable(initialize_tools)


class TestToolContext:
    """Test ToolContext dataclass."""

    def test_tool_context_creation(self):
        """Should create ToolContext with defaults."""
        from merlya.tools import ToolContext

        ctx = ToolContext()
        assert ctx.executor is None
        assert ctx.context_manager is None

    def test_tool_context_with_values(self):
        """Should create ToolContext with values."""
        from merlya.tools import ToolContext

        mock_executor = object()
        ctx = ToolContext(executor=mock_executor)
        assert ctx.executor is mock_executor


class TestModularTools:
    """Test individual tool modules."""

    def test_web_tools_exist(self):
        """Web tools should be importable."""
        from merlya.tools.web import web_fetch, web_search

        assert callable(web_search)
        assert callable(web_fetch)

    def test_container_tools_exist(self):
        """Container tools should be importable."""
        from merlya.tools.containers import docker_exec, kubectl_exec

        assert callable(docker_exec)
        assert callable(kubectl_exec)

    def test_system_tools_exist(self):
        """System tools should be importable."""
        from merlya.tools.system import (
            disk_info,
            memory_info,
            service_control,
        )

        assert callable(disk_info)
        assert callable(memory_info)
        assert callable(service_control)

    def test_file_tools_exist(self):
        """File tools should be importable."""
        from merlya.tools.files import (
            grep_files,
            read_remote_file,
        )

        assert callable(read_remote_file)
        assert callable(grep_files)

    def test_security_tools_exist(self):
        """Security tools should be importable."""
        from merlya.tools.security import analyze_security_logs, audit_host

        assert callable(audit_host)
        assert callable(analyze_security_logs)

    def test_host_tools_exist(self):
        """Host tools should be importable."""
        from merlya.tools.hosts import (
            list_hosts,
            scan_host,
        )

        assert callable(list_hosts)
        assert callable(scan_host)

    def test_command_tools_exist(self):
        """Command tools should be importable."""
        from merlya.tools.commands import add_route, execute_command

        assert callable(execute_command)
        assert callable(add_route)

    def test_interaction_tools_exist(self):
        """Interaction tools should be importable."""
        from merlya.tools.interaction import ask_user, recall_skill, remember_skill

        assert callable(ask_user)
        assert callable(remember_skill)
        assert callable(recall_skill)


class TestInfraToolsExist:
    """Test that infra tools are still exported."""

    def test_generation_tools(self):
        """Generation tools should be importable."""
        from merlya.tools import (
            GenerateAnsibleTool,
            GenerateTerraformTool,
        )

        assert GenerateTerraformTool is not None
        assert GenerateAnsibleTool is not None
