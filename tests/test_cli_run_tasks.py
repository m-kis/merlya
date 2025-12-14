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

    assert tasks == ["Check disk usage on @web-01", "/hosts list"]


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

    assert tasks == ["Check disk usage on @web-01", "/hosts list", "Just a string task"]


def test_load_tasks_from_file_returns_empty_list_for_empty_yaml(tmp_path):
    task_file = tmp_path / "tasks.yaml"
    task_file.write_text("")

    tasks = load_tasks_from_file(str(task_file))

    assert tasks == []
