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


def _card_action_value(action: Any) -> dict[str, Any]:
    if not action:
        return {}
    if isinstance(action, str):
        try:
            parsed = json.loads(action)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(action, dict):
        value = action.get("value")
        if isinstance(value, dict):
            return value
        return action

    value = getattr(action, "value", None)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def _card_action_field(action_value: Any, key: str, default: Any = "") -> Any:
    if isinstance(action_value, dict):
        return action_value.get(key, default)
    return getattr(action_value, key, default)


def _processed_decision_card(action_type: str, memory_id: str) -> dict[str, Any]:
    confirmed = action_type == "confirm_decision"
    status_text = "已确认采纳" if confirmed else "已打回"
    template = "green" if confirmed else "red"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": f"决策流程已结束：{status_text}"},
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"该决策已经**{status_text}**，后续不能重复确认或打回。\n\nmemory_id: `{memory_id}`",
                },
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "确认采纳"},
                        "type": "primary",
                        "disabled": True,
                        "value": {"action": "confirm_decision", "memory_id": memory_id},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打回"},
                        "type": "danger",
                        "disabled": True,
                        "value": {"action": "reject_decision", "memory_id": memory_id},
                    },
                ],
            },
        ],
    }


def _card_action_toast(toast_type: str, content: str, card: Optional[dict[str, Any]] = None) -> Any:
    payload = {"toast": {"type": toast_type, "content": content}}
    if card is not None:
        payload["card"] = {"type": "raw", "data": card}
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

        return P2CardActionTriggerResponse(payload)
    except ModuleNotFoundError:
        return payload


def _execute_card_action(action_value: dict[str, Any], backend_url: Optional[str] = None) -> tuple[str, str, Optional[dict[str, Any]]]:
    action_type = _card_action_field(action_value, "action", "")
    memory_id = _card_action_field(action_value, "memory_id", "")
    base_url = (backend_url or os.getenv("MEM_AGENT_BACKEND_URL") or "http://127.0.0.1:8000").rstrip("/")

    if action_type in ("confirm_decision", "reject_decision") and not memory_id:
        return "error", "操作失败：卡片缺少 memory_id", None

    endpoints = {
        "confirm_decision": ("/api/v1/feishu/decision/confirm", "已确认采纳该决策"),
        "reject_decision": ("/api/v1/feishu/decision/reject", "已打回该决策"),
    }
    if action_type in endpoints:
        endpoint, success_message = endpoints[action_type]
        response = requests.post(f"{base_url}{endpoint}", params={"memory_id": memory_id}, timeout=5)
        response.raise_for_status()
        result = response.json()
        print(f"[SDK事件] 卡片操作后端响应: action={action_type} result={result}", flush=True)
        if result.get("status") == "ok":
            return "success", success_message, _processed_decision_card(action_type, memory_id)
        message = result.get("message") or result.get("reason") or result.get("status") or "后端未返回成功"
        return "error", f"操作失败：{message}", None

    if action_type == "view_detail":
        return "info", "详情查看暂未接入，请通过查询命令查看该记忆", None
    if action_type == "view_history":
        return "info", "历史版本查看暂未接入，请通过查询命令查看", None
    if action_type in ("copy_command", "execute_command"):
        return "info", "CLI 操作需要在本地终端执行，飞书卡片暂不直接执行命令", None
    return "warning", f"未识别的卡片操作：{action_type or '空操作'}", None


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
    result = post_message_to_backend(payload)
    action = result.get("action", "?")
    intent = result.get("intent", "?")
    print(f"[SDK事件] 后端响应: action={action} intent={intent} "
          f"keys={list(result.keys())[:6]}", flush=True)
    return result


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
        content = payload.get("content", "")
        if content:
            print(f"[SDK事件] 收到消息: chat_id={payload.get('chat_id')} "
                  f"user_id={payload.get('user_id')} "
                  f"mentioned={payload.get('mentioned')} "
                  f"content={content[:100]}", flush=True)
            handler(payload)
        else:
            print(f"[SDK事件] 收到空内容消息，跳过: chat_id={payload.get('chat_id')}", flush=True)

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

    def handle_card_action(event) -> Any:
        """处理卡片按钮点击事件，转发到后端"""
        event_body = _get_attr(event, "event", event)
        action_value = _card_action_value(_get_attr(event_body, "action", None))
        if not isinstance(action_value, dict):
            print(f"[SDK事件] 卡片回调 action 解析结果不是 dict，跳过: type={type(action_value).__name__}", flush=True)
            return _card_action_toast("error", "操作失败：无法解析卡片按钮参数")
        try:
            toast_type, content, card = _execute_card_action(action_value)
        except Exception as exc:
            print(f"[SDK事件] 卡片操作失败: action={action_value} error={exc}", flush=True)
            return _card_action_toast("error", f"操作失败：{exc}")
        return _card_action_toast(toast_type, content, card)

    def handle_bot_added(event) -> None:
        """机器人被拉入群时发送欢迎消息"""
        event_body = _get_attr(event, "event", event)
        chat_id = _get_attr(event_body, "chat_id", "")
        if not chat_id:
            return
        welcome = (
            "👋 我是企业级记忆引擎机器人！\n\n"
            "我可以在群聊中：\n"
            "  📋 自动识别并记录团队决策\n"
            "  🔍 检索历史命令和决策\n"
            "  🔄 检测矛盾决策并更新\n\n"
            "试试 @我 说：\n"
            "  · 「以后统一用 XXX」— 记录新决策\n"
            "  · 「之前XX怎么部署的？」— 查询历史\n"
            "  · 「不对，改成YYY」— 修正决策"
        )
        try:
            from feishu_bot.sdk_messages import send_text_message
            send_text_message(chat_id=chat_id, text=welcome)
        except Exception:
            pass

    try:
        from lark_oapi.api.im.v1 import P2ImMessageReactionV1
        builder = (
            lark.EventDispatcherHandler.builder(
                os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
                os.getenv("FEISHU_ENCRYPT_KEY", ""),
            )
            .register_p2_im_message_receive_v1(handle_message)
            .register_p2_im_message_reaction_v1(handle_reaction)
        )
        if hasattr(builder, "register_p2_card_action_trigger"):
            builder = builder.register_p2_card_action_trigger(handle_card_action)
        if hasattr(builder, "register_p2_im_chat_member_bot_added_v1"):
            builder = builder.register_p2_im_chat_member_bot_added_v1(handle_bot_added)
        return builder.build()
    except (ImportError, AttributeError):
        # 旧版 lark-oapi 可能没有 P2ImMessageReactionV1
        builder = (
            lark.EventDispatcherHandler.builder(
                os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
                os.getenv("FEISHU_ENCRYPT_KEY", ""),
            )
            .register_p2_im_message_receive_v1(handle_message)
        )
        if hasattr(builder, "register_p2_im_message_reaction_created_v1"):
            builder = builder.register_p2_im_message_reaction_created_v1(handle_reaction)
        if hasattr(builder, "register_p2_im_message_reaction_deleted_v1"):
            builder = builder.register_p2_im_message_reaction_deleted_v1(handle_reaction)
        if hasattr(builder, "register_p2_card_action_trigger"):
            builder = builder.register_p2_card_action_trigger(handle_card_action)
        if hasattr(builder, "register_p2_im_chat_member_bot_added_v1"):
            builder = builder.register_p2_im_chat_member_bot_added_v1(handle_bot_added)
        return builder.build()


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
