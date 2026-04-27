import asyncio
import importlib
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.modules.setdefault(
    "chromadb",
    types.SimpleNamespace(
        PersistentClient=lambda path: SimpleNamespace(
            get_or_create_collection=lambda **kwargs: SimpleNamespace(
                add=lambda **add_kwargs: None,
                query=lambda **query_kwargs: {"ids": [[]], "distances": [[]]},
                delete=lambda **delete_kwargs: None,
            )
        )
    ),
)
sys.modules.setdefault(
    "openai",
    types.SimpleNamespace(OpenAI=lambda **kwargs: SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kw: None))),
)

from backend.routers import memory
from backend.schemas.memory import MemoryCreate, MemoryRetrieveRequest


def test_memory_extract_delegates_to_storage(monkeypatch):
    saved = SimpleNamespace(id="mem-1")
    calls = []
    monkeypatch.setattr(
        memory.storage,
        "save_memory",
        lambda db, memory_data: calls.append((db, memory_data)) or saved,
    )
    memory_data = MemoryCreate(content="hello", type="user_preference", source="cli")

    assert memory.extract_and_store_memory(memory_data, db="db") is saved
    assert calls == [("db", memory_data)]


def test_memory_retrieve_delegates_to_retriever(monkeypatch):
    memories = [SimpleNamespace(id="mem-1")]
    calls = []
    monkeypatch.setattr(
        memory.retriever,
        "search_memories",
        lambda db, query, top_k, threshold: calls.append((db, query, top_k, threshold)) or memories,
    )
    request = MemoryRetrieveRequest(query="deploy", top_k=3, threshold=0.5)

    assert memory.retrieve_memories(request, db="db") == memories
    assert calls == [("db", "deploy", 3, 0.5)]


def test_memory_get_delegates_to_storage(monkeypatch):
    found = SimpleNamespace(id="mem-1")
    monkeypatch.setattr(memory.storage, "get_memory_by_id", lambda db, memory_id: found)

    assert memory.get_memory("mem-1", db="db") is found


def test_memory_delete_delegates_to_storage(monkeypatch):
    deleted = []
    monkeypatch.setattr(memory.storage, "delete_memory", lambda db, memory_id: deleted.append((db, memory_id)))

    assert memory.delete_memory("mem-1", db="db") == {"status": "ok", "message": "记忆删除成功"}
    assert deleted == [("db", "mem-1")]


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
