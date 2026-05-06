import sys
import types
from types import SimpleNamespace

import pytest

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

from core import command_parser, retriever, storage
from core.utils import embedding
from db.vector.client import VectorClient
import init_db


class FakeDB:
    def __init__(self, query_result=None):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshed = []
        self.query_result = query_result

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        self.refreshed.append(item)

    def delete(self, item):
        self.deleted.append(item)

    def query(self, model):
        return FakeQuery(self.query_result)


class FakeQuery:
    def __init__(self, result):
        self.result = result
        self.filtered = False

    def filter(self, expression):
        self.filtered = True
        return self

    def first(self):
        if isinstance(self.result, list):
            return self.result[0] if self.result else None
        return self.result

    def all(self):
        return self.result or []


def test_save_memory_persists_relational_and_vector_records(monkeypatch):
    vector_calls = []
    fake_uuid = SimpleNamespace(hex="abcdef1234567890ffff")
    db = FakeDB()
    memory_data = SimpleNamespace(
        content="remember cli command",
        type="cli_command",
        source="cli",
        user_id="user-1",
        team_id="team-1",
    )

    monkeypatch.setattr(storage.uuid, "uuid4", lambda: fake_uuid)
    monkeypatch.setenv("DEFAULT_MEMORY_EXPIRE_DAYS", "10")
    monkeypatch.setattr(storage, "get_embedding", lambda text: [0.1, 0.2])
    monkeypatch.setattr(
        storage,
        "vector_client",
        SimpleNamespace(add_memory=lambda **kwargs: vector_calls.append(kwargs), delete_memory=lambda memory_id: None),
    )

    saved = storage.save_memory(db, memory_data)

    assert saved.id == "abcdef1234567890"
    assert saved.content == "remember cli command"
    assert saved.type == "cli_command"
    assert db.added == [saved]
    assert db.commits == 2  # 一次保存记忆，一次更新vector_status
    assert db.refreshed == [saved]
    assert vector_calls == [
        {
            "memory_id": "abcdef1234567890",
            "content": "remember cli command",
            "embedding": [0.1, 0.2],
            "metadata": {
                "type": "cli_command",
                "source": "cli",
                "user_id": "user-1",
                "team_id": "team-1",
            },
        }
    ]


def test_parse_command_extracts_program_flags_positionals_and_paths():
    pattern = command_parser.parse_command(
        "docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2"
    )

    assert pattern == {
        "program": "docker",
        "subcommand": "run",
        "command_family": "docker run",
        "flags": {"-p": "8080:80", "-v": "/data:/app/data", "--name": "webapp"},
        "positionals": ["my-image:1.2"],
        "paths": ["/data:/app/data"],
    }


def test_pattern_text_makes_flags_searchable():
    pattern = command_parser.parse_command("kubectl logs deploy/api -n prod --tail=200")

    text = command_parser.pattern_text(pattern)

    assert "kubectl logs" in text
    assert "-n prod" in text
    assert "--tail 200" in text


def test_get_memory_by_id_returns_first_query_result():
    memory = SimpleNamespace(id="mem-1")
    db = FakeDB(query_result=memory)

    assert storage.get_memory_by_id(db, "mem-1") is memory


def test_delete_memory_removes_relational_and_vector_records(monkeypatch):
    memory = SimpleNamespace(id="mem-1")
    db = FakeDB(query_result=memory)
    deleted_vectors = []
    monkeypatch.setattr(storage, "vector_client", SimpleNamespace(delete_memory=deleted_vectors.append))

    assert storage.delete_memory(db, "mem-1") is True
    assert db.deleted == [memory]
    assert db.commits == 1
    assert deleted_vectors == ["mem-1"]


def test_delete_memory_is_noop_when_missing(monkeypatch):
    db = FakeDB(query_result=None)
    monkeypatch.setattr(storage, "vector_client", SimpleNamespace(delete_memory=pytest.fail))

    assert storage.delete_memory(db, "missing") is False
    assert db.deleted == []
    assert db.commits == 0


def test_search_memories_uses_vector_order_and_increments_hit_count(monkeypatch):
    memory_a = SimpleNamespace(id="a", type="user_preference", hit_count=0)
    memory_b = SimpleNamespace(id="b", type="user_preference", hit_count=2)
    db = FakeDB(query_result=[memory_a, memory_b])
    vector_search_calls = []

    monkeypatch.setattr(retriever, "get_embedding", lambda query: [0.3, 0.4])
    monkeypatch.setattr(
        retriever,
        "vector_client",
        SimpleNamespace(
            search_memories=lambda **kwargs: vector_search_calls.append(kwargs)
            or [{"id": "b"}, {"id": "a"}, {"id": "missing"}]
        ),
    )

    results = retriever.search_memories(db, "query", top_k=3, threshold=0.6)

    assert vector_search_calls == [{"query_embedding": [0.3, 0.4], "top_k": 3, "threshold": 0.6}]
    assert results == [memory_b, memory_a]
    assert memory_b.hit_count == 3
    assert memory_a.hit_count == 1
    assert db.commits == 1


def test_search_memories_reads_defaults_from_environment(monkeypatch):
    db = FakeDB(query_result=[])
    calls = []
    monkeypatch.setenv("RETRIEVE_TOP_K", "9")
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.42")
    monkeypatch.setattr(retriever, "get_embedding", lambda query: [1.0])
    monkeypatch.setattr(
        retriever,
        "vector_client",
        SimpleNamespace(search_memories=lambda **kwargs: calls.append(kwargs) or []),
    )

    assert retriever.search_memories(db, "query") == []
    assert calls == [{"query_embedding": [1.0], "top_k": 9, "threshold": 0.42}]


def test_calculate_cli_relevance_score_combines_frequency_recency_and_prefix():
    memory = SimpleNamespace(
        content="git status --short",
        similarity_score=0.4,
        cli_metadata={"count": 10, "last_used_at": "2000-01-01T00:00:00"},
    )

    assert retriever.calculate_cli_relevance_score("git", memory) == pytest.approx(0.9)


def test_calculate_cli_relevance_score_includes_success_rate():
    memory = SimpleNamespace(
        content="npm run deploy",
        similarity_score=0.4,
        cli_metadata={"success_count": 3, "failure_count": 1},
    )

    assert retriever.calculate_cli_relevance_score("deploy", memory) == pytest.approx(0.55)


def test_calculate_cli_relevance_score_ignores_invalid_metadata_values():
    memory = SimpleNamespace(
        content="docker compose up",
        similarity_score=0.5,
        cli_metadata={"count": "many", "last_used_at": "not-a-date"},
    )

    assert retriever.calculate_cli_relevance_score("npm", memory) == 0.5


def test_search_memories_cli_prefix_match_beats_higher_semantic_match(monkeypatch):
    prefix_match = SimpleNamespace(id="prefix", type="cli_command", content="git status", hit_count=0)
    semantic_match = SimpleNamespace(id="semantic", type="cli_command", content="show git status", hit_count=0)
    db = FakeDB(query_result=[prefix_match, semantic_match])

    monkeypatch.setattr(retriever, "get_embedding", lambda query: [0.1])
    monkeypatch.setattr(
        retriever,
        "vector_client",
        SimpleNamespace(
            search_memories=lambda **kwargs: [
                {"id": "semantic", "similarity": 0.99, "metadata": {"count": 20}},
                {"id": "prefix", "similarity": 0.4, "metadata": {"count": 0}},
            ]
        ),
    )

    assert retriever.search_memories(db, "git", top_k=2, threshold=0.1) == [prefix_match, semantic_match]


def test_search_memories_cli_frequency_breaks_ties(monkeypatch):
    low_frequency = SimpleNamespace(id="low", type="cli_command", content="echo low frequency", hit_count=0)
    high_frequency = SimpleNamespace(id="high", type="cli_command", content="echo high frequency", hit_count=0)
    db = FakeDB(query_result=[low_frequency, high_frequency])

    monkeypatch.setattr(retriever, "get_embedding", lambda query: [0.1])
    monkeypatch.setattr(
        retriever,
        "vector_client",
        SimpleNamespace(
            search_memories=lambda **kwargs: [
                {"id": "low", "similarity": 0.5, "metadata": {"count": 1}},
                {"id": "high", "similarity": 0.5, "metadata": {"count": 8}},
            ]
        ),
    )

    assert retriever.search_memories(db, "echo", top_k=2, threshold=0.1) == [high_frequency, low_frequency]


def test_search_memories_cli_recency_breaks_ties(monkeypatch):
    old_command = SimpleNamespace(id="old", type="cli_command", content="npm test old", hit_count=0)
    recent_command = SimpleNamespace(id="recent", type="cli_command", content="npm test recent", hit_count=0)
    db = FakeDB(query_result=[old_command, recent_command])

    monkeypatch.setattr(retriever, "get_embedding", lambda query: [0.1])
    monkeypatch.setattr(
        retriever,
        "vector_client",
        SimpleNamespace(
            search_memories=lambda **kwargs: [
                {"id": "old", "similarity": 0.5, "metadata": {"count": 1, "last_used_at": "2000-01-01T00:00:00"}},
                {"id": "recent", "similarity": 0.5, "metadata": {"count": 1, "last_used_at": "2999-01-01T00:00:00"}},
            ]
        ),
    )

    assert retriever.search_memories(db, "npm", top_k=2, threshold=0.1) == [recent_command, old_command]


def test_vector_client_add_memory_delegates_to_collection():
    client = object.__new__(VectorClient)
    calls = []
    client.collection = SimpleNamespace(add=lambda **kwargs: calls.append(kwargs))

    client.add_memory("mem-1", "content", [0.1], {"type": "test"})

    assert calls == [
        {
            "ids": ["mem-1"],
            "embeddings": [[0.1]],
            "documents": ["content"],
            "metadatas": [{"type": "test"}],
        }
    ]


def test_vector_client_search_filters_by_similarity_threshold():
    client = object.__new__(VectorClient)
    client.collection = SimpleNamespace(
        query=lambda **kwargs: {
            "ids": [["keep", "drop"]],
            "distances": [[0.2, 0.5]],
            "metadatas": [[{"count": 2}, {"count": 10}]],
        }
    )

    assert client.search_memories([0.1], top_k=2, threshold=0.7) == [
        {"id": "keep", "similarity": 0.8, "metadata": {"count": 2}}
    ]


def test_vector_client_search_returns_empty_when_collection_has_no_ids():
    client = object.__new__(VectorClient)
    client.collection = SimpleNamespace(query=lambda **kwargs: {"ids": [[]], "distances": [[]]})

    assert client.search_memories([0.1]) == []


def test_vector_client_delete_memory_delegates_to_collection():
    client = object.__new__(VectorClient)
    calls = []
    client.collection = SimpleNamespace(delete=lambda **kwargs: calls.append(kwargs))

    client.delete_memory("mem-1")

    assert calls == [{"ids": ["mem-1"]}]


def test_get_embedding_returns_first_embedding(monkeypatch):
    created = []
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **kwargs: created.append(kwargs)
            or SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])
        )
    )
    monkeypatch.setattr(embedding, "client", fake_client)
    monkeypatch.setenv("EMBEDDING_MODEL", "test-model")

    assert embedding.get_embedding("hello") == [0.1, 0.2, 0.3]
    assert created == [{"input": "hello", "model": "test-model"}]


def test_init_relational_db_creates_tables(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(init_db, "init_database_schema", lambda: calls.append("init"))

    init_db.init_relational_db()

    assert calls == ["init"]
    assert "关系型数据库表创建完成" in capsys.readouterr().out


def test_init_vector_db_adds_and_removes_probe_memory(monkeypatch, capsys):
    calls = []
    fake_vector_client = SimpleNamespace(
        add_memory=lambda **kwargs: calls.append(("add", kwargs)),
        delete_memory=lambda memory_id: calls.append(("delete", memory_id)),
    )
    monkeypatch.setattr(init_db, "vector_client", fake_vector_client)

    init_db.init_vector_db()

    assert calls[0][0] == "add"
    assert calls[0][1]["memory_id"] == "test_init"
    assert calls[0][1]["embedding"] == [0.0] * 1536
    assert calls[1] == ("delete", "test_init")
    assert "向量数据库初始化完成" in capsys.readouterr().out
