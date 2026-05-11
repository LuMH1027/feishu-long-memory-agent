import json
import os
from typing import Any, Callable, Optional

import requests
from dotenv import load_dotenv

load_dotenv(override=True)


MessageHandler = Callable[[dict[str, Any]], Any]


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _message_text(message: Any) -> str:
    raw_content = _get_attr(message, "content", "") or ""
    if not raw_content:
        return ""
    try:
        parsed = json.loads(raw_content)
    except (TypeError, ValueError):
        return str(raw_content)
    return str(parsed.get("text") or raw_content)


def event_to_message_payload(event: Any) -> dict[str, Any]:
    """把飞书 SDK 的消息事件对象转换成后端方向B统一消息结构。"""
    event_body = _get_attr(event, "event", event)
    message = _get_attr(event_body, "message", {})
    sender = _get_attr(event_body, "sender", {})
    sender_id = _get_attr(sender, "sender_id", {})

    # 检测消息中是否 @了机器人
    raw_content = _get_attr(message, "content", "") or ""
    mentioned = False
    try:
        parsed = json.loads(raw_content)
        mentioned = bool(parsed.get("mentions"))
    except (TypeError, ValueError):
        pass

    return {
        "content": _message_text(message),
        "chat_id": _get_attr(message, "chat_id"),
        "message_id": _get_attr(message, "message_id"),
        "user_id": _get_attr(sender_id, "user_id") or _get_attr(sender_id, "open_id"),
        "mentioned": mentioned,
        "source": "feishu_group",
    }


def post_message_to_backend(payload: dict[str, Any], backend_url: Optional[str] = None) -> dict[str, Any]:
    """将 SDK 收到的群消息转交给本项目后端，由后端完成入库、检索和回复。"""
    base_url = (backend_url or os.getenv("MEM_AGENT_BACKEND_URL") or "http://127.0.0.1:8000").rstrip("/")
    response = requests.post(f"{base_url}/api/v1/feishu/message/analyze", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def _default_message_handler(payload: dict[str, Any]) -> dict[str, Any]:
    return post_message_to_backend(payload)


def build_event_handler(on_message: Optional[MessageHandler] = None):
    """构建飞书官方 SDK 事件处理器。

    真实运行依赖 `lark-oapi`。这里使用懒加载，避免未安装 SDK 时影响普通后端测试。
    """
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
    except ModuleNotFoundError as exc:
        raise RuntimeError("未安装 lark-oapi，请先执行 pip install lark-oapi") from exc

    handler = on_message or _default_message_handler

    def handle_message(event: P2ImMessageReceiveV1) -> None:
        payload = event_to_message_payload(event)
        if payload.get("content"):
            handler(payload)

    def handle_reaction(event) -> None:
        """处理飞书消息 Reaction 事件，转发到后端 /decision/reaction"""
        event_body = _get_attr(event, "event", event)
        message_id = _get_attr(event_body, "message_id", "")
        reaction = _get_attr(event_body, "reaction", {}) or {}
        # 支持多种 Reaction 嵌套结构
        if isinstance(reaction, dict):
            emoji = reaction.get("emoji") or reaction.get("type") or ""
        else:
            emoji = str(reaction)
        action = _get_attr(event_body, "action", "added")
        if not message_id or not emoji or action != "added":
            return
        try:
            import requests
            base_url = os.getenv("MEM_AGENT_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
            requests.post(
                f"{base_url}/api/v1/feishu/decision/reaction",
                json={"message_id": message_id, "emoji": emoji},
                timeout=5,
            )
        except Exception:
            pass

    try:
        from lark_oapi.api.im.v1 import P2ImMessageReactionV1
        return (
            lark.EventDispatcherHandler.builder(
                os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
                os.getenv("FEISHU_ENCRYPT_KEY", ""),
            )
            .register_p2_im_message_receive_v1(handle_message)
            .register_p2_im_message_reaction_v1(handle_reaction)
            .build()
        )
    except (ImportError, AttributeError):
        # 旧版 lark-oapi 可能没有 P2ImMessageReactionV1
        return (
            lark.EventDispatcherHandler.builder(
                os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
                os.getenv("FEISHU_ENCRYPT_KEY", ""),
            )
            .register_p2_im_message_receive_v1(handle_message)
            .build()
        )


def create_ws_client(app_id: Optional[str] = None, app_secret: Optional[str] = None, on_message: Optional[MessageHandler] = None):
    """创建飞书长连接客户端，适合本地开发时直接连接事件订阅。"""
    try:
        import lark_oapi as lark
    except ModuleNotFoundError as exc:
        raise RuntimeError("未安装 lark-oapi，请先执行 pip install lark-oapi") from exc

    resolved_app_id = app_id or os.getenv("FEISHU_APP_ID")
    resolved_app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")
    if not resolved_app_id or not resolved_app_secret:
        raise RuntimeError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")

    return lark.ws.Client(
        resolved_app_id,
        resolved_app_secret,
        event_handler=build_event_handler(on_message),
        log_level=getattr(lark.LogLevel, os.getenv("FEISHU_SDK_LOG_LEVEL", "INFO"), lark.LogLevel.INFO),
    )


def start_ws_client(app_id: Optional[str] = None, app_secret: Optional[str] = None, on_message: Optional[MessageHandler] = None) -> None:
    from feishu_bot.mock import should_use_mock
    if should_use_mock():
        from feishu_bot.mock import mock_start_ws_client
        mock_start_ws_client()
        return
    client = create_ws_client(app_id=app_id, app_secret=app_secret, on_message=on_message)
    client.start()
