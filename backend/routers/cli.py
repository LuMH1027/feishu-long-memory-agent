from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import json
import uuid
from pathlib import PurePath
from backend.dependencies import get_db
from core.command_parser import parse_command, pattern_text
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
            _track_directory(metadata, request.directory, request.count)
            _attach_command_pattern(metadata, request.command)
            _track_exit_code(metadata, request.exit_code)
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
            _track_directory(metadata, request.directory, request.count)
            _attach_command_pattern(metadata, request.command)
            _track_exit_code(metadata, request.exit_code)
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
        _track_directory(existing["metadata"], request.directory, request.count)
        _attach_command_pattern(existing["metadata"], request.command)
        _track_exit_code(existing["metadata"], request.exit_code)
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
                "directories": {request.directory: request.count} if request.directory else {},
                "command_pattern": parse_command(request.command),
                "first_used_at": datetime.now().isoformat(),
                "last_used_at": datetime.now().isoformat()
            }
        }
        _track_exit_code(new_command["metadata"], request.exit_code)
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


def _normalize_directory(directory: Optional[str]) -> str:
    return (directory or "").replace("\\", "/").rstrip("/").lower()


def _directory_score(stored_directory: Optional[str], request_directory: Optional[str]) -> float:
    stored = _normalize_directory(stored_directory)
    requested = _normalize_directory(request_directory)
    if not stored or not requested:
        return 0.0
    if stored == requested:
        return 0.4
    if requested.startswith(f"{stored}/") or stored.startswith(f"{requested}/"):
        return 0.25

    stored_name = PurePath(stored).name
    requested_name = PurePath(requested).name
    if stored_name and stored_name == requested_name:
        return 0.1
    return 0.0


def _metadata_directory_score(metadata: dict, request_directory: Optional[str]) -> float:
    best_score = _directory_score(metadata.get("directory"), request_directory)
    directories = metadata.get("directories")
    if isinstance(directories, dict):
        for directory in directories:
            best_score = max(best_score, _directory_score(directory, request_directory))
    elif isinstance(directories, list):
        for directory in directories:
            best_score = max(best_score, _directory_score(directory, request_directory))
    return best_score


def _track_directory(metadata: dict, directory: Optional[str], count: int) -> None:
    if not directory:
        return
    metadata["directory"] = directory
    directories = metadata.get("directories")
    if not isinstance(directories, dict):
        directories = {}
    directories[directory] = int(directories.get(directory, 0) or 0) + count
    metadata["directories"] = directories


def _track_exit_code(metadata: dict, exit_code: Optional[int]) -> None:
    if exit_code is None:
        return
    metadata["exit_code"] = exit_code
    metadata["last_exit_code"] = exit_code
    if exit_code == 0:
        metadata["success_count"] = int(metadata.get("success_count", 0) or 0) + 1
    else:
        metadata["failure_count"] = int(metadata.get("failure_count", 0) or 0) + 1
        metadata["last_failed_at"] = datetime.now().isoformat()


def _success_score(metadata: dict) -> float:
    success_count = int(metadata.get("success_count", 0) or 0)
    failure_count = int(metadata.get("failure_count", 0) or 0)
    total = success_count + failure_count
    if total == 0:
        return 0.0
    return (success_count / total) * 0.2


def _attach_command_pattern(metadata: dict, command: str) -> None:
    metadata["command_pattern"] = parse_command(command)


def _command_haystack(command: str, metadata: dict) -> str:
    pattern = metadata.get("command_pattern")
    pattern_part = pattern_text(pattern) if isinstance(pattern, dict) else ""
    return f"{command} {pattern_part}".lower()


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


def _matches_command_memory(command: str, metadata: dict, partial_command: str) -> bool:
    haystack = _command_haystack(command, metadata)
    return all(token in haystack for token in partial_command.lower().split())


def _suggestion_sort_key(memory: Memory, request: CommandSuggestRequest):
    metadata = _metadata_from_json(memory.memory_metadata)
    return (
        1 if memory.content.lower().startswith(request.partial_command.lower()) else 0,
        _metadata_directory_score(metadata, request.directory),
        _success_score(metadata),
        int(metadata.get("count", 0) or 0),
        metadata.get("last_used_at") or "",
    )


def _temp_suggestion_sort_key(item: dict, request: CommandSuggestRequest):
    metadata = item.get("metadata") or {}
    command = item.get("command", "")
    return (
        1 if command.lower().startswith(request.partial_command.lower()) else 0,
        _metadata_directory_score(metadata, request.directory),
        _success_score(metadata),
        int(metadata.get("count", 0) or 0),
        metadata.get("last_used_at") or "",
    )


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
            if _matches_command_memory(memory.content, _metadata_from_json(memory.memory_metadata), request.partial_command)
        ]
        results.sort(key=lambda memory: _suggestion_sort_key(memory, request), reverse=True)
        return {"suggestions": [_command_to_suggestion(memory) for memory in results]}

    # 搜索相关命令
    results = [
        item for item in temp_command_storage 
        if _matches_command_memory(item["command"], item.get("metadata") or {}, request.partial_command)
    ]
    
    # 按使用频率排序
    results.sort(key=lambda item: _temp_suggestion_sort_key(item, request), reverse=True)
    
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
