# 阶段1：后端API接口开发
## 开发目标
完成CLI相关的两个核心API接口，为CLI功能提供后端支撑

## 修改文件
`backend/routers/cli.py`

---

## 1.1 实现命令记录接口 `/api/v1/cli/command/record`
### 功能说明
接收CLI端上报的命令，自动存储或更新到记忆库中

### 代码实现
```python
from pydantic import BaseModel
from datetime import datetime
from core.storage import memory_storage

class CommandRecordRequest(BaseModel):
    command: str
    count: int
    shell: str
    directory: Optional[str] = None
    exit_code: Optional[int] = None

@cli_router.post("/command/record", summary="记录CLI命令")
async def record_command(request: CommandRecordRequest):
    """记录用户执行的CLI命令，用于后续智能推荐"""
    # 检查是否已有相同命令的记忆
    existing = await memory_storage.search(
        query=request.command,
        memory_type="cli_command",
        limit=1
    )
    
    if existing:
        # 更新使用次数
        memory = existing[0]
        memory.metadata["count"] = memory.metadata.get("count", 0) + request.count
        memory.metadata["last_used_at"] = datetime.now().isoformat()
        await memory_storage.update(memory.id, memory)
    else:
        # 创建新记忆
        await memory_storage.create(
            content=request.command,
            memory_type="cli_command",
            description=f"{request.shell}命令",
            metadata={
                "count": request.count,
                "shell": request.shell,
                "directory": request.directory,
                "first_used_at": datetime.now().isoformat(),
                "last_used_at": datetime.now().isoformat()
            }
        )
    
    return {"status": "success"}
```

### 测试用例
```powershell
# 测试接口是否可用
curl -X POST http://localhost:8000/api/v1/cli/command/record `
  -H "Content-Type: application/json" `
  -d '{\"command\": \"docker ps -a --filter status=running\", \"count\": 3, \"shell\": \"powershell\"}'

# 预期输出：{"status":"success"}

# 验证数据是否存入数据库
curl -X GET "http://localhost:8000/api/v1/memory/search?query=docker&type=cli_command"
# 预期输出：包含刚才存入的docker命令
```

---

## 1.2 实现命令推荐接口 `/api/v1/cli/command/suggest`
### 功能说明
根据用户输入的部分命令，智能推荐完整命令

### 代码实现
```python
class CommandSuggestRequest(BaseModel):
    partial_command: str
    directory: Optional[str] = None
    shell: str = "powershell"

@cli_router.post("/command/suggest", summary="智能推荐命令")
async def suggest_command(request: CommandSuggestRequest):
    """根据用户输入的部分命令，智能推荐完整命令"""
    # 语义搜索相关命令
    results = await memory_storage.search(
        query=request.partial_command,
        memory_type="cli_command",
        limit=10
    )
    
    # 按使用频率排序
    results.sort(key=lambda x: x.metadata.get("count", 0), reverse=True)
    
    return {
        "suggestions": [
            {
                "command": item.content,
                "description": item.description,
                "count": item.metadata.get("count", 0),
                "last_used": item.metadata.get("last_used_at")
            }
            for item in results
        ]
    }
```

### 测试用例
```powershell
# 测试推荐接口
curl -X POST http://localhost:8000/api/v1/cli/command/suggest `
  -H "Content-Type: application/json" `
  -d '{\"partial_command\": \"docker\", \"shell\": \"powershell\"}'

# 预期输出：
# {"suggestions": [{"command": "docker ps -a --filter status=running", "description": "powershell命令", "count": 3, ...}]}
```

## 完成标准
✅ 两个接口都能正常调用，数据能正确存入数据库，推荐结果符合预期
