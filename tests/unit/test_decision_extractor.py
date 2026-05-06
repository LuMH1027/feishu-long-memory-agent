"""深层测试：LLM决策抽取模块"""
import json
import sys
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

# Mock openai before importing
sys.modules.setdefault(
    "openai",
    types.SimpleNamespace(
        OpenAI=lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: None)
            )
        )
    ),
)

from core.decision_extractor import (
    _normalize_result,
    extract_decision_with_llm,
    extract_decision_with_rules_fallback,
    batch_extract_decisions,
    extract_deadline,
    DECISION_EXTRACTION_PROMPT,
)


class TestNormalizeResult:
    """_normalize_result 规范化测试"""

    def test_normalizes_complete_result(self):
        raw = {
            "is_decision": True,
            "topic": "部署环境选择",
            "conclusion": "统一用prod",
            "reason": "staging不稳定",
            "project": "project-a",
            "preferred_terms": ["prod"],
            "rejected_terms": ["staging"],
            "deadline": "2026-05-10",
            "confidence": 0.95,
        }
        result = _normalize_result(raw)
        assert result["is_decision"] is True
        assert result["topic"] == "部署环境选择"
        assert result["confidence"] == 0.95

    def test_fills_missing_fields_with_defaults(self):
        result = _normalize_result({})
        assert result["is_decision"] is False
        assert result["topic"] is None
        assert result["conclusion"] is None
        assert result["preferred_terms"] == []
        assert result["rejected_terms"] == []
        assert result["confidence"] == 0.5

    def test_converts_non_list_terms_to_empty_list(self):
        raw = {"preferred_terms": "prod", "rejected_terms": "staging"}
        result = _normalize_result(raw)
        assert result["preferred_terms"] == []
        assert result["rejected_terms"] == []

    def test_filters_empty_strings_from_terms(self):
        raw = {"preferred_terms": ["prod", "", None], "rejected_terms": ["", "staging"]}
        result = _normalize_result(raw)
        assert result["preferred_terms"] == ["prod"]
        assert result["rejected_terms"] == ["staging"]

    def test_handles_boolean_coercion(self):
        raw = {"is_decision": 1, "confidence": "0.8"}
        result = _normalize_result(raw)
        assert result["is_decision"] is True
        assert result["confidence"] == 0.8

    def test_handles_nested_list_in_terms(self):
        raw = {"preferred_terms": [["prod"], ["dev"]], "rejected_terms": []}
        result = _normalize_result(raw)
        # nested lists are truthy, so they pass the filter
        assert len(result["preferred_terms"]) == 2


class TestExtractDecisionWithLLM:
    """extract_decision_with_llm LLM调用测试"""

    def test_normalize_result_with_valid_data(self):
        """Test _normalize_result directly with valid LLM-like output"""
        raw = {
            "is_decision": True,
            "topic": "代码审查流程",
            "conclusion": "使用GitLab MR",
            "reason": "更规范",
            "project": None,
            "preferred_terms": ["GitLab MR"],
            "rejected_terms": ["直接push"],
            "deadline": None,
            "confidence": 0.9,
        }
        result = _normalize_result(raw)
        assert result["is_decision"] is True
        assert result["topic"] == "代码审查流程"
        assert result["preferred_terms"] == ["GitLab MR"]
        assert result["rejected_terms"] == ["直接push"]
        assert result["confidence"] == 0.9

    def test_returns_error_on_invalid_json(self, monkeypatch):
        import core.decision_extractor as de_mod

        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: fake_response)
            )
        )
        monkeypatch.setattr(de_mod, "_get_openai_client", lambda: fake_client)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        result = extract_decision_with_llm("test message")
        assert result["is_decision"] is False
        assert "error" in result

    def test_returns_error_on_api_failure(self, monkeypatch):
        import core.decision_extractor as de_mod

        def raise_error(**kw):
            raise RuntimeError("API timeout")

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=raise_error)
            )
        )
        monkeypatch.setattr(de_mod, "_get_openai_client", lambda: fake_client)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        result = extract_decision_with_llm("test")
        assert result["is_decision"] is False
        assert "LLM" in result["error"]


class TestExtractDecisionWithRulesFallback:
    """规则降级抽取测试"""

    def test_falls_back_to_rules_when_llm_fails(self, monkeypatch):
        monkeypatch.setattr(
            "core.decision_extractor.extract_decision_with_llm",
            lambda msg: (_ for _ in ()).throw(RuntimeError("LLM down")),
        )

        result = extract_decision_with_rules_fallback(
            "以后统一用prod部署，不再使用staging", use_llm=True
        )
        assert result["is_decision"] is True
        assert "prod" in result["preferred_terms"]
        assert result["confidence"] == 0.7

    def test_uses_rules_directly_when_llm_disabled(self):
        result = extract_decision_with_rules_fallback(
            "以后统一用prod部署", use_llm=False
        )
        assert result["is_decision"] is True
        assert result["confidence"] == 0.7

    def test_returns_not_decision_for_non_decision_message(self):
        result = extract_decision_with_rules_fallback(
            "今天天气不错", use_llm=False
        )
        assert result["is_decision"] is False


class TestBatchExtractDecisions:
    """批量抽取测试"""

    def test_batch_extracts_multiple_messages(self):
        messages = [
            "以后统一用prod部署",
            "今天天气不错",
        ]
        results = batch_extract_decisions(messages, use_llm=False)
        assert len(results) == 2
        assert results[0]["is_decision"] is True
        assert results[1]["is_decision"] is False

    def test_batch_handles_empty_list(self):
        assert batch_extract_decisions([], use_llm=False) == []


class TestExtractDeadline:
    """截止日期抽取测试"""

    def test_extracts_iso_date(self):
        assert extract_deadline("截止日期2026-05-10") == "2026-05-10"

    def test_extracts_slash_date(self):
        assert extract_deadline("截止2026/05/10完成") == "2026-05-10"

    def test_extracts_chinese_date(self):
        year = datetime.now().year
        result = extract_deadline("5月10日前完成")
        assert result == f"{year}-05-10"

    def test_extracts_relative_date_tomorrow(self):
        expected = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert extract_deadline("明天截止") == expected

    def test_extracts_relative_date_day_after_tomorrow(self):
        expected = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        assert extract_deadline("后天完成") == expected

    def test_extracts_relative_date_days_later(self):
        expected = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        assert extract_deadline("3天后截止") == expected

    def test_extracts_next_week_day(self):
        today = datetime.now()
        # 下周三
        days_ahead = 2 - today.weekday() + 7  # Wednesday is weekday 2
        expected = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        assert extract_deadline("下周三截止") == expected

    def test_extracts_deadline_keyword_with_date(self):
        assert extract_deadline("截止日期: 2026-06-15") == "2026-06-15"

    def test_extracts_deadline_english(self):
        assert extract_deadline("Deadline: 2026-07-01") == "2026-07-01"

    def test_returns_none_for_no_date(self):
        assert extract_deadline("今天天气不错") is None

    def test_rejects_invalid_year_range(self):
        assert extract_deadline("1999-01-01") is None

    def test_rejects_invalid_month(self):
        assert extract_deadline("2026-13-01") is None
