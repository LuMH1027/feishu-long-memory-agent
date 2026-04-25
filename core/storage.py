from sqlalchemy.orm import Session
import uuid
from datetime import datetime, timedelta
import os
from db.relational.models import Memory
from db.vector.client import vector_client
from core.utils.embedding import get_embedding

def save_memory(db: Session, memory_data):
    """保存记忆到关系库和向量库"""
    memory_id = uuid.uuid4().hex[:16]
    
    # 保存到关系库
    db_memory = Memory(
        id=memory_id,
        content=memory_data.content,
        type=memory_data.type,
        source=memory_data.source,
        user_id=memory_data.user_id,
        team_id=memory_data.team_id,
        expire_at=datetime.utcnow() + timedelta(days=int(os.getenv("DEFAULT_MEMORY_EXPIRE_DAYS", 30)))
    )
    db.add(db_memory)
    db.commit()
    db.refresh(db_memory)
    
    # 保存到向量库
    embedding = get_embedding(memory_data.content)
    vector_client.add_memory(
        memory_id=memory_id,
        content=memory_data.content,
        embedding=embedding,
        metadata={
            "type": memory_data.type,
            "source": memory_data.source,
            "user_id": memory_data.user_id,
            "team_id": memory_data.team_id
        }
    )
    
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
        vector_client.delete_memory(memory_id)
    return True
