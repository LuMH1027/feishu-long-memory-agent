# 方向A：CLI高频命令与工作流记忆 开发详细指南

## 一、功能总览与目标
### 1.1 核心目标
为开发者提供命令行场景下的智能记忆助手，实现：
- 自动/手动记录高频使用的复杂命令
- 语义化搜索历史命令，无需记忆完整参数
- 智能补全和推荐适合当前上下文的命令
- 跨设备、跨终端同步命令记忆
- 工作流模板存储与一键复用

### 1.2 适用场景
- 记不住复杂的Docker/K8s命令参数
- 需要频繁切换多环境的部署命令
- 团队共享常用运维/开发命令模板
- 新员工快速上手团队常用命令集

## 二、当前已有框架梳理
当前项目已经完成了方向A的基础骨架，具体包括：
| 模块 | 文件路径 | 已实现功能 |
|------|----------|------------|
| CLI入口 | `cli/main.py` | 核心命令框架：`memorize`/`search`/`list`/`clear`/`configure` |
| 后端API | `backend/routers/cli.py` | 接口骨架：`/api/v1/cli/command/suggest`/`/api/v1/cli/command/record` |
| 数据模型 | `db/relational/models.py` | `Memory`表已预留`cli_command`类型，支持命令结构化存储 |
| 核心引擎 | `core/storage.py`/`core/retriever.py` | 通用记忆存储与检索能力 |

---

---

## 三、分阶段开发与测试指南（按顺序执行）
### 前置准备工作
#### 0.1 更新依赖配置
**开发步骤**：
1. 修改`pyproject.toml`，将`typer`版本从`0.9.0`更新为`0.12.3`
2. 新增依赖项：`pyperclip==1.8.2`（用于剪贴板功能）
3. 重新安装项目：`pip install -e .`

**测试用例**：
```powershell
# 验证依赖安装
pip list | findstr -E "typer|pyperclip"
# 预期输出：
# typer            0.12.3
# pyperclip        1.8.2
```

---

### 阶段1：后端API完善（优先完成，CLI功能依赖这些接口）
#### 1.1 实现命令记录接口 `/api/v1/cli/command/record`
**目标**：提供CLI命令的持久化存储接口
**修改文件**：`backend/routers/cli.py`
**开发完成标准**：
- 新增`CommandRecordRequest` Pydantic模型
- 实现POST接口，支持新增/更新命令记忆
- 接口返回正确的JSON响应

**🧪 测试用例（直接复制运行）**：
```powershell
# 测试接口是否可用
curl -X POST http://localhost:8000/api/v1/cli/command/record `
  -H "Content-Type: application/json" `
  -d '{\"command\": \"docker ps -a --filter status=running\", \"count\": 3, \"shell\": \"powershell\"}'

# 预期输出：
# {"status":"success"}

# 验证数据是否存入数据库
curl -X GET "http://localhost:8000/api/v1/memory/search?query=docker&type=cli_command"
# 预期输出：包含刚才存入的docker命令
```

#### 1.2 实现命令推荐接口 `/api/v1/cli/command/suggest`
**目标**：根据用户输入的部分命令智能推荐完整命令
**修改文件**：`backend/routers/cli.py`
**开发完成标准**：
- 新增`CommandSuggestRequest` Pydantic模型
- 实现POST接口，返回按使用频率排序的推荐列表
- 支持按当前目录、shell类型过滤结果

**🧪 测试用例（直接复制运行）**：
```powershell
# 测试推荐接口
curl -X POST http://localhost:8000/api/v1/cli/command/suggest `
  -H "Content-Type: application/json" `
  -d '{\"partial_command\": \"docker\", \"shell\": \"powershell\"}'

# 预期输出：
# {"suggestions": [{"command": "docker ps -a --filter status=running", "description": "powershell命令", "count": 3, ...}]}
```

---

### 阶段2：CLI端功能增强
#### 2.1 增强`search`命令的交互体验（一键复制/执行）
**目标**：搜索结果支持直接操作，无需手动复制
**修改文件**：`cli/main.py`
**开发完成标准**：
- 新增`--execute`/`--copy`参数，支持直接执行或复制第一个搜索结果
- 支持交互式选择结果，提供执行/复制选项
- 自动处理命令执行的输出和错误

**🧪 测试用例（直接复制运行）**：
```powershell
# 1. 先手动存一个测试命令
mem memorize "echo test command" --type "cli_command"

# 2. 测试直接复制功能
mem search "test" --copy
# 预期输出：✅ 已复制到剪贴板：echo test command
# 验证：剪贴板内容应该为"echo test command"

# 3. 测试直接执行功能
mem search "test" --execute
# 预期输出：
# 🚀 执行命令：echo test command
# test command

# 4. 测试交互式选择
mem search "test"
# 预期输出：列出匹配结果，提示选择序号，选择后可以执行或复制
```

#### 2.2 实现`watch`命令，自动捕获历史命令
**目标**：自动扫描shell历史记录，记录高频命令
**修改文件**：`cli/main.py`
**开发完成标准**：
- 支持PowerShell/Bash/Zsh三种shell的历史文件读取
- 自动过滤短命令和重复命令
- 按阈值自动记录高频命令到记忆库

**🧪 测试用例（直接复制运行）**：
```powershell
# 1. 执行3次测试命令（触发自动记录阈值）
echo "test watch command"
echo "test watch command"
echo "test watch command"

# 2. 运行watch命令
mem watch --shell powershell --auto-record-threshold 3
# 预期输出：✅ 已扫描历史命令，自动记录了X条高频命令

# 3. 验证自动记录的命令
mem search "test watch command"
# 预期输出：能找到刚才自动记录的命令
```

#### 2.3 新增`workflow`工作流命令组
**目标**：支持多步骤工作流的保存和执行
**修改文件**：`cli/main.py`
**开发完成标准**：
- 新增`workflow save`命令，支持保存多步骤工作流
- 新增`workflow run`命令，支持交互式执行工作流的每个步骤
- 支持跳过不需要执行的步骤

**🧪 测试用例（直接复制运行）**：
```powershell
# 1. 保存一个测试工作流
mem workflow save "测试工作流" "echo step1" "echo step2" "echo step3"
# 预期输出：✅ 工作流「测试工作流」已保存，包含3个步骤

# 2. 查看是否保存成功
mem search "测试工作流" --type "cli_workflow"
# 预期输出：能找到刚才保存的工作流

# 3. 执行工作流（全部选跳过）
mem workflow run "测试工作流"
# 预期输出：
# 🚀 开始执行工作流「测试工作流」，共3个步骤
# 步骤 1/3: echo step1
# 是否执行？ [Y/n] n
# ⏭️  跳过该步骤
# ...（依次跳过所有步骤）
```

---

### 阶段3：核心引擎扩展
#### 3.1 优化命令搜索的相关性算法
**目标**：CLI命令搜索结果更符合用户使用习惯
**修改文件**：`core/retriever.py`
**开发完成标准**：
- 实现`calculate_relevance_score`函数
- 支持使用频率加权、最近使用加权、前缀匹配加权
- 高频率、最近使用的命令排在更前面

**🧪 测试用例（直接复制运行）**：
```powershell
# 1. 存两个测试命令，一个使用次数高，一个低
# 先执行watch命令多次记录"echo high frequency"（比如执行5次）
# 再手动存一个"echo low frequency"命令（使用次数1）

# 2. 搜索"echo"
mem search "echo"
# 预期输出：使用次数高的"echo high frequency"排在第一个
```

---

### 阶段4：全功能集成测试
**🧪 完整流程测试用例**：
```powershell
# 1. 开启监控模式
mem watch

# 2. 执行几次复杂命令
docker ps
docker images
docker ps -a --filter status=exited

# 3. 搜索命令
mem search "docker exited"
# 预期输出：能找到"docker ps -a --filter status=exited"命令

# 4. 保存工作流
mem workflow save "docker清理" "docker system prune -f" "docker volume prune -f"

# 5. 执行工作流
mem workflow run "docker清理"
# 预期输出：按步骤执行清理命令
```

---

## 原详细开发步骤（代码参考）
### 阶段1：CLI端功能增强
#### 1.1 实现命令自动捕获功能
**目标**：无需用户手动执行`mem memorize`，自动捕获用户输入的高频命令
**修改文件**：`cli/main.py`
**新增命令**：`watch`命令，开启后台监控模式
```python
import atexit
import readline
from pathlib import Path

@app.command()
def watch(
    shell: str = typer.Option("powershell", help="要监控的shell类型：powershell/bash/zsh"),
    auto_record_threshold: int = typer.Option(3, help="命令使用多少次后自动记录")
):
    """开启命令行监控模式，自动记录高频命令"""
    history_file = {
        "powershell": Path.home() / "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",
        "bash": Path.home() / ".bash_history",
        "zsh": Path.home() / ".zsh_history"
    }[shell]
    
    # 读取历史命令统计频率
    with open(history_file, "r", encoding="utf-8", errors="ignore") as f:
        commands = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    from collections import Counter
    command_counts = Counter(commands)
    
    # 自动记录使用超过阈值的命令
    for cmd, count in command_counts.items():
        if count >= auto_record_threshold and len(cmd) > 10: # 过滤短命令
            # 调用后端API存入记忆
            try:
                requests.post(
                    f"{get_api_base()}/cli/command/record",
                    json={"command": cmd, "count": count, "shell": shell}
                )
            except:
                pass
    
    typer.echo(f"✅ 已扫描历史命令，自动记录了{len([c for c in command_counts.values() if c >= auto_record_threshold])}条高频命令")
```

#### 1.2 增强`search`命令的交互体验
**目标**：搜索结果支持一键复制、直接执行
**修改文件**：`cli/main.py`
```python
import pyperclip
import subprocess

@app.command()
def search(
    query: str = typer.Argument(..., help="搜索关键词"),
    limit: int = typer.Option(5, help="返回结果数量"),
    execute: bool = typer.Option(False, help="直接执行第一个匹配的命令"),
    copy: bool = typer.Option(False, help="直接复制第一个匹配的命令到剪贴板")
):
    """搜索相关记忆"""
    response = requests.get(
        f"{get_api_base()}/memory/search",
        params={"query": query, "limit": limit, "type": "cli_command"}
    )
    response.raise_for_status()
    results = response.json()
    
    if not results:
        typer.echo("❌ 没有找到相关记忆")
        return
    
    if execute:
        cmd = results[0]["content"]
        typer.echo(f"🚀 执行命令：{cmd}")
        subprocess.run(cmd, shell=True)
        return
    
    if copy:
        cmd = results[0]["content"]
        pyperclip.copy(cmd)
        typer.echo(f"✅ 已复制到剪贴板：{cmd}")
        return
    
    # 交互式选择
    typer.echo("找到以下相关命令：")
    for i, result in enumerate(results, 1):
        typer.echo(f"\n{i}. {result['content']}")
        typer.echo(f"   描述：{result.get('description', '无描述')}")
        typer.echo(f"   使用次数：{result.get('metadata', {}).get('count', 0)}")
    
    selected = typer.prompt("\n请选择要执行/复制的命令序号（输入0退出）", type=int, default=0)
    if selected > 0 and selected <= len(results):
        cmd = results[selected-1]["content"]
        action = typer.prompt("请选择操作：1=执行 2=复制", type=int, default=1)
        if action == 1:
            subprocess.run(cmd, shell=True)
        else:
            pyperclip.copy(cmd)
            typer.echo("✅ 已复制到剪贴板")
```

#### 1.3 新增`workflow`命令组
**目标**：支持多步骤工作流的存储与复用
**修改文件**：`cli/main.py`
```python
workflow_app = typer.Typer(help="工作流模板管理")
app.add_typer(workflow_app, name="workflow")

@workflow_app.command("save")
def save_workflow(
    name: str = typer.Argument(..., help="工作流名称"),
    steps: List[str] = typer.Argument(..., help="工作流步骤命令，用空格分隔，多词用引号包裹")
):
    """保存工作流模板"""
    workflow = {
        "name": name,
        "steps": steps,
        "created_at": datetime.now().isoformat()
    }
    response = requests.post(
        f"{get_api_base()}/memory/",
        json={
            "content": json.dumps(workflow, ensure_ascii=False),
            "type": "cli_workflow",
            "description": f"工作流：{name}",
            "metadata": workflow
        }
    )
    response.raise_for_status()
    typer.echo(f"✅ 工作流「{name}」已保存，包含{len(steps)}个步骤")

@workflow_app.command("run")
def run_workflow(name: str = typer.Argument(..., help="工作流名称")):
    """执行已保存的工作流"""
    response = requests.get(
        f"{get_api_base()}/memory/search",
        params={"query": name, "type": "cli_workflow", "limit": 1}
    )
    results = response.json()
    if not results:
        typer.echo(f"❌ 未找到工作流「{name}」")
        return
    
    workflow = json.loads(results[0]["content"])
    typer.echo(f"🚀 开始执行工作流「{name}」，共{len(workflow['steps'])}个步骤")
    
    for i, step in enumerate(workflow["steps"], 1):
        typer.echo(f"\n步骤 {i}/{len(workflow['steps'])}: {step}")
        confirm = typer.confirm("是否执行？", default=True)
        if confirm:
            subprocess.run(step, shell=True)
        else:
            typer.echo("⏭️  跳过该步骤")
```

---

### 阶段2：后端API完善
#### 2.1 实现命令记录接口
**修改文件**：`backend/routers/cli.py`
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

#### 2.2 实现命令推荐接口
**修改文件**：`backend/routers/cli.py`
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

---

### 阶段3：核心引擎扩展
#### 3.1 优化命令搜索的相关性
**修改文件**：`core/retriever.py`
```python
def calculate_relevance_score(query: str, memory: Memory) -> float:
    """计算CLI命令场景下的相关性得分"""
    base_score = memory.similarity_score if hasattr(memory, 'similarity_score') else 0.0
    
    # CLI命令特殊权重规则
    metadata = memory.metadata or {}
    
    # 高频率使用的命令加分
    count = metadata.get("count", 0)
    count_score = min(count * 0.05, 0.3) # 最多加0.3分
    
    # 最近使用的命令加分
    last_used = metadata.get("last_used_at")
    recency_score = 0.0
    if last_used:
        from datetime import datetime
        try:
            last_used_time = datetime.fromisoformat(last_used)
            days_ago = (datetime.now() - last_used_time).days
            recency_score = max(0, 0.2 - (days_ago * 0.01)) # 30天内的命令最多加0.2分
        except:
            pass
    
    # 完全前缀匹配额外加分
    if memory.content.lower().startswith(query.lower()):
        prefix_score = 0.2
    else:
        prefix_score = 0.0
    
    return base_score + count_score + recency_score + prefix_score
```

---

### 阶段4：数据库优化
#### 4.1 新增CLI命令专用索引
**修改文件**：`db/relational/models.py`
```python
# 在Memory类中添加索引配置
class Memory(Base):
    __tablename__ = "memories"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content = Column(Text, nullable=False)
    type = Column(String(50), index=True, nullable=False) # 已存在，确保有索引
    user_id = Column(String(100), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        # 新增联合索引，优化CLI命令查询
        Index('idx_cli_command_type_user', 'type', 'user_id'),
    )
```

---

## 四、联调与测试
### 4.1 单元测试用例
编写测试文件：`tests/test_cli_commands.py`
```python
def test_memorize_command():
    """测试手动记录命令"""
    result = subprocess.run(["mem", "memorize", "docker ps -a --filter status=running"], capture_output=True, text=True)
    assert result.returncode == 0

def test_search_command():
    """测试搜索命令"""
    result = subprocess.run(["mem", "search", "docker"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "docker ps" in result.stdout

def test_workflow():
    """测试工作流功能"""
    subprocess.run(["mem", "workflow", "save", "deploy", "git pull", "npm install", "npm run build"], capture_output=True)
    result = subprocess.run(["mem", "workflow", "run", "deploy"], input="n\nn\nn\n", capture_output=True, text=True)
    assert "deploy" in result.stdout
```

### 4.2 集成测试步骤
1. 开启监控模式：`mem watch`
2. 执行几次相同的复杂命令
3. 搜索命令：`mem search "docker run"`
4. 验证自动记录是否生效
5. 测试工作流保存和执行功能

---

## 五、上线注意事项
1. **隐私保护**：默认不记录包含敏感信息的命令（如包含`password`/`secret`/`key`等关键词的命令）
2. **性能优化**：历史命令扫描操作放在后台异步执行，不阻塞用户操作
3. **兼容性**：支持Windows PowerShell、WSL、Linux Bash、macOS Zsh等主流shell
4. **资源占用**：监控模式内存占用控制在50MB以内，CPU占用<1%

---

## 六、扩展功能 roadmap
1. 支持命令参数自动填充（根据历史使用记录）
2. 支持团队命令库共享
3. 集成AI自动生成命令注释和使用说明
4. 支持命令错误自动修正建议
