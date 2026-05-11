from datetime import datetime
import json
import re
import uuid
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.schemas.memory import MemoryCreate, MemoryRetrieveRequest
from db.relational.models import Memory, DecisionMemory
from core import retriever
from core import storage

router = APIRouter()

# Unit-test fallback only. Real API requests receive a SQLAlchemy session.
temp_memory_storage: list[dict[str, Any]] = []
MAX_TEMP_MEMORIES = 1000


class MemoryStoreRequest(BaseModel):
    content: str
    type: str
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "cli"
    user_id: Optional[str] = None
    team_id: Optional[str] = None


def _has_db(db: Any) -> bool:
    return hasattr(db, "query") and hasattr(db, "add")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _metadata_to_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata or {}, ensure_ascii=False)


def _metadata_from_json(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _memory_to_dict(memory: Memory) -> dict[str, Any]:
    result = {
        "id": memory.id,
        "content": memory.content,
        "type": memory.type,
        "source": memory.source,
        "user_id": memory.user_id,
        "team_id": memory.team_id,
        "description": memory.description or "无描述",
        "metadata": _metadata_from_json(memory.memory_metadata),
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "expire_at": memory.expire_at.isoformat() if memory.expire_at else None,
        "hit_count": memory.hit_count or 0,
    }
    # 携带向量相似度（用于可解释性）
    similarity = getattr(memory, "similarity_score", None)
    if similarity is not None:
        result["similarity"] = similarity
    return result


def _memory_from_payload(payload: MemoryStoreRequest) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": uuid.uuid4().hex[:16],
        "content": payload.content,
        "type": payload.type,
        "source": payload.source,
        "user_id": payload.user_id,
        "team_id": payload.team_id,
        "description": payload.description or "无描述",
        "metadata": payload.metadata,
        "created_at": now,
        "updated_at": now,
        "expire_at": None,
        "hit_count": 0,
    }


CORRECTION_MARKERS = (
    "不对",
    "更正",
    "改成",
    "以后用",
    "以后改",
    "不再使用",
    "更新",
)


def _is_correction_memory(content: str) -> bool:
    content_lower = (content or "").lower()
    return any(marker.lower() in content_lower for marker in CORRECTION_MARKERS)


def _topic_key(payload: MemoryStoreRequest) -> str:
    explicit_topic = payload.metadata.get("topic_key")
    if explicit_topic:
        return str(explicit_topic)
    return f"{payload.source}:{payload.type}:{payload.user_id or ''}:{payload.team_id or ''}"


def _is_active_memory(memory: dict[str, Any]) -> bool:
    metadata = memory.get("metadata") or {}
    return metadata.get("status", "active") != "inactive"


def _prepare_correction_metadata(payload: MemoryStoreRequest, supersedes: list[str]) -> MemoryStoreRequest:
    metadata = dict(payload.metadata or {})
    metadata.setdefault("status", "active")
    if _is_correction_memory(payload.content):
        metadata["topic_key"] = _topic_key(payload)
        metadata["supersedes"] = supersedes
    return payload.model_copy(update={"metadata": metadata})


def _matching_topic_memory(memory: dict[str, Any], payload: MemoryStoreRequest, topic_key: str) -> bool:
    metadata = memory.get("metadata") or {}
    return (
        memory.get("type") == payload.type
        and memory.get("source") == payload.source
        and memory.get("user_id") == payload.user_id
        and memory.get("team_id") == payload.team_id
        and metadata.get("status", "active") != "inactive"
        and (metadata.get("topic_key") in (None, topic_key))
    )


def _supersede_temp_memories(payload: MemoryStoreRequest, new_memory_id: str) -> list[str]:
    if not _is_correction_memory(payload.content):
        return []
    topic_key = _topic_key(payload)
    superseded_ids = []
    for memory in temp_memory_storage:
        if memory["id"] == new_memory_id:
            continue
        if _matching_topic_memory(memory, payload, topic_key):
            memory_metadata = memory.setdefault("metadata", {})
            memory_metadata["status"] = "inactive"
            memory_metadata["topic_key"] = topic_key
            memory_metadata["superseded_by"] = new_memory_id
            superseded_ids.append(memory["id"])
    return superseded_ids


def _find_db_superseded_memories(db: Session, payload: MemoryStoreRequest) -> list[Memory]:
    if not _is_correction_memory(payload.content):
        return []
    query = db.query(Memory).filter(Memory.type == payload.type, Memory.source == payload.source)
    if payload.user_id is None:
        query = query.filter(Memory.user_id.is_(None))
    else:
        query = query.filter(Memory.user_id == payload.user_id)
    if payload.team_id is None:
        query = query.filter(Memory.team_id.is_(None))
    else:
        query = query.filter(Memory.team_id == payload.team_id)

    topic_key = _topic_key(payload)
    candidates = []
    for memory in query.all():
        metadata = _metadata_from_json(memory.memory_metadata)
        if metadata.get("status", "active") == "inactive":
            continue
        if metadata.get("topic_key") not in (None, topic_key):
            continue
        candidates.append(memory)
    return candidates


def _mark_db_superseded(db: Session, memories: list[Memory], new_memory_id: str, topic_key: str) -> None:
    for memory in memories:
        metadata = _metadata_from_json(memory.memory_metadata)
        metadata["status"] = "inactive"
        metadata["topic_key"] = topic_key
        metadata["superseded_by"] = new_memory_id
        memory.memory_metadata = _metadata_to_json(metadata)
        memory.updated_at = datetime.now()
    if memories:
        db.commit()


def _query_terms(query: str) -> list[str]:
    query_lower = query.lower()
    terms = re.findall(r"[a-z0-9_.:/-]+", query_lower)
    aliases = {
        "启动": ["run", "start"],
        "运行": ["run", "start"],
        "容器": ["docker", "container"],
        "镜像": ["image"],
        "退出": ["exited", "exit"],
        "停止": ["stop", "stopped"],
        "清理": ["prune", "clean"],
        "列表": ["list", "ls", "ps"],
        "查看": ["list", "ls", "ps"],
    }
    for keyword, replacements in aliases.items():
        if keyword in query_lower:
            terms.extend(replacements)
    return list(dict.fromkeys(term for term in terms if term))


def _cjk_terms(query: str) -> list[str]:
    cjk_text = "".join(re.findall(r"[\u4e00-\u9fff]+", query))
    if len(cjk_text) < 2:
        return [cjk_text] if cjk_text else []
    return [cjk_text[index : index + 2] for index in range(len(cjk_text) - 1)]


def _memory_search_score(memory: dict[str, Any], query: str) -> int:
    haystack = " ".join(
        [
            str(memory.get("content", "")),
            str(memory.get("description", "")),
            " ".join(str(value) for value in (memory.get("metadata") or {}).values()),
        ]
    ).lower()
    query_lower = query.lower()
    if query_lower in haystack:
        return 100

    cjk_score = sum(1 for term in _cjk_terms(query) if term and term in haystack)
    if cjk_score:
        return cjk_score

    terms = _query_terms(query)
    if not terms:
        return 0

    score = sum(1 for term in terms if term in haystack)
    if score == 0:
        return 0

    ascii_terms = re.findall(r"[a-z0-9_.:/-]+", query_lower)
    if ascii_terms and not all(term in haystack for term in ascii_terms):
        return 0
    return score


def _normalize_directory(directory: Optional[str]) -> str:
    return (directory or "").replace("\\", "/").rstrip("/").lower()


def _directory_score(metadata: dict[str, Any], request_directory: Optional[str]) -> float:
    requested = _normalize_directory(request_directory)
    if not requested:
        return 0.0

    candidates = []
    directory = metadata.get("directory")
    if isinstance(directory, str):
        candidates.append(directory)
    directories = metadata.get("directories")
    if isinstance(directories, dict):
        candidates.extend(str(directory) for directory in directories)
    elif isinstance(directories, list):
        candidates.extend(str(directory) for directory in directories)

    best_score = 0.0
    for candidate in candidates:
        stored = _normalize_directory(candidate)
        if not stored:
            continue
        if stored == requested:
            best_score = max(best_score, 0.4)
        elif requested.startswith(f"{stored}/") or stored.startswith(f"{requested}/"):
            best_score = max(best_score, 0.25)
    return best_score


def _explain_result(result: dict[str, Any], query: str, directory: Optional[str] = None) -> list[str]:
    """为单个搜索结果生成排序理由（前 3 个最强因子）"""
    reasons: list[tuple[float, str]] = []
    content = str(result.get("content", ""))
    content_lower = content.lower()
    query_lower = query.lower()
    metadata = result.get("metadata") or {}

    # 前缀匹配
    if content_lower.startswith(query_lower):
        reasons.append((0.9, f"前缀匹配:{query}"))

    # 语义相似度
    similarity = result.get("similarity") or result.get("similarity_score", 0.0)
    if similarity and float(similarity) > 0.01:
        reasons.append((float(similarity), f"语义相似:{float(similarity):.2f}"))

    # 目录匹配
    dir_score = _directory_score(metadata, directory)
    if dir_score > 0:
        reasons.append((dir_score, f"目录匹配:{dir_score:.0%}"))

    # keyword match
    kw_score = _memory_search_score(result, query)
    if kw_score > 0 and kw_score < 100:
        reasons.append((min(kw_score / 100, 0.5), f"关键词匹配:{kw_score}"))

    # 决策优先
    status = metadata.get("status", "active")
    if result.get("type") == "project_decision" and status == "active":
        preferred = metadata.get("preferred_terms", [])
        if preferred:
            reasons.append((0.7, f"飞书决策优先:{','.join(preferred[:2])}"))
    if status == "inactive" or status == "rejected":
        reasons.append((-0.5, "已废弃"))

    # 使用次数
    count = int(metadata.get("count", 0) or 0)
    if count >= 10:
        reasons.append((0.6, f"使用:{count}次"))
    elif count > 0:
        reasons.append((0.3, f"使用:{count}次"))

    # 成功率
    success = int(metadata.get("success_count", 0) or 0)
    failure = int(metadata.get("failure_count", 0) or 0)
    total = success + failure
    if total >= 5:
        rate = success / total * 100
        reasons.append((0.4, f"成功率:{rate:.0f}%"))

    # 时效性
    last_used = metadata.get("last_used_at")
    if last_used:
        try:
            from datetime import datetime
            days = (datetime.now() - datetime.fromisoformat(str(last_used))).days
            if days == 0:
                reasons.append((0.5, "今天使用过"))
            elif days <= 7:
                reasons.append((0.3, f"{days}天前使用"))
        except Exception:
            pass

    # 来源 - 仅飞书决策
    source = result.get("source")
    if source in ("feishu_group", "feishu_doc"):
        chat_id = result.get("team_id") or metadata.get("chat_id")
        extracted = metadata.get("extracted_at") or metadata.get("confirmed_at")
        if extracted:
            reasons.append((0.2, f"来源:飞书群{':' + str(chat_id)[:8] if chat_id else ''}"))

    # 按权重排序，取前 4
    reasons.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in reasons[:4]]


def _sort_and_limit(
    results: list[dict[str, Any]],
    query: str,
    limit: int,
    directory: Optional[str] = None,
) -> list[dict[str, Any]]:
    results.sort(
        key=lambda memory: (
            1 if str(memory.get("content", "")).lower().startswith(query.lower()) else 0,
            _directory_score(memory.get("metadata") or {}, directory),
            _memory_search_score(memory, query),
            (memory.get("metadata") or {}).get("count", 0),
            memory.get("updated_at") or "",
        ),
        reverse=True,
    )
    # 附加可解释性
    for r in results[:limit]:
        r["score_breakdown"] = _explain_result(r, query, directory)
    return results[:limit]


def _search_temp(
    query: str,
    memory_type: Optional[str],
    limit: int,
    directory: Optional[str] = None,
) -> list[dict[str, Any]]:
    results = [
        memory
        for memory in temp_memory_storage
        if _is_active_memory(memory)
        and (not memory_type or memory.get("type") == memory_type)
        and _memory_search_score(memory, query) > 0
    ]
    for memory in results[:limit]:
        memory["hit_count"] = memory.get("hit_count", 0) + 1
    return _sort_and_limit(results, query, limit, directory)


def _search_db(
    db: Session,
    query: str,
    memory_type: Optional[str],
    limit: int,
    directory: Optional[str] = None,
) -> list[dict[str, Any]]:
    vector_results = []
    try:
        vector_memories = retriever.search_memories(db, query, limit, threshold=0.0)
        vector_results = [_memory_to_dict(memory) for memory in vector_memories]
        vector_results = [memory for memory in vector_results if _is_active_memory(memory)]
    except Exception:
        vector_results = []

    seen_ids = {memory["id"] for memory in vector_results}
    db_query = db.query(Memory)
    if memory_type:
        db_query = db_query.filter(Memory.type == memory_type)

    keyword_results = []
    for memory in db_query.all():
        memory_dict = _memory_to_dict(memory)
        if (
            memory_dict["id"] not in seen_ids
            and _is_active_memory(memory_dict)
            and _memory_search_score(memory_dict, query) > 0
        ):
            keyword_results.append(memory_dict)

    results = _sort_and_limit(vector_results + keyword_results, query, limit, directory)
    if results:
        result_ids = [r["id"] for r in results]
        memories_by_id = {m.id: m for m in db.query(Memory).filter(Memory.id.in_(result_ids)).all()}
        for result in results:
            memory = memories_by_id.get(result["id"])
            if memory:
                memory.hit_count = (memory.hit_count or 0) + 1
        db.commit()
    return results


@router.post("/", summary="保存记忆")
def store_memory(memory_data: MemoryStoreRequest, db: Session = Depends(get_db)):
    if not _has_db(db):
        prepared = _prepare_correction_metadata(memory_data, [])
        memory = _memory_from_payload(prepared)
        temp_memory_storage.append(memory)
        if len(temp_memory_storage) > MAX_TEMP_MEMORIES:
            temp_memory_storage[:] = temp_memory_storage[-MAX_TEMP_MEMORIES:]
        superseded_ids = _supersede_temp_memories(prepared, memory["id"])
        if superseded_ids:
            memory["metadata"]["supersedes"] = superseded_ids
        return memory

    superseded_memories = _find_db_superseded_memories(db, memory_data)
    prepared = _prepare_correction_metadata(memory_data, [memory.id for memory in superseded_memories])
    payload = SimpleNamespace(**prepared.model_dump())

    memory = storage.save_memory(db, payload)
    _mark_db_superseded(db, superseded_memories, memory.id, _topic_key(prepared))
    return _memory_to_dict(memory)


@router.post("/extract", summary="提取并存储记忆")
def extract_and_store_memory(memory_data: MemoryCreate, db: Session = Depends(get_db)):
    payload = MemoryStoreRequest(
        content=memory_data.content,
        type=memory_data.type,
        source=memory_data.source,
        user_id=memory_data.user_id,
        team_id=memory_data.team_id,
    )
    return store_memory(payload, db)


@router.get("/list", summary="查看记忆列表")
def list_memories(limit: int = 10, db: Session = Depends(get_db)):
    if not _has_db(db):
        return temp_memory_storage[-limit:]
    memories = db.query(Memory).order_by(Memory.created_at.desc()).limit(limit).all()
    return [_memory_to_dict(memory) for memory in reversed(memories)]


@router.get("/search", summary="搜索记忆")
def search_memories(
    query: str,
    limit: int = 5,
    type: Optional[str] = None,
    directory: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not _has_db(db):
        return _search_temp(query, type, limit, directory)
    return _search_db(db, query, type, limit, directory)


@router.post("/retrieve", summary="检索相关记忆")
def retrieve_memories(request: MemoryRetrieveRequest, db: Session = Depends(get_db)):
    if not _has_db(db):
        return _search_temp(request.query, None, request.top_k or 5)
    return _search_db(db, request.query, None, request.top_k or 5)


@router.get("/{memory_id}", summary="获取单个记忆详情")
def get_memory(memory_id: str, db: Session = Depends(get_db)):
    if not _has_db(db):
        for memory in temp_memory_storage:
            if memory["id"] == memory_id:
                return memory
        raise HTTPException(status_code=404, detail="记忆不存在")

    memory = storage.get_memory_by_id(db, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return _memory_to_dict(memory)


@router.delete("/{memory_id}", summary="软删除记忆")
def delete_memory(memory_id: str, db: Session = Depends(get_db)):
    """软删除：标记为 deleted，7天内可恢复"""
    if not _has_db(db):
        for memory in temp_memory_storage:
            if memory["id"] == memory_id:
                metadata = memory.get("metadata") or {}
                metadata["status"] = "deleted"
                metadata["deleted_at"] = _now_iso()
                memory["metadata"] = metadata
                return {"status": "ok", "message": "记忆已移至回收站"}
        raise HTTPException(status_code=404, detail="记忆不存在")

    db_memory = retriever.get_memory_by_id(db, memory_id) if hasattr(retriever, 'get_memory_by_id') else db.query(Memory).filter(Memory.id == memory_id).first()
    if not db_memory:
        raise HTTPException(status_code=404, detail="记忆不存在")
    metadata = _metadata_from_json(db_memory.memory_metadata)
    metadata["status"] = "deleted"
    metadata["deleted_at"] = _now_iso()
    db_memory.memory_metadata = _metadata_to_json(metadata)
    db.commit()
    return {"status": "ok", "message": "记忆已移至回收站", "memory_id": memory_id}


@router.get("/trash", summary="回收站列表")
def list_trash(limit: int = 50, db: Session = Depends(get_db)):
    """查看已软删除的记忆"""
    if not _has_db(db):
        items = [m for m in temp_memory_storage if (m.get("metadata") or {}).get("status") == "deleted"]
        return items[:limit]

    results = db.query(Memory).all()
    trash = []
    for m in results:
        meta = _metadata_from_json(m.memory_metadata)
        if meta.get("status") == "deleted":
            trash.append(_memory_to_dict(m))
    return trash[:limit]


@router.post("/{memory_id}/restore", summary="恢复记忆")
def restore_memory(memory_id: str, db: Session = Depends(get_db)):
    """从回收站恢复记忆"""
    if not _has_db(db):
        for memory in temp_memory_storage:
            if memory["id"] == memory_id:
                metadata = memory.get("metadata") or {}
                metadata.pop("status", None)
                metadata.pop("deleted_at", None)
                memory["metadata"] = metadata
                return {"status": "ok", "message": "记忆已恢复"}
        raise HTTPException(status_code=404, detail="记忆不存在")

    db_memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not db_memory:
        raise HTTPException(status_code=404, detail="记忆不存在")
    metadata = _metadata_from_json(db_memory.memory_metadata)
    metadata.pop("status", None)
    metadata.pop("deleted_at", None)
    db_memory.memory_metadata = _metadata_to_json(metadata)
    db.commit()
    return {"status": "ok", "message": "记忆已恢复", "memory_id": memory_id}


@router.delete("/", summary="清空所有记忆")
def clear_all_memories(db: Session = Depends(get_db)):
    """清空所有记忆，包括关系库和向量库"""
    if not _has_db(db):
        count = len(temp_memory_storage)
        temp_memory_storage.clear()
        return {"status": "ok", "message": f"已清空 {count} 条临时记忆", "deleted_count": count}

    # 统计删除数量
    memories = db.query(Memory).all()
    count = len(memories)

    if count == 0:
        return {"status": "ok", "message": "记忆库为空", "deleted_count": 0}

    # 删除关系库中的所有记忆
    try:
        db.query(DecisionMemory).delete()
        db.query(Memory).delete()
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除关系库数据失败: {str(e)}")

    # 删除向量库中的所有记忆
    vector_deleted = 0
    try:
        from db.vector.client import vector_client
        # 获取所有记忆ID用于向量库删除
        memory_ids = [memory.id for memory in memories]
        for memory_id in memory_ids:
            try:
                vector_client.delete_memory(memory_id)
                vector_deleted += 1
            except Exception:
                pass
    except Exception:
        pass

    return {
        "status": "ok",
        "message": f"已清空 {count} 条记忆（关系库: {count} 条，向量库: {vector_deleted} 条）",
        "deleted_count": count,
        "vector_deleted": vector_deleted
    }
