import configparser
import shutil
import uuid
from pathlib import Path

from typer.testing import CliRunner

import cli.main as cli_main


runner = CliRunner()


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self.data = data if data is not None else {}
        self.status_code = status_code

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise cli_main.requests.HTTPError(f"status {self.status_code}")


def workspace_tmp_dir():
    path = Path.cwd() / ".test_tmp" / f"cli-basic-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def test_get_api_base_prefers_global_config(monkeypatch):
    temp_dir = workspace_tmp_dir()
    try:
        config_file = temp_dir / "config.ini"
        config = configparser.ConfigParser()
        config["default"] = {"api_base": "http://configured/api"}
        with open(config_file, "w", encoding="utf-8") as f:
            config.write(f)

        monkeypatch.setattr(cli_main, "CONFIG_FILE", config_file)
        monkeypatch.setenv("API_BASE", "http://env/api")

        assert cli_main.get_api_base() == "http://configured/api"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_api_base_falls_back_to_env(monkeypatch):
    temp_dir = workspace_tmp_dir()
    try:
        monkeypatch.setattr(cli_main, "CONFIG_FILE", temp_dir / "missing.ini")
        monkeypatch.setenv("API_BASE", "http://env/api")

        assert cli_main.get_api_base() == "http://env/api"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_configure_writes_global_config(monkeypatch):
    temp_dir = workspace_tmp_dir()
    try:
        config_dir = temp_dir / ".mem_agent"
        config_file = config_dir / "config.ini"
        monkeypatch.setattr(cli_main, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(cli_main, "CONFIG_FILE", config_file)
        monkeypatch.setattr(cli_main, "API_BASE", "http://default/api")

        result = runner.invoke(cli_main.app, ["configure"], input="http://saved/api\n")

        saved = configparser.ConfigParser()
        saved.read(config_file)
        assert result.exit_code == 0
        assert saved["default"]["api_base"] == "http://saved/api"
        assert f"✅ 配置已保存到 {config_file}" in result.output
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_memorize_posts_expected_payload(monkeypatch):
    calls = []
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setattr(
        cli_main,
        "_request",
        lambda method, path, **kwargs: calls.append((method, path, kwargs)) or FakeResponse({"id": "mem-1"}),
    )

    result = runner.invoke(cli_main.app, ["memorize", "remember this", "--type", "cli_command"])

    assert result.exit_code == 0
    assert calls == [
        (
            "POST",
            "/memory/extract",
            {
                "json": {
                    "content": "remember this",
                    "type": "cli_command",
                    "source": "cli",
                    "user_id": "tester",
                }
            },
        )
    ]
    assert "✅ 记忆已保存，ID: mem-1" in result.output


def test_memorize_reports_request_error(monkeypatch):
    def failing_request(method, path, **kwargs):
        raise cli_main.requests.ConnectionError("offline")

    monkeypatch.setattr(cli_main, "_request", failing_request)

    result = runner.invoke(cli_main.app, ["memorize", "remember this"])

    assert result.exit_code == 0
    assert "❌ 保存失败: offline" in result.output


def test_list_prints_empty_state(monkeypatch):
    monkeypatch.setattr(cli_main, "_request", lambda method, path, **kwargs: FakeResponse([]))

    result = runner.invoke(cli_main.app, ["list", "--limit", "3"])

    assert result.exit_code == 0
    assert "暂无记忆" in result.output


def test_list_prints_memory_summaries(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli_main,
        "_request",
        lambda method, path, **kwargs: calls.append((method, path, kwargs))
        or FakeResponse([{"id": "1", "type": "user_preference", "content": "abcdefghijklmnopqrstuvwxyz"}]),
    )

    result = runner.invoke(cli_main.app, ["list", "--limit", "7"])

    assert result.exit_code == 0
    assert calls[0] == ("GET", "/memory/list", {"params": {"limit": 7}})
    assert "[1] [user_preference] abcdefghijklmnopqrstuvwxyz..." in result.output


def test_search_memories_uses_get_search_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli_main,
        "_request",
        lambda method, path, **kwargs: calls.append((method, path, kwargs))
        or FakeResponse([{"command": "git status", "metadata": {"type": "cli_command", "count": 2}}]),
    )

    results = cli_main._search_memories("git", 5, "cli_command")

    assert calls == [("GET", "/memory/search", {"params": {"query": "git", "limit": 5, "type": "cli_command"}})]
    assert results == [
        {
            "content": "git status",
            "type": "cli_command",
            "description": "无描述",
            "metadata": {"type": "cli_command", "count": 2},
        }
    ]


def test_search_memories_falls_back_to_retrieve_endpoint(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/memory/search":
            raise cli_main.requests.HTTPError("missing")
        return FakeResponse([{"content": "echo fallback", "type": "cli_command"}])

    monkeypatch.setattr(cli_main, "_request", fake_request)

    results = cli_main._search_memories("echo", 2)

    assert calls == [
        ("GET", "/memory/search", {"params": {"query": "echo", "limit": 2}}),
        ("POST", "/memory/retrieve", {"json": {"query": "echo", "top_k": 2}}),
    ]
    assert results[0]["content"] == "echo fallback"


def test_clear_requires_confirmation():
    result = runner.invoke(cli_main.app, ["clear"], input="n\n")

    assert result.exit_code == 0
    assert "✅ 记忆已清空" not in result.output


def test_clear_force_skips_confirmation():
    result = runner.invoke(cli_main.app, ["clear", "--force"])

    assert result.exit_code == 0
    assert "✅ 记忆已清空" in result.output
