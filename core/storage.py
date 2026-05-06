from sqlalchemy.orm import Session
import uuid
from datetime import datetime, timedelta
import os
import json
import logging
from db.relational.models import Memory

# 获取日志器
logger = logging.getLogger(__name__)


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

    logger.info(f"开始保存记忆: id={memory_id}, type={memory_data.type}, source={memory_data.source}")

    # 保存到关系库
    try:
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
        logger.info(f"关系库保存成功: id={memory_id}")
    except Exception as e:
        logger.error(f"关系库保存失败: id={memory_id}, error={str(e)}")
        db.rollback()
        raise

    # 保存到向量库
    vector_status = "skipped"
    try:
        embedding = get_embedding(memory_data.content)
        # ChromaDB metadata 只接受 str/int/float/bool，过滤掉 None/list/dict
        raw_meta = {
            "type": memory_data.type,
            "source": memory_data.source,
            "user_id": memory_data.user_id,
            "team_id": memory_data.team_id,
            **metadata,
        }
        vector_meta = {}
        for k, v in raw_meta.items():
            if v is None:
                vector_meta[k] = ""
            elif isinstance(v, (list, dict)):
                vector_meta[k] = json.dumps(v, ensure_ascii=False)
            elif isinstance(v, (str, int, float, bool)):
                vector_meta[k] = v
            else:
                vector_meta[k] = str(v)
        vector_client.add_memory(
            memory_id=memory_id,
            content=memory_data.content,
            embedding=embedding,
            metadata=vector_meta,
        )
        vector_status = "ok"
        logger.info(f"向量库保存成功: id={memory_id}")
    except Exception as e:
        # Relational storage is the source of truth; vector search can be restored later.
        vector_status = "error"
        logger.warning(f"向量库保存失败（降级为关系库）: id={memory_id}, error={str(e)}")

    # 记录向量库状态到metadata
    db_memory.memory_metadata = _json_dumps({**metadata, "vector_status": vector_status})
    db.commit()

    return db_memory

def get_memory_by_id(db: Session, memory_id: str):
    """根据ID获取记忆"""
    return db.query(Memory).filter(Memory.id == memory_id).first()

def delete_memory(db: Session, memory_id: str):
    """删除记忆"""
    logger.info(f"开始删除记忆: id={memory_id}")

    db_memory = get_memory_by_id(db, memory_id)
    if not db_memory:
        logger.warning(f"记忆不存在: id={memory_id}")
        return False

    try:
        db.delete(db_memory)
        db.commit()
        logger.info(f"关系库删除成功: id={memory_id}")
    except Exception as e:
        logger.error(f"关系库删除失败: id={memory_id}, error={str(e)}")
        db.rollback()
        raise

    # 删除向量库
    try:
        vector_client.delete_memory(memory_id)
        logger.info(f"向量库删除成功: id={memory_id}")
    except Exception as e:
        logger.warning(f"向量库删除失败: id={memory_id}, error={str(e)}")

    return True
