"""飞书交互卡片模板模块"""
import json
from typing import Any, Optional


def _text_element(content: str, bold: bool = False) -> dict[str, Any]:
    """创建文本元素"""
    return {
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**{content}**" if bold else content
        }
    }


def _divider() -> dict[str, Any]:
    """创建分割线"""
    return {"tag": "hr"}


def _button(text: str, value: dict[str, Any], button_type: str = "primary") -> dict[str, Any]:
    """创建按钮"""
    return {
        "tag": "button",
        "text": {
            "tag": "plain_text",
            "content": text
        },
        "type": button_type,
        "value": value
    }


def _column_set(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """创建多列布局"""
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "columns": columns
    }


def _column(elements: list[dict[str, Any]], width: str = "weighted", weight: int = 1) -> dict[str, Any]:
    """创建列"""
    return {
        "tag": "column",
        "width": width,
        "weight": weight,
        "vertical_align": "top",
        "elements": elements
    }


def decision_card(
    topic: str,
    conclusion: str,
    reason: Optional[str] = None,
    project: Optional[str] = None,
    preferred_terms: Optional[list[str]] = None,
    rejected_terms: Optional[list[str]] = None,
    created_at: Optional[str] = None,
    memory_id: Optional[str] = None
) -> dict[str, Any]:
    """
    创建决策卡片

    Args:
        topic: 决策主题
        conclusion: 决策结论
        reason: 决策原因
        project: 相关项目
        preferred_terms: 推荐的术语/方案
        rejected_terms: 废弃的术语/方案
        created_at: 记录时间
        memory_id: 记忆ID

    Returns:
        飞书交互卡片JSON
    """
    elements = []

    # 标题区域
    elements.append(_text_element(f"📋 决策主题：{topic}", bold=True))

    if project:
        elements.append(_text_element(f"🎯 相关项目：{project}"))

    elements.append(_divider())

    # 结论区域
    elements.append(_text_element("📝 决策结论：", bold=True))
    elements.append(_text_element(conclusion))

    # 原因区域
    if reason:
        elements.append(_divider())
        elements.append(_text_element("💡 决策原因：", bold=True))
        elements.append(_text_element(reason))

    # 推荐和废弃方案
    if preferred_terms or rejected_terms:
        elements.append(_divider())

        if preferred_terms:
            terms_str = "、".join(preferred_terms)
            elements.append(_text_element(f"✅ 推荐方案：{terms_str}"))

        if rejected_terms:
            terms_str = "、".join(rejected_terms)
            elements.append(_text_element(f"❌ 废弃方案：{terms_str}"))

    # 时间信息
    if created_at:
        elements.append(_divider())
        elements.append(_text_element(f"⏰ 记录时间：{created_at}"))

    # 操作按钮
    elements.append(_divider())
    buttons = []

    if memory_id:
        buttons.append(_button("查看详情", {"action": "view_detail", "memory_id": memory_id}, "default"))

    buttons.append(_button("确认采纳", {"action": "confirm_decision", "topic": topic}, "primary"))

    if buttons:
        elements.append({
            "tag": "action",
            "actions": buttons
        })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📋 团队决策：{topic}"
            },
            "template": "blue"
        },
        "elements": elements
    }


def cli_command_card(
    command: str,
    description: Optional[str] = None,
    usage_count: int = 0,
    success_count: int = 0,
    directory: Optional[str] = None,
    created_at: Optional[str] = None,
    memory_id: Optional[str] = None
) -> dict[str, Any]:
    """
    创建CLI命令卡片

    Args:
        command: 命令内容
        description: 命令描述
        usage_count: 使用次数
        success_count: 成功次数
        directory: 关联目录
        created_at: 记录时间
        memory_id: 记忆ID

    Returns:
        飞书交互卡片JSON
    """
    elements = []

    # 命令内容
    elements.append(_text_element("💻 命令：", bold=True))
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"```\n{command}\n```"
        }
    })

    # 描述
    if description:
        elements.append(_text_element(f"📝 描述：{description}"))

    elements.append(_divider())

    # 统计信息
    stats_elements = []

    if usage_count > 0:
        stats_elements.append(_text_element(f"📊 使用次数：{usage_count}"))

    if success_count > 0 and usage_count > 0:
        success_rate = (success_count / usage_count) * 100
        stats_elements.append(_text_element(f"✅ 成功率：{success_rate:.1f}%"))

    if directory:
        stats_elements.append(_text_element(f"📁 关联目录：{directory}"))

    if stats_elements:
        elements.extend(stats_elements)
        elements.append(_divider())

    # 时间信息
    if created_at:
        elements.append(_text_element(f"⏰ 记录时间：{created_at}"))

    # 操作按钮
    elements.append(_divider())
    buttons = [
        _button("复制命令", {"action": "copy_command", "command": command}, "default"),
        _button("执行命令", {"action": "execute_command", "command": command}, "primary"),
    ]

    if memory_id:
        buttons.append(_button("查看详情", {"action": "view_detail", "memory_id": memory_id}, "default"))

    elements.append({
        "tag": "action",
        "actions": buttons
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "💻 CLI命令推荐"
            },
            "template": "green"
        },
        "elements": elements
    }


def workflow_card(
    name: str,
    steps: list[str],
    description: Optional[str] = None,
    created_at: Optional[str] = None,
    memory_id: Optional[str] = None
) -> dict[str, Any]:
    """
    创建工作流卡片

    Args:
        name: 工作流名称
        steps: 工作流步骤列表
        description: 工作流描述
        created_at: 记录时间
        memory_id: 记忆ID

    Returns:
        飞书交互卡片JSON
    """
    elements = []

    # 工作流名称
    elements.append(_text_element(f"🔄 工作流：{name}", bold=True))

    if description:
        elements.append(_text_element(f"📝 描述：{description}"))

    elements.append(_divider())

    # 步骤列表
    elements.append(_text_element("📋 执行步骤：", bold=True))

    for i, step in enumerate(steps, 1):
        elements.append(_text_element(f"{i}. {step}"))

    elements.append(_divider())

    # 时间信息
    if created_at:
        elements.append(_text_element(f"⏰ 记录时间：{created_at}"))

    # 操作按钮
    elements.append(_divider())
    buttons = [
        _button("执行工作流", {"action": "execute_workflow", "name": name}, "primary"),
    ]

    if memory_id:
        buttons.append(_button("查看详情", {"action": "view_detail", "memory_id": memory_id}, "default"))

    elements.append({
        "tag": "action",
        "actions": buttons
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🔄 工作流：{name}"
            },
            "template": "purple"
        },
        "elements": elements
    }


def memory_to_card(item: dict[str, Any]) -> dict[str, Any]:
    """
    将记忆数据转换为飞书交互卡片

    Args:
        item: 记忆数据字典

    Returns:
        飞书交互卡片JSON
    """
    metadata = item.get("metadata") or {}
    memory_id = item.get("id")
    created_at = item.get("created_at")

    # CLI工作流
    if item.get("type") == "cli_workflow":
        return workflow_card(
            name=metadata.get("name") or item.get("description") or "未命名工作流",
            steps=metadata.get("steps", []),
            description=item.get("description"),
            created_at=created_at,
            memory_id=memory_id
        )

    # CLI命令
    if item.get("type") == "cli_command":
        return cli_command_card(
            command=item.get("content", ""),
            description=item.get("description"),
            usage_count=metadata.get("count", 0),
            success_count=metadata.get("success_count", 0),
            directory=metadata.get("directory"),
            created_at=created_at,
            memory_id=memory_id
        )

    # 项目决策
    return decision_card(
        topic=metadata.get("topic") or item.get("type") or "未知主题",
        conclusion=metadata.get("conclusion") or item.get("content", ""),
        reason=metadata.get("reason"),
        project=metadata.get("project"),
        preferred_terms=metadata.get("preferred_terms", []),
        rejected_terms=metadata.get("rejected_terms", []),
        created_at=created_at,
        memory_id=memory_id
    )


def cards_to_text(cards: list[dict[str, Any]]) -> str:
    """
    将卡片列表转换为纯文本（降级方案）

    Args:
        cards: 卡片列表

    Returns:
        格式化的文本
    """
    if not cards:
        return "没有找到相关记忆。"

    lines = ["找到以下相关记忆："]

    for i, card in enumerate(cards, 1):
        header = card.get("header", {})
        title = header.get("title", {}).get("content", "未知")
        lines.append(f"\n{i}. {title}")

        # 提取关键信息
        for element in card.get("elements", []):
            if element.get("tag") == "div":
                text = element.get("text", {}).get("content", "")
                if text and not text.startswith("**"):
                    lines.append(f"   {text}")

    return "\n".join(lines)
