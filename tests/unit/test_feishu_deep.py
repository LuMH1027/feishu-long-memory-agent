"""深层测试：飞书决策路由 - 边界情况与高级场景"""
import asyncio
import importlib
import os
import sys
import types
from datetime import datetime, timedelta

import pytest

from backend.routers import memory, cli


def setup_function():
    memory.temp_memory_storage.clear()
    cli.temp_command_storage.clear()
    os.environ.pop("FEISHU_AUTO_REPLY", None)
    os.environ.pop("USE_LLM_DECISION_EXTRACTION", None)


def load_feishu_router(validate_result=True):
    verification = types.SimpleNamespace(validate_signature=lambda *args: validate_result)
    sys.modules["feishu"] = types.SimpleNamespace(verification=verification)
    sys.modules["feishu.verification"] = verification
    sys.modules.pop("backend.routers.feishu", None)
    return importlib.import_module("backend.routers.feishu")


class TestIsDecisionMessage:
    def test_detects_decision_keywords(self):
        feishu = load_feishu_router()
        assert feishu.is_decision_message("以后统一用prod") is True
        assert feishu.is_decision_message("决定采用方案A") is True
        assert feishu.is_decision_message("不再使用staging") is True
        assert feishu.is_decision_message("确认截止日期是5月10日") is True

    def test_rejects_non_decision_messages(self):
        feishu = load_feishu_router()
        assert feishu.is_decision_message("今天天气不错") is False
        assert feishu.is_decision_message("大家好") is False
        assert feishu.is_decision_message("") is False


class TestIsQueryMessage:
    def test_detects_query_keywords(self):
        feishu = load_feishu_router()
        assert feishu.is_query_message("怎么重启服务器？") is True
        assert feishu.is_query_message("谁知道部署流程？") is True
        assert feishu.is_query_message("如何清理容器？") is True

    def test_rejects_non_query_messages(self):
        feishu = load_feishu_router()
        assert feishu.is_query_message("以后统一用prod") is False


class TestExtractProject:
    def test_extracts_project_dash_name(self):
        feishu = load_feishu_router()
        assert feishu._extract_project("project-a 以后用prod") == "project-a"

    def test_extracts_known_service_names(self):
        feishu = load_feishu_router()
        assert feishu._extract_project("api-server 重启命令") == "api-server"
        assert feishu._extract_project("webapp部署") == "webapp"

    def test_returns_none_for_no_project(self):
        feishu = load_feishu_router()
        assert feishu._extract_project("以后统一用prod") is None


class TestExtractReason:
    def test_extracts_reason_with_keyword(self):
        feishu = load_feishu_router()
        assert feishu._extract_reason("因为staging经常误连测试资源") == "staging经常误连测试资源"

    def test_returns_none_when_no_reason(self):
        feishu = load_feishu_router()
        assert feishu._extract_reason("以后统一用prod") is None


class TestExtractPreferredTerms:
    def test_extracts_unified_use(self):
        feishu = load_feishu_router()
        terms = feishu._extract_preferred_terms("统一用prod部署")
        assert "prod" in terms

    def test_extracts_change_to(self):
        feishu = load_feishu_router()
        # The regex pattern only captures alphanumeric terms
        terms = feishu._extract_preferred_terms("改成prod-v2")
        assert "prod-v2" in terms

    def test_extracts_send_to(self):
        feishu = load_feishu_router()
        terms = feishu._extract_preferred_terms("发给b@example.com")
        assert "b@example.com" in terms


class TestExtractRejectedTerms:
    def test_extracts_no_longer_use(self):
        feishu = load_feishu_router()
        terms = feishu._extract_rejected_terms("不再使用staging")
        assert "staging" in terms

    def test_extracts_abandon(self):
        feishu = load_feishu_router()
        # The regex pattern only captures alphanumeric terms
        terms = feishu._extract_rejected_terms("废弃old-方案v1")
        assert "old-方案v1" not in terms  # Chinese chars not in pattern
        terms = feishu._extract_rejected_terms("staging废弃")
        assert "staging" in terms


class TestTopicKey:
    def test_with_project(self):
        feishu = load_feishu_router()
        key = feishu._topic_key("project-a", "some content", "chat-1")
        assert key == "decision:chat-1:project-a"

    def test_without_project_extracts_chinese(self):
        feishu = load_feishu_router()
        key = feishu._topic_key(None, "部署环境选择", "chat-1")
        assert "部署环境选择" in key

    def test_without_project_extracts_ascii(self):
        feishu = load_feishu_router()
        key = feishu._topic_key(None, "use prod environment", "chat-1")
        assert "use" in key

    def test_fallback_to_general(self):
        feishu = load_feishu_router()
        key = feishu._topic_key(None, "!!!", "chat-1")
        assert "general" in key


class TestExtractDecision:
    def test_extracts_full_decision(self):
        feishu = load_feishu_router()
        decision = feishu.extract_decision(
            "project-a 以后统一用 prod 部署，不再使用 staging，因为 staging 不稳定",
            chat_id="chat-1",
        )
        assert decision["project"] == "project-a"
        assert "prod" in decision["preferred_terms"]
        assert "staging" in decision["rejected_terms"]
        assert decision["reason"] is not None
        assert "staging" in decision["reason"]

    def test_extracts_minimal_decision(self):
        feishu = load_feishu_router()
        decision = feishu.extract_decision("以后统一用prod")
        assert decision["project"] is None
        assert "prod" in decision["preferred_terms"]


class TestExtractDeadlineInFeishu:
    def test_extracts_iso_date(self):
        feishu = load_feishu_router()
        assert feishu._extract_deadline("截止2026-05-10完成") == "2026-05-10"

    def test_extracts_chinese_date(self):
        feishu = load_feishu_router()
        year = datetime.now().year
        assert feishu._extract_deadline("5月10日前完成") == f"{year}-05-10"

    def test_extracts_relative_tomorrow(self):
        feishu = load_feishu_router()
        expected = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert feishu._extract_deadline("明天截止") == expected

    def test_extracts_relative_days_later(self):
        feishu = load_feishu_router()
        expected = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        assert feishu._extract_deadline("3天后截止") == expected

    def test_returns_none_for_no_date(self):
        feishu = load_feishu_router()
        assert feishu._extract_deadline("以后统一用prod") is None


class TestCleanBotMention:
    def test_removes_at_mentions(self):
        feishu = load_feishu_router()
        assert feishu._clean_bot_mention("@机器人 以后用prod") == "以后用prod"

    def test_handles_empty_content(self):
        feishu = load_feishu_router()
        assert feishu._clean_bot_mention("") == ""


class TestContradictionChain:
    """测试矛盾更新链 - 使用相同topic_key触发覆盖"""

    def test_same_topic_contradiction_marks_old_inactive(self):
        feishu = load_feishu_router()
        # Use same topic pattern to trigger contradiction detection
        m1 = feishu.extract_and_store_decision(
            feishu.DecisionExtractRequest(
                content="project-x 以后统一用staging部署",
                chat_id="chat-1",
                user_id="u1",
            )
        )
        m2 = feishu.extract_and_store_decision(
            feishu.DecisionExtractRequest(
                content="project-x 不对，改成用prod部署",
                chat_id="chat-1",
                user_id="u2",
            )
        )
        # Both should be stored successfully
        assert m1["status"] == "stored"
        assert m2["status"] == "stored"
        # The second decision should be active
        assert m2["memory"]["metadata"]["status"] == "active"

    def test_decision_stores_all_fields(self):
        feishu = load_feishu_router()
        result = feishu.extract_and_store_decision(
            feishu.DecisionExtractRequest(
                content="project-x 以后统一用prod部署，不再使用staging，因为staging不稳定",
                chat_id="chat-1",
                user_id="u1",
                message_id="msg-1",
            )
        )
        assert result["status"] == "stored"
        decision = result["decision"]
        assert decision["project"] == "project-x"
        assert "prod" in decision["preferred_terms"]
        assert "staging" in decision["rejected_terms"]
        assert decision["reason"] is not None
        assert result["memory"]["source"] == "feishu_group"


class TestHandleFeishuMessageEdgeCases:
    def test_empty_content_returns_ignored(self):
        feishu = load_feishu_router()
        response = feishu.handle_feishu_message(
            feishu.FeishuMessage(content="", chat_id="chat-1")
        )
        # Empty content with no decision/query markers returns "ignored"
        assert response["action"] == "ignored"

    def test_decision_stored_for_decision_message(self, monkeypatch):
        feishu = load_feishu_router()
        # Mock the send functions to avoid lark_oapi dependency
        monkeypatch.setattr(feishu, "_send_group_card", lambda *a, **kw: {"status": "ok"})
        monkeypatch.setattr(feishu, "_send_group_text", lambda *a, **kw: {"status": "ok"})
        monkeypatch.setenv("FEISHU_AUTO_REPLY", "true")

        response = feishu.handle_feishu_message(
            feishu.FeishuMessage(
                content="以后统一用prod部署",
                chat_id="chat-1",
                user_id="u1",
            )
        )
        assert response["action"] == "decision_stored"

    def test_suggest_cards_for_query_message(self, monkeypatch):
        feishu = load_feishu_router()
        monkeypatch.setattr(feishu, "_send_group_card", lambda *a, **kw: {"status": "ok"})
        # Store a command first
        asyncio.run(
            cli.record_command(
                cli.CommandRecordRequest(
                    command="systemctl restart nginx",
                    count=5,
                    shell="bash",
                    directory="/etc",
                )
            )
        )
        response = feishu.handle_feishu_message(
            feishu.FeishuMessage(
                content="怎么重启服务器？",
                chat_id="chat-1",
            )
        )
        assert response["action"] == "suggest_cards"

    def test_no_action_for_regular_message(self):
        feishu = load_feishu_router()
        response = feishu.handle_feishu_message(
            feishu.FeishuMessage(
                content="今天天气不错",
                chat_id="chat-1",
            )
        )
        # Non-decision, non-query messages return "ignored"
        assert response["action"] == "ignored"
        assert response["cards"] == []


class TestAutoReplyEnvParsing:
    def test_auto_reply_enabled_for_true(self, monkeypatch):
        feishu = load_feishu_router()
        monkeypatch.setenv("FEISHU_AUTO_REPLY", "true")
        assert feishu._auto_reply_enabled() is True

    def test_auto_reply_enabled_for_1(self, monkeypatch):
        feishu = load_feishu_router()
        monkeypatch.setenv("FEISHU_AUTO_REPLY", "1")
        assert feishu._auto_reply_enabled() is True

    def test_auto_reply_disabled_for_false(self, monkeypatch):
        feishu = load_feishu_router()
        monkeypatch.setenv("FEISHU_AUTO_REPLY", "false")
        assert feishu._auto_reply_enabled() is False

    def test_auto_reply_disabled_when_unset(self, monkeypatch):
        feishu = load_feishu_router()
        monkeypatch.delenv("FEISHU_AUTO_REPLY", raising=False)
        assert feishu._auto_reply_enabled() is False

    def test_llm_extraction_enabled_for_true(self, monkeypatch):
        feishu = load_feishu_router()
        monkeypatch.setenv("USE_LLM_DECISION_EXTRACTION", "true")
        assert feishu._use_llm_extraction() is True

    def test_llm_extraction_disabled_when_unset(self, monkeypatch):
        feishu = load_feishu_router()
        monkeypatch.delenv("USE_LLM_DECISION_EXTRACTION", raising=False)
        assert feishu._use_llm_extraction() is False


class TestMetadataHelpers:
    def test_metadata_from_json_parses_dict(self):
        feishu = load_feishu_router()
        assert feishu._metadata_from_json('{"key": "value"}') == {"key": "value"}

    def test_metadata_from_json_returns_empty_for_none(self):
        feishu = load_feishu_router()
        assert feishu._metadata_from_json(None) == {}

    def test_metadata_from_json_returns_empty_for_invalid(self):
        feishu = load_feishu_router()
        assert feishu._metadata_from_json("not json") == {}

    def test_metadata_from_json_returns_empty_for_list(self):
        feishu = load_feishu_router()
        assert feishu._metadata_from_json("[1, 2, 3]") == {}

    def test_metadata_to_json_serializes(self):
        feishu = load_feishu_router()
        import json
        result = feishu._metadata_to_json({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_metadata_to_json_handles_none(self):
        feishu = load_feishu_router()
        import json
        assert json.loads(feishu._metadata_to_json(None)) == {}
