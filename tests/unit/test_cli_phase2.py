import json
import shutil
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cli.main as cli_main


runner = CliRunner()


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise cli_main.requests.HTTPError(f"status {self.status_code}")


@pytest.fixture
def cli_results():
    return [
        {
            "content": "echo test command",
            "type": "cli_command",
            "description": "test command",
            "metadata": {"count": 4},
        }
    ]


def test_search_copy_copies_first_result(monkeypatch, cli_results):
    copied = {}

    monkeypatch.setattr(cli_main, "_search_memories", lambda query, limit, memory_type=None: cli_results)
    monkeypatch.setattr(cli_main.pyperclip, "copy", lambda value: copied.setdefault("value", value))

    result = runner.invoke(cli_main.app, ["search", "test", "--copy"])

    assert result.exit_code == 0
    assert copied["value"] == "echo test command"
    assert "✅ 已复制到剪贴板：echo test command" in result.output


def test_search_execute_runs_first_result(monkeypatch, cli_results):
    executed = {}

    monkeypatch.setattr(cli_main, "_search_memories", lambda query, limit, memory_type=None: cli_results)
    monkeypatch.setattr(
        cli_main.subprocess,
        "run",
        lambda cmd, shell: executed.update({"cmd": cmd, "shell": shell}),
    )

    result = runner.invoke(cli_main.app, ["search", "test", "--execute"])

    assert result.exit_code == 0
    assert executed == {"cmd": "echo test command", "shell": True}
    assert "🚀 执行命令：echo test command" in result.output


def test_search_interactive_can_copy_selected_result(monkeypatch, cli_results):
    copied = {}

    monkeypatch.setattr(cli_main, "_search_memories", lambda query, limit, memory_type=None: cli_results)
    monkeypatch.setattr(cli_main.pyperclip, "copy", lambda value: copied.setdefault("value", value))

    result = runner.invoke(cli_main.app, ["search", "test"], input="1\n2\n")

    assert result.exit_code == 0
    assert copied["value"] == "echo test command"
    assert "找到以下相关命令：" in result.output
    assert "✅ 已复制到剪贴板" in result.output


def test_watch_records_high_frequency_history(monkeypatch):
    test_home = Path.cwd() / ".test_tmp" / f"home-{uuid.uuid4().hex}"
    test_home.mkdir(parents=True)
    history_file = test_home / ".bash_history"
    history_file.write_text(
        "echo test watch command\n"
        "echo test watch command\n"
        "echo test watch command\n"
        "short\n",
        encoding="utf-8",
    )
    posted = []

    class FakeHomePath(type(Path())):
        pass

    fake_home = FakeHomePath(test_home)
    monkeypatch.setattr(cli_main.Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        cli_main,
        "_request",
        lambda method, path, **kwargs: posted.append((method, path, kwargs)) or FakeResponse({"status": "success"}),
    )

    try:
        result = runner.invoke(cli_main.app, ["watch", "--shell", "bash", "--auto-record-threshold", "3"])
    finally:
        shutil.rmtree(test_home, ignore_errors=True)

    assert result.exit_code == 0
    assert len(posted) == 1
    assert posted[0][0] == "POST"
    assert posted[0][1] == "/cli/command/record"
    assert posted[0][2]["json"] == {
        "command": "echo test watch command",
        "count": 3,
        "shell": "bash",
    }
    assert "✅ 已扫描历史命令，自动记录了1条高频命令" in result.output


def test_workflow_save_posts_workflow_payload(monkeypatch):
    posted = []

    monkeypatch.setattr(
        cli_main,
        "_request",
        lambda method, path, **kwargs: posted.append((method, path, kwargs)) or FakeResponse({"id": "1"}),
    )

    result = runner.invoke(cli_main.app, ["workflow", "save", "测试工作流", "echo step1", "echo step2"])

    assert result.exit_code == 0
    assert posted[0][0] == "POST"
    assert posted[0][1] == "/memory/"
    payload = posted[0][2]["json"]
    assert payload["type"] == "cli_workflow"
    assert json.loads(payload["content"])["steps"] == ["echo step1", "echo step2"]
    assert "✅ 工作流《测试工作流》已保存，包含2个步骤" in result.output


def test_workflow_run_prompts_and_executes_confirmed_steps(monkeypatch):
    workflow = {"name": "测试工作流", "steps": ["echo step1", "echo step2"]}
    executed = []

    monkeypatch.setattr(
        cli_main,
        "_search_memories",
        lambda query, limit, memory_type=None: [
            {"content": json.dumps(workflow, ensure_ascii=False), "type": "cli_workflow", "metadata": {}}
        ],
    )
    monkeypatch.setattr(cli_main.subprocess, "run", lambda cmd, shell: executed.append((cmd, shell)))

    result = runner.invoke(cli_main.app, ["workflow", "run", "测试工作流"], input="y\nn\n")

    assert result.exit_code == 0
    assert executed == [("echo step1", True)]
    assert "🚀 开始执行工作流《测试工作流》，共2个步骤" in result.output
    assert "⏭️  跳过该步骤" in result.output
