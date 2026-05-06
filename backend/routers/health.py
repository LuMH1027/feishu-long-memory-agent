"""健康检查路由"""
import logging
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from db.relational.models import Memory, DecisionMemory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["健康检查"])


def _check_database(db: Session) -> dict[str, Any]:
    """检查数据库状态"""
    try:
        # 尝试查询
        memory_count = db.query(Memory).count()
        decision_count = db.query(DecisionMemory).count()

        return {
            "status": "ok",
            "memory_count": memory_count,
            "decision_count": decision_count,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def _check_vector_db() -> dict[str, Any]:
    """检查向量数据库状态"""
    try:
        from db.vector.client import vector_client

        # 尝试获取集合信息
        collection = vector_client.collection
        count = collection.count()

        return {
            "status": "ok",
            "collection_name": collection.name,
            "vector_count": count,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def _check_embedding() -> dict[str, Any]:
    """检查Embedding服务状态"""
    try:
        from core.utils.embedding import get_embedding

        # 尝试获取embedding
        test_text = "health check"
        embedding = get_embedding(test_text)

        return {
            "status": "ok",
            "model": os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002"),
            "dimension": len(embedding),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/", summary="基础健康检查")
def health_check():
    """基础健康检查接口"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "enterprise-memory-engine"
    }


@router.get("/detailed", summary="详细健康检查")
def detailed_health_check(db: Session = Depends(get_db)):
    """详细健康检查接口，包含各组件状态"""
    # 检查数据库
    db_status = _check_database(db)

    # 检查向量库
    vector_status = _check_vector_db()

    # 检查Embedding服务
    embedding_status = _check_embedding()

    # 判断整体状态
    overall_status = "ok"
    if db_status["status"] != "ok":
        overall_status = "degraded"
    if vector_status["status"] != "ok":
        overall_status = "degraded"
    if embedding_status["status"] != "ok":
        overall_status = "degraded"

    return {
        "status": overall_status,
        "timestamp": datetime.now().isoformat(),
        "components": {
            "database": db_status,
            "vector_db": vector_status,
            "embedding": embedding_status,
        }
    }


@router.get("/database", summary="数据库健康检查")
def database_health_check(db: Session = Depends(get_db)):
    """数据库健康检查接口"""
    return _check_database(db)


@router.get("/vector", summary="向量库健康检查")
def vector_health_check():
    """向量库健康检查接口"""
    return _check_vector_db()


@router.get("/embedding", summary="Embedding服务健康检查")
def embedding_health_check():
    """Embedding服务健康检查接口"""
    return _check_embedding()
