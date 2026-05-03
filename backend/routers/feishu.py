from datetime import datetime
import json
import os
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.routers import memory
from db.relational.models import DecisionMemory, Memory

try:
    from feishu.verification import validate_signature
except Exception:
    def validate_signature(token, timestamp, nonce, body, signature):
        """本地开发兜底：未配置飞书 SDK 时只在有 token 的情况下跳过空签名。"""
        return not token or bool(signature)


router = APIRouter(prefix="/feishu", tags=["飞书协同记忆"])


class FeishuMessage(BaseModel):
    content: str
    chat_id: Optional[str] = None
    user_id: Optional[str] = None
    message_id: Optional[str] = None
    mentioned: bool = False
    source: str = "feishu_group"


class DecisionExtractRequest(BaseModel):
    content: str
    chat_id: Optional[str] = None
    user_id: Optional[str] = None
    message_id: Optional[str] = None
    source: str = "feishu_group"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeishuQueryRequest(BaseModel):
    query: str
    chat_id: Optional[str] = None
    user_id: Optional[str] = None
    limit: int = 5


DECISION_MARKERS = (
    "决定",
    "确认",
    "统一",
    "以后",
    "不再",
    "废弃",
    "改成",
    "更正",
    "不对",
    "结论",
    "采用",
    "方案",
)

QUERY_MARKERS = (
    "怎么",
    "如何",
    "查询",
    "有没有",
    "谁知道",
    "流程",
    "命令",
    "启动",
    "部署",
    "重启",
    "清理",
)


def _has_db(db: Any) -> bool:
    return hasattr(db, "query") and hasattr(db, "add")


def _metadata_from_json(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _metadata_to_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata or {}, ensure_ascii=False)


def _clean_bot_mention(content: str) -> str:
    return re.sub(r"@[\w\-\u4e00-\u9fff]+", "", content or "").strip()


def _contains_any(content: str, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in (content or "").lower() for marker in markers)


def is_decision_message(content: str) -> bool:
    return _contains_any(content, DECISION_MARKERS)


def is_query_message(content: str) -> bool:
    return _contains_any(content, QUERY_MARKERS)


def _extract_project(content: str) -> Optional[str]:
    patterns = [
        r"(project-[a-zA-Z0-9_-]+)",
        r"(项目\s*[a-zA-Z0-9_\-\u4e00-\u9fff]+)",
        r"(webapp|api-server|订单库|用户服务|支付服务)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1).replace("项目", "").strip()
    return None


def _extract_reason(content: str) -> Optional[str]:
    match = re.search(r"(?:因为|原因是|理由是)([^。；;\n]+)", content)
    return match.group(1).strip() if match else None


def _extract_preferred_terms(content: str) -> list[str]:
    terms: list[str] = []
    for pattern in (
        r"(?:统一用|统一使用|以后用|以后统一用|采用|改成|换成)\s*([a-zA-Z0-9_\-./:]+)",
        r"(?:发给)\s*([a-zA-Z0-9_.@-]+)",
    ):
        terms.extend(match.group(1) for match in re.finditer(pattern, content, re.IGNORECASE))
    return list(dict.fromkeys(term for term in terms if term))


def _extract_rejected_terms(content: str) -> list[str]:
    terms: list[str] = []
    for pattern in (
        r"(?:不再使用|不用|废弃|放弃|不能再用|不要再用)\s*([a-zA-Z0-9_\-./:]+)",
        r"([a-zA-Z0-9_\-./:]+)\s*(?:废弃|不用了|不再用了)",
    ):
        terms.extend(match.group(1) for match in re.finditer(pattern, content, re.IGNORECASE))
    return list(dict.fromkeys(term for term in terms if term))


def _topic_key(project: Optional[str], content: str, chat_id: Optional[str]) -> str:
    if project:
        return f"decision:{chat_id or 'global'}:{project.lower()}"
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", content))
    ascii_terms = "-".join(re.findall(r"[a-zA-Z0-9_-]+", content.lower())[:4])
    compact = cjk[:12] or ascii_terms or "general"
    return f"decision:{chat_id or 'global'}:{compact}"


def extract_decision(content: str, chat_id: Optional[str] = None) -> dict[str, Any]:
    cleaned = _clean_bot_mention(content)
    project = _extract_project(cleaned)
    reason = _extract_reason(cleaned)
    preferred_terms = _extract_preferred_terms(cleaned)
    rejected_terms = _extract_rejected_terms(cleaned)
    topic = project or "团队决策"
    conclusion = cleaned.rstrip("。")

    return {
        "topic": topic,
        "conclusion": conclusion,
        "reason": reason,
        "project": project,
        "preferred_terms": preferred_terms,
        "rejected_terms": rejected_terms,
        "topic_key": _topic_key(project, cleaned, chat_id),
    }


def _memory_to_card(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    if item.get("type") == "cli_workflow":
        return {
            "card_type": "workflow",
            "title": f"工作流：{metadata.get('name') or item.get('description') or item.get('content')}",
            "summary": item.get("description") or "历史工作流",
            "steps": metadata.get("steps", []),
            "source": item.get("source"),
            "memory_id": item.get("id"),
        }
    if item.get("type") == "cli_command":
        return {
            "card_type": "cli_command",
            "title": "历史 CLI 命令",
            "command": item.get("content"),
            "usage_count": metadata.get("count", 0),
            "success_count": metadata.get("success_count", 0),
            "directory": metadata.get("directory"),
            "source": item.get("source"),
            "memory_id": item.get("id"),
        }
    return {
        "card_type": "decision",
        "title": metadata.get("topic") or item.get("type"),
        "summary": metadata.get("conclusion") or item.get("content"),
        "reason": metadata.get("reason"),
        "project": metadata.get("project"),
        "preferred_terms": metadata.get("preferred_terms", []),
        "rejected_terms": metadata.get("rejected_terms", []),
        "source": item.get("source"),
        "memory_id": item.get("id"),
    }


def _cards_to_text(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "没有找到相关团队记忆。"

    lines = ["找到以下团队记忆："]
    for index, card in enumerate(cards, start=1):
        card_type = card.get("card_type")
        if card_type == "cli_command":
            lines.append(f"{index}. 历史 CLI 命令：{card.get('command')}")
            if card.get("usage_count"):
                lines.append(f"   使用次数：{card.get('usage_count')}")
            if card.get("directory"):
                lines.append(f"   项目目录：{card.get('directory')}")
        elif card_type == "workflow":
            lines.append(f"{index}. 工作流：{card.get('title')}")
            for step_index, step in enumerate(card.get("steps") or [], start=1):
                lines.append(f"   {step_index}) {step}")
        else:
            lines.append(f"{index}. 团队决策：{card.get('summary')}")
            if card.get("reason"):
                lines.append(f"   原因：{card.get('reason')}")
            if card.get("preferred_terms"):
                lines.append(f"   推荐：{', '.join(card.get('preferred_terms'))}")
            if card.get("rejected_terms"):
                lines.append(f"   废弃：{', '.join(card.get('rejected_terms'))}")
    return "\n".join(lines)


def _send_group_text(chat_id: Optional[str], text: str) -> dict[str, Any]:
    if not chat_id:
        return {"status": "skipped", "reason": "缺少 chat_id"}
    try:
        from feishu_bot.sdk_messages import send_text_message
    except Exception as exc:
        return {"status": "error", "provider": "lark-oapi", "message": str(exc)}
    return send_text_message(chat_id=chat_id, text=text)


def _auto_reply_enabled() -> bool:
    return os.getenv("FEISHU_AUTO_REPLY", "").lower() in {"1", "true", "yes", "on"}


def _store_decision_record(request: DecisionExtractRequest, db: Session) -> dict[str, Any]:
    decision = extract_decision(request.content, request.chat_id)
    metadata = {
        **request.metadata,
        **decision,
        "chat_id": request.chat_id,
        "message_id": request.message_id,
        "status": "active",
        "extracted_at": datetime.now().isoformat(),
    }
    stored = memory.store_memory(
        memory.MemoryStoreRequest(
            content=decision["conclusion"],
            type="project_decision",
            description=f"项目决策：{decision['topic']}",
            metadata=metadata,
            source=request.source,
            user_id=request.user_id,
            team_id=request.chat_id,
        ),
        db,
    )

    if _has_db(db):
        exists = db.query(DecisionMemory).filter(DecisionMemory.id == stored["id"]).first()
        if not exists:
            db.add(
                DecisionMemory(
                    id=stored["id"],
                    topic=decision["topic"],
                    conclusion=decision["conclusion"],
                    reason=decision.get("reason"),
                    related_persons=request.user_id,
                )
            )
            db.commit()
    return {"status": "stored", "decision": decision, "memory": stored}


def _query_related_cards(query: str, limit: int, db: Session) -> list[dict[str, Any]]:
    related = memory.search_memories(query=query, limit=limit, db=db)
    cards = [_memory_to_card(item) for item in related]
    if not _has_db(db):
        cards.extend(_query_temp_cli_cards(query, limit))
    return cards[:limit]


def _query_temp_cli_cards(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        from backend.routers import cli
    except Exception:
        return []

    query_terms = [term.lower() for term in re.findall(r"[a-zA-Z0-9_.:/-]+", query)]
    aliases = {
        "启动": ["run", "start"],
        "部署": ["deploy", "apply"],
        "重启": ["restart", "rollout"],
        "清理": ["prune", "clean"],
        "容器": ["docker"],
    }
    for keyword, terms in aliases.items():
        if keyword in query:
            query_terms.extend(terms)
    cjk_terms = [term for term in re.findall(r"[\u4e00-\u9fff]+", query) if len(term) >= 2]

    matches = []
    for item in cli.temp_command_storage:
        command = item.get("command", "")
        haystack = f"{command} {item.get('description', '')}".lower()
        score = sum(1 for term in query_terms if term in haystack)
        score += sum(1 for term in cjk_terms if term in haystack)
        if score:
            matches.append((score, item))

    matches.sort(key=lambda pair: (pair[0], pair[1].get("metadata", {}).get("count", 0)), reverse=True)
    cards = []
    for _, item in matches[:limit]:
        metadata = item.get("metadata") or {}
        cards.append(
            {
                "card_type": "cli_command",
                "title": "历史 CLI 命令",
                "command": item.get("command"),
                "usage_count": metadata.get("count", 0),
                "success_count": metadata.get("success_count", 0),
                "directory": metadata.get("directory"),
                "source": "cli",
                "memory_id": item.get("id"),
            }
        )
    return cards


@router.post("/event/callback")
async def feishu_event_callback(request: Request, db: Session = Depends(get_db)):
    """飞书事件回调接口：校验签名，并对消息事件做决策提取或知识查询。"""
    signature = request.headers.get("X-Lark-Signature")
    timestamp = request.headers.get("X-Lark-Request-Timestamp")
    nonce = request.headers.get("X-Lark-Request-Nonce")
    body = await request.body()

    if not validate_signature(os.getenv("FEISHU_VERIFICATION_TOKEN"), timestamp, nonce, body, signature):
        raise HTTPException(status_code=403, detail="签名验证失败")

    event_data = await request.json()
    if event_data.get("type") == "url_verification":
        return {"challenge": event_data.get("challenge")}

    content = _extract_event_content(event_data)
    if not content:
        return {"status": "ok"}

    message = FeishuMessage(content=content, chat_id=_extract_chat_id(event_data), user_id=_extract_user_id(event_data))
    return handle_feishu_message(message, db)


@router.post("/message/push")
def push_feishu_message(user_id: str, content: str):
    """使用飞书官方 SDK 主动推送文本消息到飞书群。user_id 参数兼容旧接口，这里作为 chat_id 使用。"""
    return _send_group_text(user_id, content)


@router.post("/decision/extract")
def extract_and_store_decision(request: DecisionExtractRequest, db: Session = Depends(get_db)):
    """从飞书消息中提取结构化项目决策，并写入统一记忆库。"""
    if not is_decision_message(request.content):
        return {"status": "ignored", "reason": "未识别到决策语义"}
    return _store_decision_record(request, db)


@router.post("/memory/query")
def query_feishu_memory(request: FeishuQueryRequest, db: Session = Depends(get_db)):
    """在飞书侧查询历史决策、CLI 命令和工作流，并返回卡片化结果。"""
    cards = _query_related_cards(request.query, request.limit, db)
    return {"query": request.query, "cards": cards}


@router.post("/message/analyze")
def handle_feishu_message(message: FeishuMessage, db: Session = Depends(get_db)):
    """分析群消息：决策入库，或在相关话题出现时返回主动推送候选卡片。"""
    if is_decision_message(message.content):
        stored = _store_decision_record(
            DecisionExtractRequest(
                content=message.content,
                chat_id=message.chat_id,
                user_id=message.user_id,
                message_id=message.message_id,
                source=message.source,
            ),
            db,
        )
        reply = {"status": "skipped", "reason": "未开启 FEISHU_AUTO_REPLY"}
        if _auto_reply_enabled():
            reply = _send_group_text(message.chat_id, f"已记录团队决策：{stored['decision']['conclusion']}")
        return {"action": "decision_stored", "reply": reply, **stored}

    should_push = message.mentioned or is_query_message(message.content)
    cards = _query_related_cards(message.content, 3, db) if should_push else []
    reply = {"status": "skipped", "reason": "未开启 FEISHU_AUTO_REPLY"}
    if cards and _auto_reply_enabled():
        reply = _send_group_text(message.chat_id, _cards_to_text(cards))
    return {
        "action": "suggest_cards" if cards else "ignored",
        "should_push": bool(cards),
        "cards": cards,
        "reply": reply,
    }


def _extract_event_content(event_data: dict[str, Any]) -> Optional[str]:
    message = (event_data.get("event") or {}).get("message") or {}
    raw_content = message.get("content")
    if not raw_content:
        return None
    try:
        parsed = json.loads(raw_content)
        return parsed.get("text") or raw_content
    except (TypeError, ValueError):
        return raw_content


def _extract_chat_id(event_data: dict[str, Any]) -> Optional[str]:
    return ((event_data.get("event") or {}).get("message") or {}).get("chat_id")


def _extract_user_id(event_data: dict[str, Any]) -> Optional[str]:
    sender = (event_data.get("event") or {}).get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    return sender_id.get("user_id") or sender_id.get("open_id")
