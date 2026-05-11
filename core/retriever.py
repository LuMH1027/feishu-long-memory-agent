from sqlalchemy.orm import Session
import os
from datetime import datetime
from db.vector.client import vector_client
from core.utils.embedding import get_embedding
from db.relational.models import Memory


def _safe_lower(value: str) -> str:
    return (value or "").lower()


def _get_memory_metadata(memory: Memory) -> dict:
    """Return CLI metadata from dynamic search attributes or future model fields."""
    cli_metadata = getattr(memory, "cli_metadata", None)
    if isinstance(cli_metadata, dict):
        return cli_metadata

    metadata = getattr(memory, "metadata", None)
    if isinstance(metadata, dict):
        return metadata

    return {}


def is_cli_prefix_match(query: str, memory: Memory) -> bool:
    """Return whether the memory command starts with the user's query."""
    return _safe_lower(getattr(memory, "content", "")).startswith(_safe_lower(query))


def calculate_cli_relevance_score(query: str, memory: Memory) -> float:
    """计算CLI命令场景下的相关性得分"""
    base_score = getattr(memory, "similarity_score", 0.0) or 0.0
    metadata = _get_memory_metadata(memory)

    try:
        count = int(metadata.get("count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    count_score = min(count * 0.05, 0.3)

    recency_score = 0.0
    days_ago = 0
    last_used = metadata.get("last_used_at")
    if last_used:
        try:
            last_used_time = datetime.fromisoformat(last_used)
            days_ago = max(0, (datetime.now() - last_used_time).days)
            recency_score = min(max(0, 0.2 - (days_ago * 0.01)), 0.2)
        except (TypeError, ValueError):
            pass

    # T3-2c: 记忆衰减 — 不使用时间越长，自然沉底
    import math
    decay_lambda = 0.02  # 每天衰减 2%
    decay_score = max(0, 0.3 * math.exp(-decay_lambda * days_ago)) if last_used else 0.0

    # T3-2a: dismiss 降权
    dismiss_count = int(metadata.get("dismiss_count", 0) or 0)
    dismiss_penalty = min(dismiss_count * 0.15, 0.5)

    prefix_score = 0.2 if is_cli_prefix_match(query, memory) else 0.0

    try:
        success_count = int(metadata.get("success_count", 0) or 0)
        failure_count = int(metadata.get("failure_count", 0) or 0)
    except (TypeError, ValueError):
        success_count = 0
        failure_count = 0
    total_runs = success_count + failure_count
    success_score = (success_count / total_runs) * 0.2 if total_runs else 0.0

    return base_score + count_score + recency_score + decay_score + prefix_score + success_score - dismiss_penalty


def _search_sort_key(query: str, memory: Memory):
    if getattr(memory, "type", None) != "cli_command":
        return (0, getattr(memory, "similarity_score", 0.0) or 0.0)

    # Prefix matching is the strongest CLI signal, then weighted relevance.
    return (
        1 if is_cli_prefix_match(query, memory) else 0,
        calculate_cli_relevance_score(query, memory),
    )


def search_memories(db: Session, query: str, top_k: int = None, threshold: float = None):
    """搜索相关记忆"""
    if top_k is None:
        top_k = int(os.getenv("RETRIEVE_TOP_K", 5))
    if threshold is None:
        threshold = float(os.getenv("SIMILARITY_THRESHOLD", 0.7))
    
    # 向量检索
    query_embedding = get_embedding(query)
    vector_results = vector_client.search_memories(
        query_embedding=query_embedding,
        top_k=top_k,
        threshold=threshold
    )
    
    # 获取详细信息
    memory_ids = [result["id"] for result in vector_results]
    if not memory_ids:
        return []

    vector_result_map = {result["id"]: result for result in vector_results}
    memories = db.query(Memory).filter(Memory.id.in_(memory_ids)).all()
    
    # 按照检索结果补充动态搜索属性
    memory_map = {mem.id: mem for mem in memories}
    sorted_memories = []
    for mem_id in memory_ids:
        if mem_id not in memory_map:
            continue
        memory = memory_map[mem_id]
        vector_result = vector_result_map.get(mem_id, {})
        memory.similarity_score = vector_result.get("similarity", 0.0)
        memory.cli_metadata = vector_result.get("metadata") or {}
        sorted_memories.append(memory)

    sorted_memories.sort(
        key=lambda memory: _search_sort_key(query, memory),
        reverse=True,
    )
    
    # 更新命中次数
    for memory in sorted_memories:
        memory.hit_count += 1
    db.commit()
    
    return sorted_memories
