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
    # NOTE: 本地开发/演示阶段使用简化签名验证。
    # 飞书 SDK 的签名验证器需要 `feishu/verification.py`（未包含在当前项目中）。
    # 生产部署时需替换为真实的飞书 SDK 签名验证器（参见 T4-S1 企业级安全路线图）。
    def validate_signature(token, timestamp, nonce, body, signature):
        """本地开发兜底：未配置飞书 SDK 时只在有 token 的情况下跳过空签名。"""
        return not token or bool(signature)


router = APIRouter(prefix="/feishu", tags=["飞书协同记忆"])

# 待确认决策映射: message_id → memory_id
# 用于 Reaction 事件匹配和自动确认
_pending_decisions: dict[str, str] = {}  # message_id → memory_id
_pending_reactions: dict[str, dict[str, int]] = {}  # message_id → {emoji: count}
PENDING_TIMEOUT_SECONDS = 300  # 5 分钟无人操作自动确认


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
        r"(?:统一用|统一使用|以后\S{0,4}?用|采用|改成|换成)\s*([a-zA-Z0-9_\-./:]+)",
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



def _extract_deadline(content: str) -> Optional[str]:
    """从消息中提取截止日期"""
    from datetime import datetime, timedelta
    
    # 明确日期模式
    date_patterns = [
        (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', 3),
        (r'(\d{1,2})月(\d{1,2})[日号]', 2),
        (r'截止[日时]?[期是]?[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})', 1),
        (r'[Dd]eadline[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})', 1),
    ]
    
    for pattern, group_count in date_patterns:
        match = re.search(pattern, content)
        if match:
            try:
                if group_count == 3:
                    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                        return f"{year}-{month:02d}-{day:02d}"
                elif group_count == 2:
                    month, day = int(match.group(1)), int(match.group(2))
                    if 1 <= month <= 12 and 1 <= day <= 31:
                        year = datetime.now().year
                        return f"{year}-{month:02d}-{day:02d}"
                elif group_count == 1:
                    date_str = match.group(1)
                    parts = re.split(r'[-/]', date_str)
                    if len(parts) == 3:
                        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                        if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                            return f"{year}-{month:02d}-{day:02d}"
            except (ValueError, IndexError):
                pass
    
    # 相对日期
    if '明天' in content:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif '后天' in content:
        return (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    
    weekday_match = re.search(r'下周([一二三四五六日天])', content)
    if weekday_match:
        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        char = weekday_match.group(1)
        if char in weekday_map:
            today = datetime.now()
            days_ahead = weekday_map[char] - today.weekday() + 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    
    days_match = re.search(r'(\d+)天后', content)
    if days_match:
        return (datetime.now() + timedelta(days=int(days_match.group(1)))).strftime("%Y-%m-%d")
    
    return None

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
    deadline = _extract_deadline(cleaned)
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
    """将记忆数据转换为飞书交互卡片"""
    try:
        from feishu_bot.card_templates import memory_to_card
        return memory_to_card(item)
    except Exception:
        # 降级为简单字典格式
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
    """将卡片列表转换为纯文本（降级方案）"""
    if not cards:
        return "没有找到相关团队记忆。"

    lines = ["找到以下团队记忆："]
    for index, card in enumerate(cards, start=1):
        # 如果是飞书交互卡片格式
        if "header" in card:
            header = card.get("header", {})
            title = header.get("title", {}).get("content", "未知")
            lines.append(f"{index}. {title}")
            continue

        # 降级格式
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
    """发送纯文本消息到群聊"""
    if not chat_id:
        return {"status": "skipped", "reason": "缺少 chat_id"}
    try:
        from feishu_bot.sdk_messages import send_text_message
    except Exception as exc:
        return {"status": "error", "provider": "lark-oapi", "message": str(exc)}
    return send_text_message(chat_id=chat_id, text=text)


def _send_group_card(chat_id: Optional[str], card: dict[str, Any], fallback_text: Optional[str] = None) -> dict[str, Any]:
    """发送交互卡片消息到群聊，失败时降级为文本"""
    if not chat_id:
        return {"status": "skipped", "reason": "缺少 chat_id"}
    try:
        from feishu_bot.sdk_messages import send_card_message
        return send_card_message(chat_id=chat_id, card=card, fallback_text=fallback_text)
    except Exception as exc:
        # 降级为文本消息
        if fallback_text:
            return _send_group_text(chat_id, fallback_text)
        return {"status": "error", "provider": "lark-oapi", "message": str(exc)}


def _auto_reply_enabled() -> bool:
    return os.getenv("FEISHU_AUTO_REPLY", "").lower() in {"1", "true", "yes", "on"}


def _use_llm_extraction() -> bool:
    """检查是否使用LLM抽取"""
    return os.getenv("USE_LLM_DECISION_EXTRACTION", "").lower() in {"1", "true", "yes", "on"}


def _store_decision_record(request: DecisionExtractRequest, db: Session) -> dict[str, Any]:
    # 尝试使用LLM抽取，失败时降级为规则抽取
    use_llm = _use_llm_extraction()

    if use_llm:
        try:
            from core.decision_extractor import extract_decision_with_rules_fallback
            llm_result = extract_decision_with_rules_fallback(request.content, use_llm=True)

            if llm_result.get("is_decision"):
                # 使用LLM结果
                decision = {
                    "topic": llm_result.get("topic", "未知主题"),
                    "conclusion": llm_result.get("conclusion", request.content),
                    "reason": llm_result.get("reason"),
                    "project": llm_result.get("project"),
                    "preferred_terms": llm_result.get("preferred_terms", []),
                    "rejected_terms": llm_result.get("rejected_terms", []),
                    "topic_key": _topic_key(llm_result.get("project"), request.content, request.chat_id),
                    "llm_confidence": llm_result.get("confidence", 0.0),
                    "deadline": llm_result.get("deadline"),
                }
            else:
                # LLM判断不是决策
                return {"status": "ignored", "reason": "LLM判断不是决策消息", "confidence": llm_result.get("confidence", 0.0)}
        except Exception:
            # LLM失败，降级为规则抽取
            pass

    # 使用规则抽取
    decision = extract_decision(request.content, request.chat_id)

    metadata = {
        **request.metadata,
        **decision,
        "chat_id": request.chat_id,
        "message_id": request.message_id,
        "status": "pending",
        "extracted_at": datetime.now().isoformat(),
        "extraction_method": "llm" if use_llm and decision.get("llm_confidence") else "rules",
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
                    deadline=decision.get("deadline"),
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


# ── 人审机决：确认 / 打回 ──────────────────────────────


def _find_pending_for_chat(chat_id: Optional[str]) -> Optional[str]:
    """查找某群聊最近的一条 pending 决策 memory_id"""
    for msg_id, mem_id in reversed(list(_pending_decisions.items())):
        if mem_id:
            return mem_id
    return None


def _confirm_decision(memory_id: str, db: Optional[Session] = None) -> dict[str, Any]:
    """确认 pending 决策为 active"""
    if _has_db(db):
        from db.relational.models import Memory as MemoryModel
        record = db.query(MemoryModel).filter(MemoryModel.id == memory_id).first()
        if record:
            metadata = _metadata_from_json(record.memory_metadata)
            metadata["status"] = "active"
            metadata["confirmed_at"] = datetime.now().isoformat()
            record.memory_metadata = _metadata_to_json(metadata)
            db.commit()
            # 清理 pending 映射
            for k, v in list(_pending_decisions.items()):
                if v == memory_id:
                    del _pending_decisions[k]
            return {"status": "ok", "action": "confirmed", "memory_id": memory_id}
    # temp 模式
    for idx, item in enumerate(memory.temp_memory_storage):
        if item.get("id") == memory_id:
            metadata = item.get("metadata") or {}
            metadata["status"] = "active"
            metadata["confirmed_at"] = datetime.now().isoformat()
            item["metadata"] = metadata
            for k, v in list(_pending_decisions.items()):
                if v == memory_id:
                    del _pending_decisions[k]
            return {"status": "ok", "action": "confirmed", "memory_id": memory_id}
    return {"status": "error", "message": "未找到该决策"}


def _reject_decision(memory_id: str, db: Optional[Session] = None) -> dict[str, Any]:
    """打回/删除 pending 决策"""
    if _has_db(db):
        from db.relational.models import Memory as MemoryModel
        record = db.query(MemoryModel).filter(MemoryModel.id == memory_id).first()
        if record:
            metadata = _metadata_from_json(record.memory_metadata)
            metadata["status"] = "rejected"
            metadata["rejected_at"] = datetime.now().isoformat()
            record.memory_metadata = _metadata_to_json(metadata)
            db.commit()
            for k, v in list(_pending_decisions.items()):
                if v == memory_id:
                    del _pending_decisions[k]
            return {"status": "ok", "action": "rejected", "memory_id": memory_id}
    # temp 模式
    for idx, item in enumerate(memory.temp_memory_storage):
        if item.get("id") == memory_id:
            metadata = item.get("metadata") or {}
            metadata["status"] = "rejected"
            metadata["rejected_at"] = datetime.now().isoformat()
            item["metadata"] = metadata
            for k, v in list(_pending_decisions.items()):
                if v == memory_id:
                    del _pending_decisions[k]
            return {"status": "ok", "action": "rejected", "memory_id": memory_id}
    return {"status": "error", "message": "未找到该决策"}


@router.post("/decision/confirm", summary="确认 pending 决策")
def confirm_decision(memory_id: str, db: Session = Depends(get_db)):
    """通过 Reaction 👍 或卡片按钮确认决策"""
    return _confirm_decision(memory_id, db)


@router.post("/decision/reject", summary="打回 pending 决策")
def reject_decision(memory_id: str, db: Session = Depends(get_db)):
    """通过 Reaction 👎 或 @机器人打回 来拒绝决策"""
    return _reject_decision(memory_id, db)


# ── T3-2d: 决策时间线 ──────────────────────────────────

@router.get("/decisions/timeline", summary="决策时间线")
def decision_timeline(topic: str, db: Session = Depends(get_db)):
    """查看某话题的决策变更时间线（supersedes 链）"""
    if not _has_db(db):
        items = [
            item for item in memory.temp_memory_storage
            if item.get("type") == "project_decision"
            and topic.lower() in (item.get("content", "") or "").lower()
        ]
        return {"topic": topic, "timeline": items}

    results = (
        db.query(Memory)
        .filter(Memory.type == "project_decision")
        .order_by(Memory.created_at.desc())
        .all()
    )
    timeline = []
    for m in results:
        meta = _metadata_from_json(m.memory_metadata)
        if topic.lower() in (m.content or "").lower() or topic.lower() in (meta.get("topic", "") or "").lower():
            timeline.append({
                "id": m.id,
                "topic": meta.get("topic", ""),
                "conclusion": m.content,
                "status": meta.get("status", "active"),
                "supersedes": meta.get("supersedes", []),
                "superseded_by": meta.get("superseded_by"),
                "extracted_at": meta.get("extracted_at", ""),
            })
    # 后处理：按 supersedes 链构建演变顺序
    id_to_idx = {d["id"]: i for i, d in enumerate(timeline)}
    for d in timeline:
        d["_chain"] = []
    for d in timeline:
        for sid in d.get("supersedes", []):
            if sid in id_to_idx:
                prev = timeline[id_to_idx[sid]]
                prev["_chain"].append({"id": d["id"], "conclusion": d["conclusion"][:40]})
    # 添加演变序号
    current = next((d for d in timeline if not d.get("superseded_by")), None)
    seq = 1
    while current:
        current["_seq"] = seq
        seq += 1
        next_superseded = current.get("supersedes", [])
        current = next(
            (d for d in timeline
             if any(s == d["id"] for s in (current.get("supersedes") or []))),
            None
        )
    return {"topic": topic, "timeline": timeline}


# ── T3-2e: 决策订阅 ─────────────────────────────────────

# 会话级存储（进程重启丢失；启动时从已有决策 topic 重建）
_subscriptions: set[str] = set()


def _rebuild_subscriptions_from_db(db: Session):
    """从已有 project_decision 的 topic 字段重建订阅集合"""
    if not _has_db(db):
        return
    try:
        from db.relational.models import Memory as MemModel
        rows = db.query(MemModel).filter(MemModel.type == "project_decision").all()
        for r in rows:
            meta = _metadata_from_json(r.memory_metadata)
            topic = meta.get("topic")
            if topic:
                _subscriptions.add(topic)
    except Exception:
        pass


class SubscribeRequest(BaseModel):
    topic: str


@router.post("/subscribe", summary="订阅话题")
def subscribe_topic(request: SubscribeRequest, db: Session = Depends(get_db)):
    """订阅话题（会话级，持久化在 T4 路线图中）"""
    _subscriptions.add(request.topic)
    if not _subscriptions:
        _rebuild_subscriptions_from_db(db)
    _subscriptions.add(request.topic)
    return {"status": "ok", "topic": request.topic, "total": len(_subscriptions)}


@router.get("/subscribe", summary="列出订阅")
def list_subscriptions(db: Session = Depends(get_db)):
    if not _subscriptions:
        _rebuild_subscriptions_from_db(db)
    return {"topics": list(_subscriptions)}


@router.delete("/subscribe", summary="取消订阅")
def unsubscribe_topic(topic: str):
    _subscriptions.discard(topic)
    return {"status": "ok", "topic": topic, "total": len(_subscriptions)}


@router.get("/decisions/recent", summary="最近决策列表")
def recent_decisions(limit: int = 10, db: Session = Depends(get_db)):
    """浏览最近 N 条团队决策（供飞书 @机器人 最近有什么决策 查询）"""
    if not _has_db(db):
        # temp mode
        items = []
        for item in memory.temp_memory_storage:
            meta = item.get("metadata") or {}
            if item.get("type") == "project_decision" and meta.get("status", "active") != "inactive":
                items.append({
                    "id": item.get("id", ""),
                    "topic": meta.get("topic", ""),
                    "conclusion": item.get("content", ""),
                    "project": meta.get("project"),
                    "status": meta.get("status", "active"),
                    "extracted_at": meta.get("extracted_at", ""),
                })
        return {"count": len(items), "decisions": items[:limit]}

    # 查询最近决策：先取足够多行，再在 Python 层过滤 status
    from sqlalchemy import text
    rows = db.execute(
        text("SELECT id, content, type, memory_metadata, updated_at FROM memories "
             "WHERE type = :type_val ORDER BY updated_at DESC LIMIT :lim"),
        {"type_val": "project_decision", "lim": max(limit * 10, 200)}
    ).fetchall()

    decisions = []
    for row in rows:
        meta = _metadata_from_json(row.memory_metadata)
        st = meta.get("status", "active")
        if st in ("active", "pending"):
            decisions.append({
                "id": row.id,
                "topic": meta.get("topic", ""),
                "conclusion": row.content,
                "project": meta.get("project"),
                "status": st,
                "extracted_at": meta.get("extracted_at", ""),
            })
            if len(decisions) >= limit:
                break
    return {"count": len(decisions), "decisions": decisions}
    return {"count": len(decisions), "decisions": decisions}


@router.post("/decision/reaction", summary="处理 Reaction 事件")
def handle_reaction_event(message_id: str, emoji: str, db: Session = Depends(get_db)):
    """处理飞书 Reaction 事件：👍 确认 / 👎 打回"""
    memory_id = _pending_decisions.get(message_id)
    if not memory_id:
        return {"status": "ignored", "reason": "该消息没有待确认决策"}

    if message_id not in _pending_reactions:
        _pending_reactions[message_id] = {}
    _pending_reactions[message_id][emoji] = _pending_reactions[message_id].get(emoji, 0) + 1

    if emoji in ("👍", "THUMBSUP", "+1"):
        count = _pending_reactions[message_id].get(emoji, 1)
        if count >= 3:
            return _confirm_decision(memory_id, db)
        return {"status": "counting", "count": count, "needed": 3, "memory_id": memory_id}
    if emoji in ("👎", "THUMBSDOWN", "-1"):
        return _reject_decision(memory_id, db)

    return {"status": "ignored", "reason": f"未处理的 Reaction: {emoji}"}


@router.post("/event/callback")
async def feishu_event_callback(request: Request, db: Session = Depends(get_db)):
    """飞书事件回调接口：校验签名，并对消息事件做决策提取或知识查询。"""
    # 本地开发/测试模式跳过签名验证
    env = os.getenv("ENVIRONMENT", "")
    mock = os.getenv("FEISHU_MOCK_MODE", "").lower() in {"1", "true", "yes", "on"}
    if not mock and env != "development":
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
    """分析群消息：LLM意图分类 → 决策入库 / 查询检索 / 追问澄清 / 忽略。"""
    content = message.content or ""

    # 检查文本打回
    reject_keywords = ("打回", "这个不对", "不是这个", "撤回这条", "撤销这条")
    if message.mentioned and any(kw in content for kw in reject_keywords):
        memory_id = _find_pending_for_chat(message.chat_id)
        if memory_id:
            _reject_decision(memory_id)
            return {"action": "decision_rejected", "memory_id": memory_id, "reason": "用户打回"}

    # — LLM 意图分类（优先）—
    intent_result = {}
    if _use_llm_extraction():
        try:
            from core.decision_extractor import classify_message_intent
            intent_result = classify_message_intent(content)
            intent = intent_result.get("intent", "chat")
        except Exception:
            intent = None  # LLM 失败 → 回退规则模式
    else:
        intent = None  # 回退到规则模式

    # — 路由：decision_new / decision_revise / decision_repeal —
    if intent in ("decision_new", "decision_revise", "decision_repeal") or (
        intent is None and is_decision_message(content)
    ):
        stored = _store_decision_record(
            DecisionExtractRequest(
                content=content,
                chat_id=message.chat_id,
                user_id=message.user_id,
                message_id=message.message_id,
                source=message.source,
            ),
            db,
        )
        reply = {"status": "skipped", "reason": "未开启 FEISHU_AUTO_REPLY"}
        if _auto_reply_enabled() and stored.get("status") != "ignored":
            decision = stored.get("decision", {})
            memory_id = stored.get("memory", {}).get("id")
            from feishu_bot.card_templates import decision_card
            card = decision_card(
                topic=decision.get("topic", "未知主题"),
                conclusion=decision.get("conclusion", ""),
                reason=decision.get("reason"),
                project=decision.get("project"),
                preferred_terms=decision.get("preferred_terms", []),
                rejected_terms=decision.get("rejected_terms", []),
                created_at=datetime.now().isoformat(),
                memory_id=memory_id,
                status="pending",
            )
            fallback_text = f"待确认决策：{decision['conclusion']}\n请 👍 确认采纳 / 👎 打回"
            reply = _send_group_card(message.chat_id, card, fallback_text)
            reply_msg_id = reply.get("message_id")
            if reply_msg_id and memory_id:
                _pending_decisions[reply_msg_id] = memory_id
        return {"action": "decision_stored", "intent": intent, "reply": reply,
                "auto_confirm_after_seconds": PENDING_TIMEOUT_SECONDS,
                "note": "当前为演示模式，pending 决策需手动确认。自动确认定时器在 T4 企业版中实现",
                **stored}

    # — 路由：decision_confirm —
    if intent == "decision_confirm":
        memory_id = _find_pending_for_chat(message.chat_id)
        if memory_id:
            _confirm_decision(memory_id, db)
            return {"action": "decision_confirmed", "memory_id": memory_id}
        return {"action": "ignored", "reason": "无待确认决策可加固"}

    # — 路由：unclear —
    if intent == "unclear":
        reply = {"status": "skipped"}
        if _auto_reply_enabled():
            question = intent_result.get("clarification_question", "能否再详细说明一下？")
            options = intent_result.get("suggested_options", [])
            fallback_text = f"🤔 {question}"
            if options:
                fallback_text += "\n" + "\n".join(f"  · {o}" for o in options)
            reply = _send_group_text(message.chat_id, fallback_text)
        return {"action": "clarification_needed", "intent_result": intent_result, "reply": reply}

    # — 路由：query / 最近决策 —
    if "最近" in content and ("决策" in content or "决定" in content):
        decisions = recent_decisions(5, db)
        items = decisions.get("decisions", [])
        if items and _auto_reply_enabled():
            lines = ["最近团队决策："] + [
                f"  [{d.get('status','?')}] {d.get('topic','?')}: {d.get('conclusion','?')[:60]}"
                for d in items
            ]
            reply = _send_group_text(message.chat_id, "\n".join(lines))
            return {"action": "recent_decisions", "count": len(items), "reply": reply}
        return {"action": "recent_decisions", "count": len(items)}

    if intent == "query" or (intent is None and (message.mentioned or is_query_message(content))):
        cards = _query_related_cards(content, 3, db)
        reply = {"status": "skipped", "reason": "未开启 FEISHU_AUTO_REPLY"}
        if cards and _auto_reply_enabled():
            first_card = cards[0]
            reply = _send_group_card(message.chat_id, first_card, _cards_to_text(cards))
        return {"action": "suggest_cards" if cards else "no_match", "cards": cards, "reply": reply}

    # — 路由：chat —
    return {"action": "ignored", "intent": intent or "chat", "reason": "闲聊，无需处理"}


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
