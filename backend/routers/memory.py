from datetime import datetime
import json
import re
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.schemas.memory import MemoryCreate, MemoryRetrieveRequest
from db.relational.models import Memory

router = APIRouter()

# Unit-test fallback only. Real API requests receive a SQLAlchemy session.
temp_memory_storage: list[dict[str, Any]] = []


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
    return {
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


def _memory_from_payload(payload: MemoryStoreRequest) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": __import__("uuid").uuid4().hex[:16],
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


def _sort_and_limit(results: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    results.sort(
        key=lambda memory: (
            1 if str(memory.get("content", "")).lower().startswith(query.lower()) else 0,
            _memory_search_score(memory, query),
            (memory.get("metadata") or {}).get("count", 0),
            memory.get("updated_at") or "",
        ),
        reverse=True,
    )
    return results[:limit]


def _search_temp(query: str, memory_type: Optional[str], limit: int) -> list[dict[str, Any]]:
    results = [
        memory
        for memory in temp_memory_storage
        if (not memory_type or memory.get("type") == memory_type) and _memory_search_score(memory, query) > 0
    ]
    for memory in results[:limit]:
        memory["hit_count"] = memory.get("hit_count", 0) + 1
    return _sort_and_limit(results, query, limit)


def _search_db(db: Session, query: str, memory_type: Optional[str], limit: int) -> list[dict[str, Any]]:
    vector_results = []
    try:
        from core import retriever

        vector_memories = retriever.search_memories(db, query, limit, threshold=0.0)
        vector_results = [_memory_to_dict(memory) for memory in vector_memories]
    except Exception:
        vector_results = []

    seen_ids = {memory["id"] for memory in vector_results}
    db_query = db.query(Memory)
    if memory_type:
        db_query = db_query.filter(Memory.type == memory_type)

    keyword_results = []
    for memory in db_query.all():
        memory_dict = _memory_to_dict(memory)
        if memory_dict["id"] not in seen_ids and _memory_search_score(memory_dict, query) > 0:
            keyword_results.append(memory_dict)

    results = _sort_and_limit(vector_results + keyword_results, query, limit)
    for result in results:
        memory = db.query(Memory).filter(Memory.id == result["id"]).first()
        if memory:
            memory.hit_count = (memory.hit_count or 0) + 1
    db.commit()
    return results


@router.post("/", summary="保存记忆")
def store_memory(memory_data: MemoryStoreRequest, db: Session = Depends(get_db)):
    if not _has_db(db):
        memory = _memory_from_payload(memory_data)
        temp_memory_storage.append(memory)
        return memory

    payload = SimpleNamespace(**memory_data.model_dump())
    from core import storage

    memory = storage.save_memory(db, payload)
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
def search_memories(query: str, limit: int = 5, type: Optional[str] = None, db: Session = Depends(get_db)):
    if not _has_db(db):
        return _search_temp(query, type, limit)
    return _search_db(db, query, type, limit)


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

    from core import storage

    memory = storage.get_memory_by_id(db, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return _memory_to_dict(memory)


@router.delete("/{memory_id}", summary="删除记忆")
def delete_memory(memory_id: str, db: Session = Depends(get_db)):
    if not _has_db(db):
        before_count = len(temp_memory_storage)
        temp_memory_storage[:] = [memory for memory in temp_memory_storage if memory["id"] != memory_id]
        if len(temp_memory_storage) == before_count:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"status": "ok", "message": "记忆删除成功"}

    from core import storage

    if not storage.get_memory_by_id(db, memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    storage.delete_memory(db, memory_id)
    return {"status": "ok", "message": "记忆删除成功"}
