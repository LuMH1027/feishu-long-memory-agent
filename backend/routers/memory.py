from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.schemas.memory import MemoryCreate, MemoryResponse, MemoryRetrieveRequest
from core import storage, retriever

router = APIRouter()

@router.post("/extract", response_model=MemoryResponse)
def extract_and_store_memory(memory_data: MemoryCreate, db: Session = Depends(get_db)):
    """提取并存储记忆"""
    memory = storage.save_memory(db, memory_data)
    return memory

@router.post("/retrieve", response_model=list[MemoryResponse])
def retrieve_memories(request: MemoryRetrieveRequest, db: Session = Depends(get_db)):
    """检索相关记忆"""
    memories = retriever.search_memories(db, request.query, request.top_k, request.threshold)
    return memories

@router.get("/{memory_id}", response_model=MemoryResponse)
def get_memory(memory_id: str, db: Session = Depends(get_db)):
    """获取单个记忆详情"""
    memory = storage.get_memory_by_id(db, memory_id)
    return memory

@router.delete("/{memory_id}")
def delete_memory(memory_id: str, db: Session = Depends(get_db)):
    """删除记忆"""
    storage.delete_memory(db, memory_id)
    return {"status": "ok", "message": "记忆删除成功"}
