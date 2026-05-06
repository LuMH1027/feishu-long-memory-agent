"""深层测试：飞书交互卡片模板模块"""
import pytest

from feishu_bot.card_templates import (
    decision_card,
    cli_command_card,
    workflow_card,
    memory_to_card,
    cards_to_text,
    _text_element,
    _divider,
    _button,
)


class TestTextElement:
    def test_creates_plain_text(self):
        elem = _text_element("hello")
        assert elem["tag"] == "div"
        assert elem["text"]["tag"] == "lark_md"
        assert elem["text"]["content"] == "hello"

    def test_creates_bold_text(self):
        elem = _text_element("hello", bold=True)
        assert "**hello**" in elem["text"]["content"]


class TestButton:
    def test_creates_primary_button(self):
        btn = _button("确认", {"action": "confirm"})
        assert btn["tag"] == "button"
        assert btn["type"] == "primary"
        assert btn["text"]["content"] == "确认"

    def test_creates_default_button(self):
        btn = _button("取消", {"action": "cancel"}, "default")
        assert btn["type"] == "default"


class TestDecisionCard:
    def test_creates_minimal_decision_card(self):
        card = decision_card(topic="部署", conclusion="用prod")
        assert "header" in card
        assert "团队决策：部署" in card["header"]["title"]["content"]
        assert card["header"]["template"] == "blue"
        assert any("用prod" in str(e) for e in card["elements"])

    def test_creates_full_decision_card(self):
        card = decision_card(
            topic="部署环境",
            conclusion="用prod",
            reason="staging不稳定",
            project="project-a",
            preferred_terms=["prod"],
            rejected_terms=["staging"],
            created_at="2026-05-01",
            memory_id="mem-1",
        )
        elements_str = str(card["elements"])
        assert "project-a" in elements_str
        assert "staging不稳定" in elements_str
        assert "prod" in elements_str
        assert "staging" in elements_str
        assert "2026-05-01" in elements_str

    def test_decision_card_has_action_buttons(self):
        card = decision_card(topic="t", conclusion="c", memory_id="m-1")
        action_elements = [e for e in card["elements"] if e.get("tag") == "action"]
        assert len(action_elements) == 1
        buttons = action_elements[0]["actions"]
        assert len(buttons) == 2  # 查看详情 + 确认采纳

    def test_decision_card_without_memory_id_has_one_button(self):
        card = decision_card(topic="t", conclusion="c")
        action_elements = [e for e in card["elements"] if e.get("tag") == "action"]
        buttons = action_elements[0]["actions"]
        assert len(buttons) == 1  # only 确认采纳


class TestCliCommandCard:
    def test_creates_command_card(self):
        card = cli_command_card(command="docker ps -a")
        assert "header" in card
        assert card["header"]["template"] == "green"
        assert "docker ps -a" in str(card["elements"])

    def test_includes_stats(self):
        card = cli_command_card(
            command="git status",
            description="查看状态",
            usage_count=10,
            success_count=8,
            directory="/workspace",
        )
        elements_str = str(card["elements"])
        assert "10" in elements_str
        assert "80.0%" in elements_str
        assert "/workspace" in elements_str

    def test_has_copy_and_execute_buttons(self):
        card = cli_command_card(command="ls")
        action_elements = [e for e in card["elements"] if e.get("tag") == "action"]
        buttons = action_elements[0]["actions"]
        actions = [b["value"]["action"] for b in buttons]
        assert "copy_command" in actions
        assert "execute_command" in actions


class TestWorkflowCard:
    def test_creates_workflow_card(self):
        card = workflow_card(name="部署", steps=["git pull", "docker build"])
        assert "header" in card
        assert card["header"]["template"] == "purple"
        elements_str = str(card["elements"])
        assert "git pull" in elements_str
        assert "docker build" in elements_str

    def test_workflow_has_execute_button(self):
        card = workflow_card(name="test", steps=["step1"])
        action_elements = [e for e in card["elements"] if e.get("tag") == "action"]
        buttons = action_elements[0]["actions"]
        assert buttons[0]["value"]["action"] == "execute_workflow"


class TestMemoryToCard:
    def test_converts_cli_workflow_to_workflow_card(self):
        item = {
            "type": "cli_workflow",
            "content": '{"name": "deploy", "steps": ["step1"]}',
            "metadata": {"name": "deploy", "steps": ["step1"]},
        }
        card = memory_to_card(item)
        assert card["header"]["template"] == "purple"

    def test_converts_cli_command_to_command_card(self):
        item = {
            "type": "cli_command",
            "content": "docker ps",
            "metadata": {"count": 5, "success_count": 4},
        }
        card = memory_to_card(item)
        assert card["header"]["template"] == "green"

    def test_converts_project_decision_to_decision_card(self):
        item = {
            "type": "project_decision",
            "content": "用prod",
            "metadata": {
                "topic": "部署",
                "conclusion": "用prod",
                "preferred_terms": ["prod"],
            },
        }
        card = memory_to_card(item)
        assert card["header"]["template"] == "blue"

    def test_defaults_to_decision_card_for_unknown_type(self):
        item = {"type": "unknown", "content": "something", "metadata": {}}
        card = memory_to_card(item)
        assert card["header"]["template"] == "blue"


class TestCardsToText:
    def test_returns_empty_message_for_no_cards(self):
        assert "没有找到" in cards_to_text([])

    def test_formats_single_card(self):
        card = decision_card(topic="部署", conclusion="用prod")
        text = cards_to_text([card])
        assert "团队决策：部署" in text

    def test_formats_multiple_cards(self):
        cards = [
            decision_card(topic="部署", conclusion="用prod"),
            cli_command_card(command="docker ps"),
        ]
        text = cards_to_text(cards)
        assert "1." in text
        assert "2." in text
