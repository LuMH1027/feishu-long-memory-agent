import asyncio
import importlib
import sys
import types

import pytest
from fastapi import HTTPException

from backend.routers import memory
from backend.routers import cli
from backend.schemas.memory import MemoryCreate, MemoryRetrieveRequest


def setup_function():
    memory.temp_memory_storage.clear()
    cli.temp_command_storage.clear()


def test_memory_extract_stores_memory():
    result = memory.extract_and_store_memory(MemoryCreate(content="hello", type="user_preference", source="cli"))

    assert result["content"] == "hello"
    assert result["type"] == "user_preference"
    assert result["source"] == "cli"
    assert result in memory.temp_memory_storage


def test_memory_store_preserves_description_and_metadata():
    result = memory.store_memory(
        memory.MemoryStoreRequest(
            content='{"name": "docker清理"}',
            type="cli_workflow",
            description="工作流：docker清理",
            metadata={"name": "docker清理", "steps": ["docker system prune -f"]},
        )
    )

    assert result["description"] == "工作流：docker清理"
    assert result["metadata"]["steps"] == ["docker system prune -f"]


def test_memory_search_matches_all_query_tokens_and_filters_type():
    memory.store_memory(
        memory.MemoryStoreRequest(content="docker ps -a --filter status=exited", type="cli_command", metadata={"count": 3})
    )
    memory.store_memory(memory.MemoryStoreRequest(content="docker images", type="cli_command", metadata={"count": 10}))
    memory.store_memory(memory.MemoryStoreRequest(content="docker清理", type="cli_workflow"))

    results = memory.search_memories(query="docker exited", limit=5, type="cli_command")

    assert [item["content"] for item in results] == ["docker ps -a --filter status=exited"]
    assert results[0]["hit_count"] == 1


def test_memory_search_matches_chinese_intent_with_command_terms():
    memory.store_memory(
        memory.MemoryStoreRequest(
            content="docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2",
            type="docker启动命令",
        )
    )

    results = memory.search_memories(query="启动webapp容器", limit=5)

    assert [item["content"] for item in results] == [
        "docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2"
    ]


def test_memory_retrieve_uses_search_logic():
    memory.store_memory(memory.MemoryStoreRequest(content="git status --short", type="cli_command"))

    results = memory.retrieve_memories(MemoryRetrieveRequest(query="git short", top_k=1))

    assert [item["content"] for item in results] == ["git status --short"]


def test_memory_correction_supersedes_previous_same_topic_memory():
    old_memory = memory.store_memory(
        memory.MemoryStoreRequest(
            content="以后周报发给 A：python scripts/send_weekly.py --to a@example.com",
            type="周报发送命令",
            source="cli",
        )
    )
    new_memory = memory.store_memory(
        memory.MemoryStoreRequest(
            content="不对，以后周报发给 B：python scripts/send_weekly.py --to b@example.com",
            type="周报发送命令",
            source="cli",
        )
    )

    results = memory.search_memories(query="发送周报", limit=5, type="周报发送命令")

    assert [item["content"] for item in results] == [new_memory["content"]]
    assert old_memory["metadata"]["status"] == "inactive"
    assert old_memory["metadata"]["superseded_by"] == new_memory["id"]
    assert new_memory["metadata"]["status"] == "active"
    assert new_memory["metadata"]["supersedes"] == [old_memory["id"]]


def test_memory_list_returns_recent_items():
    first = memory.store_memory(memory.MemoryStoreRequest(content="first", type="note"))
    second = memory.store_memory(memory.MemoryStoreRequest(content="second", type="note"))

    assert memory.list_memories(limit=1) == [second]
    assert memory.list_memories(limit=2) == [first, second]


def test_memory_get_and_delete_by_id():
    result = memory.store_memory(memory.MemoryStoreRequest(content="delete me", type="note"))

    assert memory.get_memory(result["id"]) == result
    assert memory.delete_memory(result["id"]) == {"status": "ok", "message": "记忆删除成功"}
    assert memory.temp_memory_storage == []


def test_memory_get_missing_raises_404():
    with pytest.raises(HTTPException) as exc_info:
        memory.get_memory("missing")

    assert exc_info.value.status_code == 404


class FakeRequest:
    def __init__(self, payload, headers=None, body=b"body"):
        self._payload = payload
        self._body = body
        self.headers = headers or {
            "X-Lark-Signature": "signature",
            "X-Lark-Request-Timestamp": "timestamp",
            "X-Lark-Request-Nonce": "nonce",
        }

    async def body(self):
        return self._body

    async def json(self):
        return self._payload


def load_feishu_router(validate_result):
    verification = types.SimpleNamespace(validate_signature=lambda *args: validate_result)
    sys.modules["feishu"] = types.SimpleNamespace(verification=verification)
    sys.modules["feishu.verification"] = verification
    sys.modules.pop("backend.routers.feishu", None)
    return importlib.import_module("backend.routers.feishu")


def test_feishu_callback_returns_challenge_for_url_verification():
    feishu = load_feishu_router(True)
    request = FakeRequest({"type": "url_verification", "challenge": "abc"})

    assert asyncio.run(feishu.feishu_event_callback(request)) == {"challenge": "abc"}


def test_feishu_callback_returns_ok_for_normal_event():
    feishu = load_feishu_router(True)
    request = FakeRequest({"type": "event_callback"})

    assert asyncio.run(feishu.feishu_event_callback(request)) == {"status": "ok"}


def test_feishu_callback_rejects_invalid_signature():
    feishu = load_feishu_router(False)
    request = FakeRequest({"type": "event_callback"})

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(feishu.feishu_event_callback(request))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "签名验证失败"


def test_push_feishu_message_returns_ok():
    feishu = load_feishu_router(True)

    assert feishu.push_feishu_message("user-1", "hello") == {"status": "ok"}


def test_feishu_decision_extract_stores_structured_project_decision():
    feishu = load_feishu_router(True)

    response = feishu.extract_and_store_decision(
        feishu.DecisionExtractRequest(
            content="@机器人 以后 project-a 统一用 prod 命名空间部署，不再使用 staging，因为 staging 经常误连测试资源",
            chat_id="chat-1",
            user_id="user-1",
            message_id="msg-1",
        )
    )

    assert response["status"] == "stored"
    assert response["decision"]["project"] == "project-a"
    assert response["decision"]["preferred_terms"] == ["prod"]
    assert response["decision"]["rejected_terms"] == ["staging"]
    assert response["memory"]["type"] == "project_decision"
    assert response["memory"]["source"] == "feishu_group"
    assert response["memory"]["metadata"]["topic_key"] == "decision:chat-1:project-a"


def test_feishu_message_query_returns_cli_command_card():
    feishu = load_feishu_router(True)
    asyncio.run(
        cli.record_command(
            cli.CommandRecordRequest(
                command="kubectl rollout restart deploy/api-server -n prod",
                count=4,
                shell="bash",
                directory="E:/workspace/project-a",
                exit_code=0,
            )
        )
    )

    response = feishu.handle_feishu_message(
        feishu.FeishuMessage(
            content="谁知道 api-server 怎么重启？",
            chat_id="chat-1",
            mentioned=False,
        )
    )

    assert response["action"] == "suggest_cards"
    assert response["should_push"] is True
    assert response["cards"][0]["card_type"] == "cli_command"
    assert response["cards"][0]["command"] == "kubectl rollout restart deploy/api-server -n prod"


def test_feishu_decision_reorders_cli_suggestions_by_team_policy():
    feishu = load_feishu_router(True)
    asyncio.run(
        cli.record_command(
            cli.CommandRecordRequest(
                command="kubectl apply -f k8s/staging.yaml",
                count=10,
                shell="bash",
                directory="E:/workspace/project-a",
            )
        )
    )
    asyncio.run(
        cli.record_command(
            cli.CommandRecordRequest(
                command="kubectl apply -f k8s/prod.yaml",
                count=2,
                shell="bash",
                directory="E:/workspace/project-a",
            )
        )
    )
    feishu.extract_and_store_decision(
        feishu.DecisionExtractRequest(
            content="不对，project-a 以后统一用 prod 部署，不再使用 staging",
            chat_id="chat-1",
            user_id="lead-1",
        )
    )

    response = asyncio.run(
        cli.suggest_command(
            cli.CommandSuggestRequest(
                partial_command="kubectl apply",
                directory="E:/workspace/project-a",
            )
        )
    )

    assert [item["command"] for item in response["suggestions"]] == [
        "kubectl apply -f k8s/prod.yaml",
        "kubectl apply -f k8s/staging.yaml",
    ]
