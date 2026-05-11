"""飞书 SDK Mock 模式 —— lark-oapi 未安装或凭证未配置时自动切换"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Optional

logger = logging.getLogger("feishu.mock")

_MOCK_PREFIX = "[飞书Mock]"


_printed_mode = False


def _print_mode(mock: bool):
    global _printed_mode
    if _printed_mode:
        return
    _printed_mode = True
    if mock:
        print(f"\n{_MOCK_PREFIX} 已激活 Mock 模式")
        print(f"{_MOCK_PREFIX}   原因: lark-oapi 未安装 或 FEISHU_APP_ID 未配置 或 FEISHU_MOCK_MODE=true")
        print(f"{_MOCK_PREFIX}   飞书消息仅打印到终端，不会发送到真实群聊\n")


def should_use_mock() -> bool:
    """检测是否应使用 Mock 模式"""
    # 显式开关
    force_mock = os.getenv("FEISHU_MOCK_MODE", "").lower() in {"1", "true", "yes", "on"}
    if force_mock:
        _print_mode(True)
        return True

    # lark-oapi 未安装
    try:
        import lark_oapi  # noqa: F401
    except ModuleNotFoundError:
        logger.info("lark-oapi 未安装，启用飞书 Mock 模式")
        _print_mode(True)
        return True

    # 凭证未配置
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if not app_id or not app_secret or app_id.startswith("your_") or app_secret.startswith("your_"):
        logger.info("飞书凭证未配置，启用飞书 Mock 模式")
        _print_mode(True)
        return True

    _print_mode(False)
    return False


def mock_send_text_message(chat_id: str, text: str) -> dict[str, Any]:
    msg_id = f"mock_msg_{uuid.uuid4().hex[:12]}"
    print(f"\n{_MOCK_PREFIX} 发送文本消息 → chat_id={chat_id}")
    print(f"{_MOCK_PREFIX}   内容: {text[:120]}{'...' if len(text) > 120 else ''}")
    return {"status": "ok", "provider": "mock", "message_id": msg_id}


def mock_send_card_message(chat_id: str, card: dict[str, Any]) -> dict[str, Any]:
    msg_id = f"mock_card_{uuid.uuid4().hex[:12]}"
    header = card.get("header", {})
    title = header.get("title", {}).get("content", "未知卡片")
    elements = card.get("elements", [])
    print(f"\n{_MOCK_PREFIX} 发送卡片消息 → chat_id={chat_id}")
    print(f"{_MOCK_PREFIX}   标题: {title}")
    print(f"{_MOCK_PREFIX}   元素数: {len(elements)}")
    print(f"{_MOCK_PREFIX}   卡片内容: {json.dumps(card, ensure_ascii=False)[:300]}")
    return {"status": "ok", "provider": "mock", "message_id": msg_id}


def mock_reaction(message_id: str, emoji: str = "👍") -> dict[str, Any]:
    """Mock 模式下模拟 Reaction 事件，直接调用后端确认/打回端点"""
    import requests
    print(f"\n{_MOCK_PREFIX} 模拟 Reaction: {emoji} → message_id={message_id}")
    try:
        r = requests.post(
            "http://127.0.0.1:8000/api/v1/feishu/decision/reaction",
            json={"message_id": message_id, "emoji": emoji},
            timeout=5,
        )
        result = r.json()
        print(f"{_MOCK_PREFIX}   结果: {json.dumps(result, ensure_ascii=False)}")
        return result
    except Exception as e:
        print(f"{_MOCK_PREFIX}   失败: {e}")
        return {"status": "error", "message": str(e)}


def mock_start_ws_client() -> None:
    print(f"\n{_MOCK_PREFIX} 飞书 WebSocket 事件监听已就绪 (模拟模式)")
    print(f"{_MOCK_PREFIX}   在 Mock 模式下，不会建立真实的飞书连接")
    print(f"{_MOCK_PREFIX}   群聊消息测试请使用 HTTP API: POST /api/v1/feishu/message/analyze")
    print(f"{_MOCK_PREFIX}   按 Ctrl+C 退出")
    try:
        while True:
            import time
            time.sleep(60)
            logger.debug("Mock WS: 等待中...")
    except KeyboardInterrupt:
        print(f"\n{_MOCK_PREFIX} Mock 模式监听已停止")
