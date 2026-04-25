from fastapi import APIRouter, Request, HTTPException
import os
from feishu.verification import validate_signature

router = APIRouter()

@router.post("/event/callback")
async def feishu_event_callback(request: Request):
    """飞书事件回调接口"""
    signature = request.headers.get("X-Lark-Signature")
    timestamp = request.headers.get("X-Lark-Request-Timestamp")
    nonce = request.headers.get("X-Lark-Request-Nonce")
    
    if not validate_signature(
        os.getenv("FEISHU_VERIFICATION_TOKEN"),
        timestamp,
        nonce,
        await request.body(),
        signature
    ):
        raise HTTPException(status_code=403, detail="签名验证失败")
    
    event_data = await request.json()
    if event_data.get("type") == "url_verification":
        return {"challenge": event_data.get("challenge")}
    
    return {"status": "ok"}

@router.post("/message/push")
def push_feishu_message(user_id: str, content: str):
    """主动推送消息到飞书"""
    return {"status": "ok"}
