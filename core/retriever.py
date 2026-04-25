from sqlalchemy.orm import Session
import os
from db.vector.client import vector_client
from core.utils.embedding import get_embedding
from db.relational.models import Memory

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
    memories = db.query(Memory).filter(Memory.id.in_(memory_ids)).all()
    
    # 按照检索结果排序
    memory_map = {mem.id: mem for mem in memories}
    sorted_memories = [memory_map[mem_id] for mem_id in memory_ids if mem_id in memory_map]
    
    # 更新命中次数
    for memory in sorted_memories:
        memory.hit_count += 1
    db.commit()
    
    return sorted_memories
