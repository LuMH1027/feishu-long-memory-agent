from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import json
import uuid
from backend.dependencies import get_db
from db.relational.models import Memory

cli_router = APIRouter(prefix="/cli", tags=["CLI"])

# Unit-test fallback only. Real API requests receive a SQLAlchemy session.
temp_command_storage = []

class CommandRecordRequest(BaseModel):
    command: str
    count: int
    shell: str
    directory: Optional[str] = None
    exit_code: Optional[int] = None

@cli_router.post("/command/record", summary="记录CLI命令")
async def record_command(request: CommandRecordRequest, db: Session = Depends(get_db)):
    """记录用户执行的CLI命令，用于后续智能推荐"""
    if _has_db(db):
        now = datetime.now().isoformat()
        existing = db.query(Memory).filter(Memory.type == "cli_command", Memory.content == request.command).first()
        if existing:
            metadata = _metadata_from_json(existing.memory_metadata)
            metadata["count"] = int(metadata.get("count", 0) or 0) + request.count
            metadata["last_used_at"] = now
            metadata["shell"] = request.shell
            metadata["directory"] = request.directory
            if request.exit_code is not None:
                metadata["exit_code"] = request.exit_code
            existing.description = existing.description or f"{request.shell}命令"
            existing.memory_metadata = _metadata_to_json(metadata)
            existing.updated_at = datetime.now()
        else:
            metadata = {
                "count": request.count,
                "shell": request.shell,
                "directory": request.directory,
                "first_used_at": now,
                "last_used_at": now,
            }
            if request.exit_code is not None:
                metadata["exit_code"] = request.exit_code
            db.add(
                Memory(
                    id=uuid.uuid4().hex[:16],
                    content=request.command,
                    type="cli_command",
                    source="cli",
                    description=f"{request.shell}命令",
                    memory_metadata=_metadata_to_json(metadata),
                )
            )
        db.commit()
        return {"status": "success"}

    # 检查是否已有相同命令的记忆
    existing = next((item for item in temp_command_storage if item["command"] == request.command), None)
    
    if existing:
        # 更新使用次数
        existing["metadata"]["count"] += request.count
        existing["metadata"]["last_used_at"] = datetime.now().isoformat()
    else:
        # 创建新记忆
        new_command = {
            "id": len(temp_command_storage) + 1,
            "command": request.command,
            "type": "cli_command",
            "description": f"{request.shell}命令",
            "metadata": {
                "count": request.count,
                "shell": request.shell,
                "directory": request.directory,
                "first_used_at": datetime.now().isoformat(),
                "last_used_at": datetime.now().isoformat()
            }
        }
        temp_command_storage.append(new_command)
    
    return {"status": "success"}

class CommandSuggestRequest(BaseModel):
    partial_command: str
    directory: Optional[str] = None
    shell: str = "powershell"

class CommandSuggestion(BaseModel):
    command: str
    description: str
    count: int
    last_used: Optional[str]


def _has_db(db) -> bool:
    return hasattr(db, "query") and hasattr(db, "add")


def _metadata_to_json(metadata: dict) -> str:
    return json.dumps(metadata or {}, ensure_ascii=False)


def _metadata_from_json(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _command_to_suggestion(memory: Memory) -> dict:
    metadata = _metadata_from_json(memory.memory_metadata)
    return {
        "command": memory.content,
        "description": memory.description or f"{metadata.get('shell', 'shell')}命令",
        "count": metadata.get("count", 0),
        "last_used": metadata.get("last_used_at"),
    }


def _matches_partial_command(command: str, partial_command: str) -> bool:
    command_lower = command.lower()
    return all(token in command_lower for token in partial_command.lower().split())


@cli_router.get("/command/list", summary="查看已记录CLI命令")
async def list_commands(limit: int = 10, db: Session = Depends(get_db)):
    """返回最近记录的CLI命令，用于CLI列表视图兜底展示。"""
    if _has_db(db):
        memories = (
            db.query(Memory)
            .filter(Memory.type == "cli_command")
            .order_by(Memory.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": memory.id,
                "command": memory.content,
                "type": memory.type,
                "description": memory.description or "CLI命令",
                "metadata": _metadata_from_json(memory.memory_metadata),
            }
            for memory in memories
        ]
    return temp_command_storage[-limit:]


@cli_router.post("/command/suggest", summary="智能推荐命令", response_model=dict[str, List[CommandSuggestion]])
async def suggest_command(request: CommandSuggestRequest, db: Session = Depends(get_db)):
    """根据用户输入的部分命令，智能推荐完整命令"""
    if _has_db(db):
        memories = db.query(Memory).filter(Memory.type == "cli_command").all()
        results = [
            memory
            for memory in memories
            if _matches_partial_command(memory.content, request.partial_command)
        ]
        results.sort(key=lambda memory: _metadata_from_json(memory.memory_metadata).get("count", 0), reverse=True)
        return {"suggestions": [_command_to_suggestion(memory) for memory in results]}

    # 搜索相关命令
    results = [
        item for item in temp_command_storage 
        if _matches_partial_command(item["command"], request.partial_command)
    ]
    
    # 按使用频率排序
    results.sort(key=lambda x: x["metadata"]["count"], reverse=True)
    
    return {
        "suggestions": [
            {
                "command": item["command"],
                "description": item["description"],
                "count": item["metadata"]["count"],
                "last_used": item["metadata"]["last_used_at"]
            }
            for item in results
        ]
    }
