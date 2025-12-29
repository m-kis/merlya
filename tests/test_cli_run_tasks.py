"""Tests for loading task files used by `merlya run --file`."""

from __future__ import annotations

from merlya.cli.run import load_tasks_from_file


def test_load_tasks_from_file_skips_comments_and_blank_lines_in_text(tmp_path):
    task_file = tmp_path / "tasks.txt"
    task_file.write_text(
        "\n".join(
            [
                "# comment",
                "   # indented comment",
                "",
                "Check disk usage on @web-01",
                "   ",
                "  /hosts list",
            ]
        )
    )

    tasks = load_tasks_from_file(str(task_file))

    assert len(tasks) == 2
    assert tasks[0].prompt == "Check disk usage on @web-01"
    assert tasks[1].prompt == "/hosts list"
    assert all(t.model_role is None for t in tasks)


def test_load_tasks_from_file_supports_yaml_tasks_dict(tmp_path):
    task_file = tmp_path / "tasks.yml"
    task_file.write_text(
        "\n".join(
            [
                "tasks:",
                "  - description: Check disk",
                "    prompt: Check disk usage on @web-01",
                "  - prompt: /hosts list",
                "  - Just a string task",
            ]
        )
    )

    tasks = load_tasks_from_file(str(task_file))

    assert len(tasks) == 3
    assert tasks[0].prompt == "Check disk usage on @web-01"
    assert tasks[0].description == "Check disk"
    assert tasks[1].prompt == "/hosts list"
    assert tasks[2].prompt == "Just a string task"


def test_load_tasks_from_file_returns_empty_list_for_empty_yaml(tmp_path):
    task_file = tmp_path / "tasks.yaml"
    task_file.write_text("")

    tasks = load_tasks_from_file(str(task_file))

    assert tasks == []


def test_load_tasks_from_file_with_model_selection(tmp_path):
    """Test that model selection works at file and task level."""
    task_file = tmp_path / "tasks.yml"
    task_file.write_text(
        "\n".join(
            [
                "model: fast",
                "tasks:",
                "  - description: Quick check",
                "    prompt: Check disk space",
                "  - description: Complex analysis",
                "    prompt: Analyze system performance",
                "    model: brain",
            ]
        )
    )

    tasks = load_tasks_from_file(str(task_file))

    assert len(tasks) == 2
    # First task uses file-level default
    assert tasks[0].model_role == "fast"
    # Second task overrides with task-level model
    assert tasks[1].model_role == "brain"


def test_load_tasks_from_file_cli_model_overrides_file(tmp_path):
    """Test that CLI default_model overrides file-level model."""
    task_file = tmp_path / "tasks.yml"
    task_file.write_text(
        "\n".join(
            [
                "model: brain",
                "tasks:",
                "  - prompt: Some task",
            ]
        )
    )

    # CLI specifies fast, should override file-level brain
    tasks = load_tasks_from_file(str(task_file), default_model="fast")

    assert len(tasks) == 1
    assert tasks[0].model_role == "fast"


def test_load_tasks_from_file_invalid_model_raises_error(tmp_path):
    """Test that invalid model role raises ValueError."""
    import pytest

    task_file = tmp_path / "tasks.yml"
    task_file.write_text(
        "\n".join(
            [
                "model: invalid_model",
                "tasks:",
                "  - prompt: Some task",
            ]
        )
    )

    with pytest.raises(ValueError, match="Invalid model role 'invalid_model'"):
        load_tasks_from_file(str(task_file))


def test_load_tasks_from_file_invalid_task_model_raises_error(tmp_path):
    """Test that invalid model role at task level raises ValueError."""
    import pytest

    task_file = tmp_path / "tasks.yml"
    task_file.write_text(
        "\n".join(
            [
                "tasks:",
                "  - description: Bad task",
                "    prompt: Do something",
                "    model: wrong",
            ]
        )
    )

    with pytest.raises(ValueError, match=r"Invalid model role 'wrong'.*task #1"):
        load_tasks_from_file(str(task_file))
