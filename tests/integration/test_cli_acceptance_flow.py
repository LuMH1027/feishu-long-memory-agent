import asyncio
import json
import shutil
import uuid
from pathlib import Path

from typer.testing import CliRunner

import cli.main as cli_main
from backend.routers import cli as cli_router
from backend.routers import memory as memory_router
from backend.schemas.memory import MemoryCreate, MemoryRetrieveRequest


runner = CliRunner()


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        return None


class FakeBackend:
    def request(self, method, path, **kwargs):
        params = kwargs.get("params") or {}
        payload = kwargs.get("json") or {}

        if method == "POST" and path == "/cli/command/record":
            return FakeResponse(asyncio.run(cli_router.record_command(cli_router.CommandRecordRequest(**payload))))

        if method == "POST" and path == "/cli/command/suggest":
            return FakeResponse(asyncio.run(cli_router.suggest_command(cli_router.CommandSuggestRequest(**payload))))

        if method == "GET" and path == "/cli/command/list":
            return FakeResponse(asyncio.run(cli_router.list_commands(limit=params.get("limit", 10))))

        if method == "POST" and path == "/memory/":
            return FakeResponse(memory_router.store_memory(memory_router.MemoryStoreRequest(**payload)))

        if method == "POST" and path == "/memory/extract":
            return FakeResponse(memory_router.extract_and_store_memory(MemoryCreate(**payload)))

        if method == "GET" and path == "/memory/search":
            return FakeResponse(
                memory_router.search_memories(
                    query=params["query"],
                    limit=params.get("limit", 5),
                    type=params.get("type"),
                )
            )

        if method == "POST" and path == "/memory/retrieve":
            return FakeResponse(memory_router.retrieve_memories(MemoryRetrieveRequest(**payload)))

        if method == "GET" and path == "/memory/list":
            return FakeResponse(memory_router.list_memories(limit=params.get("limit", 10)))

        raise AssertionError(f"Unhandled fake backend request: {method} {path}")


def setup_function():
    cli_router.temp_command_storage.clear()
    memory_router.temp_memory_storage.clear()


def test_phase4_cli_acceptance_flow(monkeypatch):
    backend = FakeBackend()
    copied = {}
    executed = []
    test_home = Path.cwd() / ".test_tmp" / f"acceptance-{uuid.uuid4().hex}"
    test_home.mkdir(parents=True)
    history_file = test_home / ".bash_history"
    history_file.write_text(
        "docker ps -a --filter status=exited\n"
        "docker ps -a --filter status=exited\n"
        "docker ps -a --filter status=exited\n",
        encoding="utf-8",
    )

    class FakeHomePath(type(Path())):
        pass

    monkeypatch.setattr(cli_main.Path, "home", lambda: FakeHomePath(test_home))
    monkeypatch.setattr(cli_main, "_request", backend.request)
    monkeypatch.setattr(cli_main.pyperclip, "copy", lambda value: copied.setdefault("value", value))
    monkeypatch.setattr(cli_main.subprocess, "run", lambda cmd, shell: executed.append((cmd, shell)))

    try:
        watch_result = runner.invoke(cli_main.app, ["watch", "--shell", "bash", "--auto-record-threshold", "3"])
        search_result = runner.invoke(cli_main.app, ["search", "docker exited"])
        copy_result = runner.invoke(cli_main.app, ["search", "docker exited", "--copy"])
        save_result = runner.invoke(
            cli_main.app,
            ["workflow", "save", "docker清理", "docker system prune -f", "docker volume prune -f"],
        )
        run_result = runner.invoke(cli_main.app, ["workflow", "run", "docker清理"], input="n\nn\n")
        list_result = runner.invoke(cli_main.app, ["list"])
    finally:
        shutil.rmtree(test_home, ignore_errors=True)

    assert watch_result.exit_code == 0
    assert "✅ 已扫描历史命令，自动记录了1条高频命令" in watch_result.output

    assert search_result.exit_code == 0
    assert "docker ps -a --filter status=exited" in search_result.output

    assert copy_result.exit_code == 0
    assert copied["value"] == "docker ps -a --filter status=exited"

    assert save_result.exit_code == 0
    assert "✅ 工作流《docker清理》已保存，包含2个步骤" in save_result.output

    assert run_result.exit_code == 0
    assert "🚀 开始执行工作流《docker清理》，共2个步骤" in run_result.output
    assert executed == []

    assert list_result.exit_code == 0
    assert "docker ps -a --filter status=exited" in list_result.output
    assert "cli_workflow" in list_result.output
    assert json.dumps("docker清理", ensure_ascii=False).strip('"') in list_result.output
