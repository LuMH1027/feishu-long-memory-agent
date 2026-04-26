from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from backend.dependencies import get_db

cli_router = APIRouter(prefix="/cli", tags=["CLI"])

# 临时内存存储，用于接口测试
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
    # 检查是否已有相同命令的记忆
    existing = next((item for item in temp_command_storage if item["command"] == request.command), None)
    
    if existing:
        # 更新使用次数
        existing["count"] += request.count
        existing["last_used_at"] = datetime.now().isoformat()
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

@cli_router.post("/command/suggest", summary="智能推荐命令", response_model=dict[str, List[CommandSuggestion]])
async def suggest_command(request: CommandSuggestRequest, db: Session = Depends(get_db)):
    """根据用户输入的部分命令，智能推荐完整命令"""
    # 搜索相关命令
    results = [
        item for item in temp_command_storage 
        if request.partial_command.lower() in item["command"].lower()
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
