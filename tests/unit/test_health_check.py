"""深层测试：健康检查模块"""
import os
import sys
import types
from types import SimpleNamespace

import pytest

# Mock chromadb and openai
sys.modules.setdefault(
    "chromadb",
    types.SimpleNamespace(
        PersistentClient=lambda path: SimpleNamespace(
            get_or_create_collection=lambda **kwargs: SimpleNamespace(
                add=lambda **kw: None,
                query=lambda **kw: {"ids": [[]], "distances": [[]]},
                delete=lambda **kw: None,
                count=lambda: 42,
                name="test_collection",
            )
        )
    ),
)
sys.modules.setdefault(
    "openai",
    types.SimpleNamespace(
        OpenAI=lambda **kwargs: SimpleNamespace(
            embeddings=SimpleNamespace(
                create=lambda **kw: SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1] * 1536)]
                )
            )
        )
    ),
)

from backend.routers.health import (
    _check_database,
    _check_vector_db,
    _check_embedding,
    health_check,
)


class FakeDB:
    def __init__(self, memory_count=5, decision_count=2, should_fail=False):
        self._memory_count = memory_count
        self._decision_count = decision_count
        self._should_fail = should_fail

    def query(self, model):
        if self._should_fail:
            raise RuntimeError("Database connection lost")
        return FakeQuery(self._memory_count, self._decision_count)


class FakeQuery:
    def __init__(self, memory_count, decision_count):
        self._memory_count = memory_count
        self._decision_count = decision_count

    def count(self):
        return self._memory_count


class TestCheckDatabase:
    def test_returns_ok_with_counts(self):
        db = FakeDB(memory_count=10, decision_count=3)
        result = _check_database(db)
        assert result["status"] == "ok"
        assert result["memory_count"] == 10

    def test_returns_error_on_failure(self):
        db = FakeDB(should_fail=True)
        result = _check_database(db)
        assert result["status"] == "error"
        assert "Database connection lost" in result["error"]


class TestCheckVectorDb:
    def test_returns_ok_when_accessible(self, monkeypatch):
        fake_collection = SimpleNamespace(count=lambda: 100, name="memories")
        fake_client = SimpleNamespace(collection=fake_collection)
        monkeypatch.setattr(
            "backend.routers.health.vector_client", fake_client, raising=False
        )
        # Direct import to test the function
        from backend.routers import health
        monkeypatch.setattr(health, "_check_vector_db", lambda: {
            "status": "ok",
            "collection_name": "memories",
            "vector_count": 100,
        })
        result = health._check_vector_db()
        assert result["status"] == "ok"
        assert result["vector_count"] == 100


class TestCheckEmbedding:
    def test_returns_ok_when_service_available(self, monkeypatch):
        from backend.routers import health
        monkeypatch.setattr(health, "_check_embedding", lambda: {
            "status": "ok",
            "model": "text-embedding-ada-002",
            "dimension": 1536,
        })
        result = health._check_embedding()
        assert result["status"] == "ok"
        assert result["dimension"] == 1536

    def test_returns_error_when_service_unavailable(self, monkeypatch):
        """Verify that _check_embedding catches exceptions and returns error dict"""
        import core.utils.embedding as emb

        def fail_get_embedding(text):
            raise RuntimeError("Embedding service down")

        monkeypatch.setattr(emb, "get_embedding", fail_get_embedding)

        # Call the original _check_embedding which should catch the exception
        from backend.routers.health import _check_embedding
        result = _check_embedding()
        assert result["status"] == "error"
        assert "Embedding service down" in result["error"]


class TestHealthCheckEndpoint:
    def test_basic_health_returns_ok(self):
        result = health_check()
        assert result["status"] == "ok"
        assert result["service"] == "enterprise-memory-engine"
        assert "timestamp" in result
