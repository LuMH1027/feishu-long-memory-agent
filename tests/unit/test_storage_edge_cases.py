"""深层测试：存储引擎边界情况"""
import sys
import types
from types import SimpleNamespace

import pytest

sys.modules.setdefault(
    "chromadb",
    types.SimpleNamespace(
        PersistentClient=lambda path: SimpleNamespace(
            get_or_create_collection=lambda **kwargs: SimpleNamespace(
                add=lambda **kw: None,
                query=lambda **kw: {"ids": [[]], "distances": [[]]},
                delete=lambda **kw: None,
            )
        )
    ),
)
sys.modules.setdefault(
    "openai",
    types.SimpleNamespace(
        OpenAI=lambda **kwargs: SimpleNamespace(
            embeddings=SimpleNamespace(create=lambda **kw: None)
        )
    ),
)

from core import storage


class FakeDB:
    def __init__(self, should_fail_commit=False):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshed = []
        self.rolled_back = False
        self._should_fail_commit = should_fail_commit

    def add(self, item):
        self.added.append(item)

    def commit(self):
        if self._should_fail_commit and self.commits == 0:
            raise RuntimeError("DB commit failed")
        self.commits += 1

    def refresh(self, item):
        self.refreshed.append(item)

    def delete(self, item):
        self.deleted.append(item)

    def rollback(self):
        self.rolled_back = True

    def query(self, model):
        return FakeQuery(None)


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, expression):
        return self

    def first(self):
        return self.result

    def all(self):
        return self.result or []


class TestSaveMemoryDegradation:
    def test_succeeds_when_vector_client_raises(self, monkeypatch):
        db = FakeDB()
        memory_data = SimpleNamespace(
            content="test content",
            type="cli_command",
            source="cli",
            user_id="u1",
            team_id="t1",
        )
        monkeypatch.setattr(storage, "get_embedding", lambda text: [0.1])
        monkeypatch.setattr(
            storage,
            "vector_client",
            SimpleNamespace(
                add_memory=lambda **kw: (_ for _ in ()).throw(RuntimeError("VectorDB down")),
                delete_memory=lambda mid: None,
            ),
        )

        saved = storage.save_memory(db, memory_data)
        assert saved.id is not None
        assert db.commits >= 1
        # vector_status should be "error" in metadata
        import json
        meta = json.loads(saved.memory_metadata)
        assert meta["vector_status"] == "error"

    def test_succeeds_when_embedding_raises(self, monkeypatch):
        db = FakeDB()
        memory_data = SimpleNamespace(
            content="test",
            type="cli_command",
            source="cli",
            user_id="u1",
            team_id="t1",
        )
        monkeypatch.setattr(
            storage,
            "get_embedding",
            lambda text: (_ for _ in ()).throw(RuntimeError("Embedding API down")),
        )
        monkeypatch.setattr(
            storage,
            "vector_client",
            SimpleNamespace(
                add_memory=lambda **kw: None,
                delete_memory=lambda mid: None,
            ),
        )

        saved = storage.save_memory(db, memory_data)
        assert saved.id is not None
        import json
        meta = json.loads(saved.memory_metadata)
        assert meta["vector_status"] == "error"

    def test_rollback_on_db_failure(self, monkeypatch):
        db = FakeDB(should_fail_commit=True)
        memory_data = SimpleNamespace(
            content="test",
            type="cli_command",
            source="cli",
            user_id="u1",
            team_id="t1",
        )

        with pytest.raises(RuntimeError, match="DB commit failed"):
            storage.save_memory(db, memory_data)
        assert db.rolled_back is True

    def test_records_ok_vector_status(self, monkeypatch):
        db = FakeDB()
        memory_data = SimpleNamespace(
            content="test",
            type="cli_command",
            source="cli",
            user_id="u1",
            team_id="t1",
        )
        monkeypatch.setattr(storage, "get_embedding", lambda text: [0.1, 0.2])
        monkeypatch.setattr(
            storage,
            "vector_client",
            SimpleNamespace(
                add_memory=lambda **kw: None,
                delete_memory=lambda mid: None,
            ),
        )

        saved = storage.save_memory(db, memory_data)
        import json
        meta = json.loads(saved.memory_metadata)
        assert meta["vector_status"] == "ok"


class TestDeleteMemoryEdgeCases:
    def test_returns_false_for_nonexistent_memory(self, monkeypatch):
        db = FakeDB()
        db.query = lambda model: FakeQuery(None)
        monkeypatch.setattr(
            storage,
            "vector_client",
            SimpleNamespace(delete_memory=lambda mid: None),
        )
        assert storage.delete_memory(db, "nonexistent") is False

    def test_succeeds_even_if_vector_delete_fails(self, monkeypatch):
        memory = SimpleNamespace(id="mem-1")
        db = FakeDB()
        db.query = lambda model: FakeQuery(memory)
        monkeypatch.setattr(
            storage,
            "vector_client",
            SimpleNamespace(
                delete_memory=lambda mid: (_ for _ in ()).throw(RuntimeError("VectorDB down"))
            ),
        )
        assert storage.delete_memory(db, "mem-1") is True
        assert memory in db.deleted

    def test_rollback_on_db_delete_failure(self, monkeypatch):
        memory = SimpleNamespace(id="mem-1")
        db = FakeDB()
        db._should_fail_commit = True
        db.query = lambda model: FakeQuery(memory)
        monkeypatch.setattr(
            storage,
            "vector_client",
            SimpleNamespace(delete_memory=lambda mid: None),
        )
        with pytest.raises(RuntimeError):
            storage.delete_memory(db, "mem-1")
        assert db.rolled_back is True


class TestMemoryMetadataHelper:
    def test_extracts_metadata_from_data_with_dict_metadata(self):
        data = SimpleNamespace(metadata={"count": 5})
        assert storage._memory_metadata(data) == {"count": 5}

    def test_returns_empty_dict_for_none_metadata(self):
        data = SimpleNamespace(metadata=None)
        assert storage._memory_metadata(data) == {}

    def test_returns_empty_dict_for_missing_attribute(self):
        data = SimpleNamespace()
        assert storage._memory_metadata(data) == {}
