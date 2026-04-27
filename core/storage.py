from sqlalchemy.orm import Session
import uuid
from datetime import datetime, timedelta
import os
import json
from db.relational.models import Memory


def get_embedding(text: str):
    from core.utils.embedding import get_embedding as _get_embedding

    return _get_embedding(text)


class _VectorClientProxy:
    def add_memory(self, **kwargs):
        from db.vector.client import vector_client

        return vector_client.add_memory(**kwargs)

    def delete_memory(self, memory_id: str):
        from db.vector.client import vector_client

        return vector_client.delete_memory(memory_id)


vector_client = _VectorClientProxy()


def _json_dumps(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _memory_metadata(memory_data) -> dict:
    metadata = getattr(memory_data, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    return {}


def save_memory(db: Session, memory_data):
    """保存记忆到关系库和向量库"""
    memory_id = uuid.uuid4().hex[:16]
    metadata = _memory_metadata(memory_data)
    
    # 保存到关系库
    db_memory = Memory(
        id=memory_id,
        content=memory_data.content,
        type=memory_data.type,
        source=memory_data.source,
        description=getattr(memory_data, "description", None),
        memory_metadata=_json_dumps(metadata),
        user_id=memory_data.user_id,
        team_id=memory_data.team_id,
        expire_at=datetime.utcnow() + timedelta(days=int(os.getenv("DEFAULT_MEMORY_EXPIRE_DAYS", 30)))
    )
    db.add(db_memory)
    db.commit()
    db.refresh(db_memory)
    
    # 保存到向量库
    try:
        embedding = get_embedding(memory_data.content)
        vector_client.add_memory(
            memory_id=memory_id,
            content=memory_data.content,
            embedding=embedding,
            metadata={
                "type": memory_data.type,
                "source": memory_data.source,
                "user_id": memory_data.user_id,
                "team_id": memory_data.team_id,
                **metadata,
            }
        )
    except Exception:
        # Relational storage is the source of truth; vector search can be restored later.
        pass
    
    return db_memory

def get_memory_by_id(db: Session, memory_id: str):
    """根据ID获取记忆"""
    return db.query(Memory).filter(Memory.id == memory_id).first()

def delete_memory(db: Session, memory_id: str):
    """删除记忆"""
    db_memory = get_memory_by_id(db, memory_id)
    if db_memory:
        db.delete(db_memory)
        db.commit()
        try:
            vector_client.delete_memory(memory_id)
        except Exception:
            pass
    return True
