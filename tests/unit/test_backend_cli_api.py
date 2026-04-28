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
                    "directories": {"E:/repo": 3},
                    "command_pattern": {
                        "program": "pytest",
                        "subcommand": "tests/unit",
                        "command_family": "pytest tests/unit",
                        "flags": {},
                        "positionals": [],
                        "paths": [],
                    },
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


def test_suggest_command_prioritizes_matching_directory_context():
    asyncio.run(
        cli.record_command(
            cli.CommandRecordRequest(
                command="npm run deploy -- --env staging",
                count=8,
                shell="powershell",
                directory="E:/workspace/project-a",
            )
        )
    )
    asyncio.run(
        cli.record_command(
            cli.CommandRecordRequest(
                command="npm run deploy -- --env prod",
                count=2,
                shell="powershell",
                directory="E:/workspace/project-b",
            )
        )
    )

    response = asyncio.run(
        cli.suggest_command(
            cli.CommandSuggestRequest(
                partial_command="npm deploy",
                directory="E:/workspace/project-b",
            )
        )
    )

    assert [item["command"] for item in response["suggestions"]] == [
        "npm run deploy -- --env prod",
        "npm run deploy -- --env staging",
    ]


def test_record_command_tracks_execution_feedback_counts():
    asyncio.run(
        cli.record_command(cli.CommandRecordRequest(command="npm test", count=1, shell="bash", exit_code=0))
    )
    asyncio.run(
        cli.record_command(cli.CommandRecordRequest(command="npm test", count=1, shell="bash", exit_code=1))
    )

    metadata = cli.temp_command_storage[0]["metadata"]
    assert metadata["count"] == 2
    assert metadata["success_count"] == 1
    assert metadata["failure_count"] == 1
    assert metadata["last_exit_code"] == 1
    assert metadata["exit_code"] == 1
    assert "last_failed_at" in metadata


def test_suggest_command_prioritizes_successful_command_when_other_signals_tie():
    asyncio.run(
        cli.record_command(cli.CommandRecordRequest(command="npm run deploy-success", count=2, shell="bash", exit_code=0))
    )
    asyncio.run(
        cli.record_command(cli.CommandRecordRequest(command="npm run deploy-fail", count=2, shell="bash", exit_code=1))
    )

    response = asyncio.run(cli.suggest_command(cli.CommandSuggestRequest(partial_command="npm deploy")))

    assert [item["command"] for item in response["suggestions"]] == [
        "npm run deploy-success",
        "npm run deploy-fail",
    ]


def test_list_commands_returns_recent_records():
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="first", count=1, shell="bash")))
    asyncio.run(cli.record_command(cli.CommandRecordRequest(command="second", count=1, shell="bash")))

    response = asyncio.run(cli.list_commands(limit=1))

    assert [item["command"] for item in response] == ["second"]


def test_suggest_command_returns_empty_list_when_no_match():
    response = asyncio.run(cli.suggest_command(cli.CommandSuggestRequest(partial_command="docker")))

    assert response == {"suggestions": []}
