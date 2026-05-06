"""深层测试：检索引擎边界情况"""
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

from core import retriever


class TestIsCliPrefixMatch:
    def test_matches_prefix(self):
        mem = SimpleNamespace(content="git status --short")
        assert retriever.is_cli_prefix_match("git", mem) is True

    def test_no_match(self):
        mem = SimpleNamespace(content="docker ps")
        assert retriever.is_cli_prefix_match("git", mem) is False

    def test_case_insensitive(self):
        mem = SimpleNamespace(content="Git Status")
        assert retriever.is_cli_prefix_match("git", mem) is True

    def test_empty_content(self):
        mem = SimpleNamespace(content="")
        assert retriever.is_cli_prefix_match("git", mem) is False

    def test_empty_query(self):
        mem = SimpleNamespace(content="git status")
        assert retriever.is_cli_prefix_match("", mem) is True

    def test_none_content(self):
        mem = SimpleNamespace(content=None)
        assert retriever.is_cli_prefix_match("git", mem) is False


class TestCalculateCliRelevanceScore:
    def test_base_score_only(self):
        mem = SimpleNamespace(
            content="docker ps",
            similarity_score=0.6,
            cli_metadata={},
        )
        # "git" does not prefix-match "docker ps", so no prefix bonus
        assert retriever.calculate_cli_relevance_score("git", mem) == 0.6

    def test_count_bonus_capped_at_0_3(self):
        mem = SimpleNamespace(
            content="docker ps",
            similarity_score=0.0,
            cli_metadata={"count": 100},
        )
        # "git" does not prefix-match "docker ps"
        score = retriever.calculate_cli_relevance_score("git", mem)
        # count_score = min(100 * 0.05, 0.3) = 0.3
        assert score == pytest.approx(0.3)

    def test_prefix_bonus(self):
        mem = SimpleNamespace(
            content="docker ps",
            similarity_score=0.0,
            cli_metadata={},
        )
        score = retriever.calculate_cli_relevance_score("docker", mem)
        assert score == pytest.approx(0.2)  # prefix bonus only

    def test_success_rate_bonus(self):
        mem = SimpleNamespace(
            content="docker deploy",
            similarity_score=0.0,
            cli_metadata={"success_count": 9, "failure_count": 1},
        )
        # "git" does not prefix-match "docker deploy"
        score = retriever.calculate_cli_relevance_score("git", mem)
        # success_score = (9/10) * 0.2 = 0.18
        assert score == pytest.approx(0.18)

    def test_all_bonuses_combined(self):
        mem = SimpleNamespace(
            content="git push",
            similarity_score=0.5,
            cli_metadata={
                "count": 10,
                "last_used_at": "2999-01-01T00:00:00",
                "success_count": 8,
                "failure_count": 2,
            },
        )
        score = retriever.calculate_cli_relevance_score("git", mem)
        # base=0.5, count=min(0.5,0.3)=0.3, recency~0.2, prefix=0.2, success=(8/10)*0.2=0.16
        # total ~ 1.36
        assert score > 1.0

    def test_handles_invalid_count_gracefully(self):
        mem = SimpleNamespace(
            content="docker ps",
            similarity_score=0.5,
            cli_metadata={"count": "abc"},
        )
        # "git" does not prefix-match "docker ps"
        score = retriever.calculate_cli_relevance_score("git", mem)
        assert score == pytest.approx(0.5)  # only base score

    def test_handles_invalid_last_used_at(self):
        mem = SimpleNamespace(
            content="docker ps",
            similarity_score=0.5,
            cli_metadata={"last_used_at": "not-a-date"},
        )
        score = retriever.calculate_cli_relevance_score("git", mem)
        assert score == pytest.approx(0.5)

    def test_handles_invalid_success_counts(self):
        mem = SimpleNamespace(
            content="docker ps",
            similarity_score=0.5,
            cli_metadata={"success_count": "abc", "failure_count": "xyz"},
        )
        score = retriever.calculate_cli_relevance_score("git", mem)
        assert score == pytest.approx(0.5)

    def test_zero_total_runs_no_success_bonus(self):
        mem = SimpleNamespace(
            content="docker ps",
            similarity_score=0.5,
            cli_metadata={"success_count": 0, "failure_count": 0},
        )
        score = retriever.calculate_cli_relevance_score("git", mem)
        assert score == pytest.approx(0.5)


class TestSearchSortKey:
    def test_non_cli_command_uses_similarity_only(self):
        mem = SimpleNamespace(type="user_preference", similarity_score=0.8)
        key = retriever._search_sort_key("test", mem)
        assert key == (0, 0.8)

    def test_cli_command_with_prefix_match_gets_higher_key(self):
        mem = SimpleNamespace(
            type="cli_command",
            content="git status",
            similarity_score=0.3,
            cli_metadata={},
        )
        key = retriever._search_sort_key("git", mem)
        assert key[0] == 1  # prefix match flag

    def test_cli_command_without_prefix_match(self):
        mem = SimpleNamespace(
            type="cli_command",
            content="docker ps",
            similarity_score=0.3,
            cli_metadata={},
        )
        key = retriever._search_sort_key("git", mem)
        assert key[0] == 0

    def test_none_similarity_score_defaults_to_zero(self):
        mem = SimpleNamespace(type="user_preference", similarity_score=None)
        key = retriever._search_sort_key("test", mem)
        assert key == (0, 0.0)


class TestGetMemoryMetadata:
    def test_returns_cli_metadata_when_available(self):
        mem = SimpleNamespace(cli_metadata={"count": 5})
        assert retriever._get_memory_metadata(mem) == {"count": 5}

    def test_falls_back_to_metadata(self):
        mem = SimpleNamespace(cli_metadata=None, metadata={"count": 3})
        assert retriever._get_memory_metadata(mem) == {"count": 3}

    def test_returns_empty_dict_when_neither_available(self):
        mem = SimpleNamespace(cli_metadata=None, metadata=None)
        assert retriever._get_memory_metadata(mem) == {}

    def test_returns_empty_dict_for_missing_attrs(self):
        mem = SimpleNamespace()
        assert retriever._get_memory_metadata(mem) == {}
