import json
import os
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()


def _credentials(app_id: Optional[str] = None, app_secret: Optional[str] = None) -> tuple[str, str]:
    resolved_app_id = app_id or os.getenv("FEISHU_APP_ID")
    resolved_app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")
    if not resolved_app_id or not resolved_app_secret:
        raise RuntimeError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")
    return resolved_app_id, resolved_app_secret


def create_client(app_id: Optional[str] = None, app_secret: Optional[str] = None):
    """创建飞书官方 SDK Client。"""
    try:
        import lark_oapi as lark
    except ModuleNotFoundError as exc:
        raise RuntimeError("未安装 lark-oapi，请先执行 pip install lark-oapi") from exc

    resolved_app_id, resolved_app_secret = _credentials(app_id, app_secret)
    return lark.Client.builder().app_id(resolved_app_id).app_secret(resolved_app_secret).build()


def send_text_message(
    chat_id: str,
    text: str,
    *,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    client: Any = None,
) -> dict[str, Any]:
    """使用飞书官方 Python SDK 以机器人身份发送群文本消息。"""
    if not chat_id:
        return {"status": "skipped", "reason": "缺少 chat_id"}

    try:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    except ModuleNotFoundError as exc:
        raise RuntimeError("未安装 lark-oapi，请先执行 pip install lark-oapi") from exc

    sdk_client = client or create_client(app_id, app_secret)
    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    response = sdk_client.im.v1.message.create(request)

    if hasattr(response, "success") and response.success():
        data = getattr(response, "data", None)
        return {
            "status": "ok",
            "provider": "lark-oapi",
            "message_id": getattr(data, "message_id", None),
        }

    return {
        "status": "error",
        "provider": "lark-oapi",
        "code": getattr(response, "code", None),
        "message": getattr(response, "msg", None) or getattr(response, "error", None),
    }
