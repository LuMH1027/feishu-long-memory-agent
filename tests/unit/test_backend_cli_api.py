import asyncio

from backend.main import health_check
from backend.routers import cli


def setup_function():
    cli.temp_command_storage.clear()


def test_health_check_contract():
    assert health_check() == {"status": "ok", "message": "记忆引擎服务运行正常"}


def test_record_command_creates_cli_memory():
    response = asyncio.run(
        cli.record_command(
            cli.CommandRecordRequest(
                command="pytest tests/unit",
                count=3,
                shell="powershell",
                directory="E:/repo",
            )
        )
    )

    assert response == {"status": "success"}
    assert cli.temp_command_storage == [
        {
            "id": 1,
            "command": "pytest tests/unit",
            "type": "cli_command",
            "description": "powershell命令",
            "metadata": {
                "count": 3,
                "shell": "powershell",
                "directory": "E:/repo",
                "first_used_at": cli.temp_command_storage[0]["metadata"]["first_used_at"],
                "last_used_at": cli.temp_command_storage[0]["metadata"]["last_used_at"],
            },
        }
    ]


def test_record_command_merges_duplicate_counts():
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="npm test", count=2, shell="bash")))
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="npm test", count=5, shell="bash")))

    assert len(cli.temp_command_storage) == 1
    assert cli.temp_command_storage[0]["metadata"]["count"] == 7


def test_suggest_command_filters_case_insensitively_and_sorts_by_count():
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="git status", count=2, shell="bash")))
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="git commit", count=5, shell="bash")))
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="pytest", count=10, shell="bash")))

    response = asyncio.run(cli.suggest_command(cli.CommandSuggestRequest(partial_command="GIT")))

    assert [item["command"] for item in response["suggestions"]] == ["git commit", "git status"]
    assert [item["count"] for item in response["suggestions"]] == [5, 2]


def test_suggest_command_matches_all_tokens_when_not_contiguous():
    asyncio.run(
        cli.record_command(
            cli.CommandRecordRequest(command="docker ps -a --filter status=exited", count=3, shell="powershell")
        )
    )

    response = asyncio.run(cli.suggest_command(cli.CommandSuggestRequest(partial_command="docker exited")))

    assert [item["command"] for item in response["suggestions"]] == ["docker ps -a --filter status=exited"]


def test_list_commands_returns_recent_records():
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="first", count=1, shell="bash")))
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="second", count=1, shell="bash")))

    response = asyncio.run(cli.list_commands(limit=1))

    assert [item["command"] for item in response] == ["second"]


def test_suggest_command_returns_empty_list_when_no_match():
    response = asyncio.run(cli.suggest_command(cli.CommandSuggestRequest(partial_command="docker")))

    assert response == {"suggestions": []}
