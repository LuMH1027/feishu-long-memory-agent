# CLI 记忆系统项目技术文档

更新时间：2026-04-27

本文档说明本项目中 CLI 方向的完整功能、技术路线、模块职责和调用链路。重点回答三个问题：

1. CLI 提供了哪些能力。
2. 每个 CLI 命令调用了哪些函数、哪些后端接口。
3. 后端接口如何落到真实数据库、向量库和检索逻辑。

---

## 1. 项目定位

CLI 方向的目标是把本地命令行历史、用户主动记忆和常用工作流沉淀为可检索、可复用的长期记忆。

用户不需要反复回忆完整命令，例如：

```powershell
docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2
```

后续只需要输入：

```powershell
mem search "启动webapp容器"
```

系统会从关系数据库和向量检索结果中找到最相关的记忆，返回完整命令，并支持复制或执行。

---

## 2. 总体技术路线

CLI 技术路线采用“本地 CLI 客户端 + FastAPI 后端 + SQLite 关系库 + Chroma 向量库”的架构。

### 2.1 架构分层

```text
用户终端
  |
  | mem configure / memorize / search / watch / workflow / list
  v
cli/main.py
  |
  | requests HTTP 调用
  v
FastAPI 后端 backend/main.py
  |
  | 路由注册
  +--> backend/routers/memory.py
  |       |
  |       +--> core/storage.py
  |       |       |
  |       |       +--> SQLite memories 表
  |       |       +--> Chroma vector_store
  |       |
  |       +--> core/retriever.py
  |
  +--> backend/routers/cli.py
          |
          +--> SQLite memories 表中 type=cli_command 的记录
```

### 2.2 存储策略

系统使用双存储：

- 关系数据库：SQLite，真实主存储，保存所有记忆的正文、类型、来源、用户、命中次数、元数据等。
- 向量数据库：ChromaDB，增强语义检索能力。

当前设计中，关系库是 source of truth。也就是说：

- 保存记忆时，先写 SQLite。
- 再尝试生成 embedding 并写入 Chroma。
- 如果 embedding 或 Chroma 不可用，不影响 SQLite 保存成功。
- 检索时优先尝试向量检索，失败或无结果时回退到关系库关键词检索。

这样做的好处是：向量库依赖缺失或服务异常时，CLI 记忆功能不会完全不可用。

---

## 3. 代码模块职责

### 3.1 CLI 入口：`cli/main.py`

这是用户真正执行 `mem` 命令时进入的文件。

核心职责：

- 定义 Typer CLI 应用。
- 读取 API 地址配置。
- 发起 HTTP 请求到 FastAPI 后端。
- 对搜索结果做统一格式化。
- 提供本地交互能力，例如复制到剪贴板、执行命令、读取 shell history。

主要对象：

```python
app = typer.Typer(...)
workflow_app = typer.Typer(...)
app.add_typer(workflow_app, name="workflow")
```

这说明项目有一个主命令 `mem`，以及一个子命令组 `mem workflow`。

### 3.2 后端入口：`backend/main.py`

这是 FastAPI 应用入口。

核心职责：

- 创建 FastAPI app。
- 注册 CLI 路由和 memory 路由。
- 在服务启动时初始化数据库表结构。
- 暴露健康检查接口。

当前注册关系：

```python
app.include_router(cli.cli_router, prefix="/api/v1", tags=["CLI端对接"])
app.include_router(memory.router, prefix="/api/v1/memory", tags=["记忆管理"])
```

因此真实 API 路径是：

- `/api/v1/cli/command/record`
- `/api/v1/cli/command/suggest`
- `/api/v1/cli/command/list`
- `/api/v1/memory/extract`
- `/api/v1/memory/`
- `/api/v1/memory/search`
- `/api/v1/memory/retrieve`
- `/api/v1/memory/list`

服务启动时调用：

```python
@app.on_event("startup")
def startup_event():
    init_database_schema()
```

这里会初始化数据库。

### 3.3 数据库依赖：`backend/dependencies.py`

核心职责：

- 读取 `.env` 中的 `DATABASE_URL`。
- 创建 SQLAlchemy engine。
- 创建 SessionLocal。
- 定义 Base。
- 提供 `get_db()` 依赖。
- 提供 `init_database_schema()` 初始化表结构。

关键调用：

```python
Base.metadata.create_all(bind=engine)
```

这会创建模型中定义的表。

同时，为了兼容已有数据库，`init_database_schema()` 会检查 `memories` 表是否缺少字段：

- `description`
- `memory_metadata`

如果缺少，就执行 SQLite 兼容的 `ALTER TABLE` 补列。

### 3.4 数据模型：`db/relational/models.py`

核心表是 `memories`。

字段说明：

| 字段 | 作用 |
|---|---|
| `id` | 记忆 ID，主键 |
| `content` | 记忆正文，例如完整 CLI 命令 |
| `type` | 记忆类型，例如 `cli_command`、`cli_workflow`、`docker启动命令` |
| `source` | 来源，例如 `cli`、`feishu_group` |
| `description` | 记忆描述 |
| `memory_metadata` | JSON 字符串，保存 count、shell、directory、workflow steps 等扩展信息 |
| `user_id` | 用户 ID |
| `team_id` | 团队 ID |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `expire_at` | 过期时间 |
| `hit_count` | 检索命中次数 |

CLI 命令历史不是单独建表，而是保存到 `memories` 表中，使用：

```text
type = "cli_command"
source = "cli"
```

工作流也保存到同一张表中，使用：

```text
type = "cli_workflow"
source = "cli"
```

### 3.5 CLI 后端接口：`backend/routers/cli.py`

这个模块专门处理 CLI 命令历史。

提供三个接口：

1. `POST /api/v1/cli/command/record`
2. `POST /api/v1/cli/command/suggest`
3. `GET /api/v1/cli/command/list`

真实 API 请求会通过 `Depends(get_db)` 获得 SQLAlchemy Session，然后读写 `memories` 表。

同时文件中保留了：

```python
temp_command_storage = []
```

它只用于单元测试 fallback。当路由函数被测试直接调用、没有真实 db session 时，才使用临时数组。

### 3.6 Memory 后端接口：`backend/routers/memory.py`

这个模块处理通用记忆。

提供接口：

1. `POST /api/v1/memory/`
2. `POST /api/v1/memory/extract`
3. `GET /api/v1/memory/list`
4. `GET /api/v1/memory/search`
5. `POST /api/v1/memory/retrieve`
6. `GET /api/v1/memory/{memory_id}`
7. `DELETE /api/v1/memory/{memory_id}`

它是 CLI 主动记忆、工作流保存、搜索检索的主要后端入口。

### 3.7 核心存储：`core/storage.py`

核心职责：

- 保存记忆到 SQLite。
- 尝试保存记忆向量到 Chroma。
- 按 ID 查询记忆。
- 删除记忆时同时删除关系库和向量库。

关键设计：

```python
db.add(db_memory)
db.commit()
db.refresh(db_memory)
```

先提交关系库。

之后：

```python
try:
    embedding = get_embedding(memory_data.content)
    vector_client.add_memory(...)
except Exception:
    pass
```

向量库写入失败不会影响主流程。

### 3.8 核心检索：`core/retriever.py`

核心职责：

- 生成 query embedding。
- 调用向量库检索。
- 根据向量库结果回查 SQLite。
- 针对 CLI 命令进行重排序。

CLI 专用排序因素：

- 向量相似度：`similarity_score`
- 使用次数：`metadata.count`
- 最近使用时间：`metadata.last_used_at`
- 前缀匹配：命令是否以用户输入开头

排序入口：

```python
search_memories(db, query, top_k, threshold)
```

对于 CLI 命令，排序使用：

```python
_search_sort_key(query, memory)
```

其中 `calculate_cli_relevance_score()` 会把相似度、频率、最近使用、前缀匹配合并成综合分。

### 3.9 向量库客户端：`db/vector/client.py`

核心职责：

- 初始化 ChromaDB 持久化客户端。
- 创建或获取 `memories` collection。
- 写入 memory embedding。
- 根据 query embedding 搜索。
- 删除向量记录。

向量库路径来自环境变量：

```python
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "./db/vector_store")
```

默认保存在：

```text
db/vector_store
```

---

## 4. CLI 功能详解与调用链

本节按用户实际命令说明。

---

## 4.1 `mem configure`

### 功能

配置 CLI 访问的后端 API 地址。

示例：

```powershell
mem configure
```

用户输入：

```text
http://localhost:8000/api/v1
```

配置会保存到：

```text
~/.mem_agent/config.ini
```

### 调用链

```text
用户执行 mem configure
  -> cli/main.py: configure()
      -> typer.prompt() 获取 API 地址
      -> CONFIG_DIR.mkdir()
      -> configparser.ConfigParser()
      -> 写入 CONFIG_FILE
```

### 后端调用

该命令不调用后端，只写本地配置。

### API 地址读取逻辑

所有 CLI 网络请求都会通过：

```python
get_api_base()
```

读取顺序：

1. 优先读取 `~/.mem_agent/config.ini` 中的 `default.api_base`
2. 如果没有配置文件，再读取 `.env` 中的 `API_BASE`
3. 如果 `.env` 也没有，则默认：

```text
http://localhost:8000/api/v1
```

---

## 4.2 `mem memorize`

### 功能

主动保存一条记忆。

示例：

```powershell
mem memorize "docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2" --type "docker启动命令"
```

### CLI 调用链

```text
用户执行 mem memorize
  -> cli/main.py: memorize(content, type)
      -> _request("POST", "/memory/extract", json={...})
          -> requests.request(method, f"{get_api_base()}{path}", ...)
```

CLI 发出的请求体：

```json
{
  "content": "docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2",
  "type": "docker启动命令",
  "source": "cli",
  "user_id": "local_user"
}
```

### 后端调用链

```text
POST /api/v1/memory/extract
  -> backend/routers/memory.py: extract_and_store_memory()
      -> 构造 MemoryStoreRequest
      -> store_memory(payload, db)
          -> core/storage.py: save_memory(db, payload)
              -> db.add(Memory(...))
              -> db.commit()
              -> db.refresh()
              -> get_embedding(content)
              -> vector_client.add_memory(...)
              -> return db_memory
          -> _memory_to_dict(memory)
          -> 返回 JSON
```

### 数据落库

写入 `memories` 表。

关键字段：

```text
content = 用户输入内容
type = 用户传入的 type
source = "cli"
user_id = 当前用户
expire_at = 当前时间 + DEFAULT_MEMORY_EXPIRE_DAYS
```

### 向量库写入

`core/storage.py` 中保存关系库成功后，会尝试：

```text
content -> embedding -> Chroma memories collection
```

如果向量库失败，关系库记忆仍然保存成功。

---

## 4.3 `mem search`

### 功能

搜索记忆或命令。

示例：

```powershell
mem search "启动webapp容器"
```

支持参数：

```powershell
mem search "docker exited" --limit 5
mem search "docker exited" --copy
mem search "docker exited" --execute
mem search "docker exited" --type cli_command
```

### CLI 调用链

```text
用户执行 mem search
  -> cli/main.py: search(query, limit, execute, copy, type)
      -> _search_memories(query, limit, memory_type)
```

`_search_memories()` 是 CLI 搜索的核心。

### `_search_memories()` 调用顺序

```text
_search_memories(query, limit, memory_type)
  1. GET /memory/search
  2. 如果失败或无结果，POST /memory/retrieve
  3. 如果仍无结果，POST /cli/command/suggest
  4. _normalize_result() 统一返回结构
```

具体路径：

```text
GET /api/v1/memory/search?query=...&limit=...&type=...
```

失败或无结果后：

```text
POST /api/v1/memory/retrieve
```

请求体：

```json
{
  "query": "启动webapp容器",
  "top_k": 5
}
```

如果 memory 检索仍没有结果，再调用：

```text
POST /api/v1/cli/command/suggest
```

请求体：

```json
{
  "partial_command": "启动webapp容器",
  "shell": "powershell"
}
```

### 后端 `/memory/search` 调用链

```text
GET /api/v1/memory/search
  -> backend/routers/memory.py: search_memories()
      -> _search_db(db, query, type, limit)
          -> 尝试 core/retriever.py: search_memories(db, query, limit, threshold=0.0)
              -> get_embedding(query)
              -> vector_client.search_memories(...)
              -> db.query(Memory).filter(Memory.id.in_(memory_ids))
              -> CLI 专用重排序
              -> memory.hit_count += 1
              -> db.commit()
          -> 如果向量失败或结果不足，遍历关系库做关键词匹配
          -> _sort_and_limit()
          -> 更新命中次数 hit_count
          -> db.commit()
          -> 返回结果
```

### 关系库关键词兜底检索

在 `backend/routers/memory.py` 中：

```python
_memory_search_score(memory, query)
```

会把以下内容拼成搜索文本：

- `content`
- `description`
- `metadata` 中的值

然后检查 query 或 query terms 是否命中。

还内置了部分中文意图词到命令词的映射，例如：

```text
启动 -> run/start
容器 -> docker/container
清理 -> prune/clean
查看 -> list/ls/ps
```

因此用户输入中文“启动webapp容器”，也有机会匹配到包含 `docker run` 的命令。

### `/cli/command/suggest` 兜底检索

如果通用 memory 搜索没有结果，CLI 会调用 `/cli/command/suggest`。

该接口只查：

```text
Memory.type == "cli_command"
```

匹配逻辑：

```python
_matches_partial_command(command, partial_command)
```

规则是：用户输入拆成多个 token，每个 token 都要出现在 command 中。

例如：

```text
partial_command = "docker exited"
command = "docker ps -a --filter status=exited"
```

可以匹配，因为 `docker` 和 `exited` 都在命令中。

### 搜索结果处理

CLI 会调用：

```python
_normalize_result(result)
```

把不同接口返回的数据统一成：

```json
{
  "content": "...",
  "type": "...",
  "description": "...",
  "metadata": {}
}
```

这样 `mem search` 不需要关心结果来自 memory API 还是 CLI suggest API。

### `--copy` 和 `--execute`

如果使用：

```powershell
mem search "xxx" --copy
```

调用：

```python
pyperclip.copy(results[0]["content"])
```

如果使用：

```powershell
mem search "xxx" --execute
```

调用：

```python
subprocess.run(cmd, shell=True)
```

如果没有 `--copy` 和 `--execute`，CLI 会展示列表，并让用户选择：

```text
1. 执行
2. 复制
0. 退出
```

---

## 4.4 `mem watch`

### 功能

扫描本地 shell 历史，自动记录高频命令。

示例：

```powershell
mem watch --shell powershell --auto-record-threshold 3
mem watch --shell bash --auto-record-threshold 3
mem watch --shell zsh --auto-record-threshold 3
```

### 支持的历史文件

PowerShell：

```text
~/AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt
```

Bash：

```text
~/.bash_history
```

Zsh：

```text
~/.zsh_history
```

### CLI 调用链

```text
用户执行 mem watch
  -> cli/main.py: watch(shell, auto_record_threshold)
      -> 根据 shell 找到 history 文件
      -> 读取文件行
      -> 过滤空行和注释
      -> Counter(commands) 统计频率
      -> 对 count >= threshold 且长度 > 10 的命令逐条上报
      -> _request("POST", "/cli/command/record", json={...})
```

请求体：

```json
{
  "command": "docker ps -a --filter status=exited",
  "count": 3,
  "shell": "bash"
}
```

### 后端调用链

```text
POST /api/v1/cli/command/record
  -> backend/routers/cli.py: record_command()
      -> 查询 memories 表中是否已有相同 command 且 type=cli_command
      -> 如果存在：
           metadata.count += request.count
           metadata.last_used_at = now
           metadata.shell = request.shell
           metadata.directory = request.directory
           updated_at = now
      -> 如果不存在：
           db.add(Memory(type="cli_command", source="cli", ...))
      -> db.commit()
      -> 返回 {"status": "success"}
```

### 去重合并逻辑

判断重复命令的条件：

```python
Memory.type == "cli_command"
Memory.content == request.command
```

如果同一条命令重复出现，不新建多条记录，而是累加：

```text
memory_metadata.count
```

这样搜索排序可以利用“使用频率”。

---

## 4.5 `mem workflow save`

### 功能

保存多步 CLI 工作流。

示例：

```powershell
mem workflow save "docker清理" "docker system prune -f" "docker volume prune -f"
```

### CLI 调用链

```text
用户执行 mem workflow save
  -> cli/main.py: save_workflow(name, steps)
      -> 构造 workflow dict
      -> json.dumps(workflow, ensure_ascii=False)
      -> 优先 _request("POST", "/memory/", json=payload)
      -> 如果失败，fallback 到 _request("POST", "/memory/extract", json={...})
```

payload 结构：

```json
{
  "content": "{\"name\":\"docker清理\",\"steps\":[...],\"created_at\":\"...\"}",
  "type": "cli_workflow",
  "description": "工作流：docker清理",
  "metadata": {
    "name": "docker清理",
    "steps": [
      "docker system prune -f",
      "docker volume prune -f"
    ],
    "created_at": "..."
  }
}
```

### 后端调用链

```text
POST /api/v1/memory/
  -> backend/routers/memory.py: store_memory()
      -> core/storage.py: save_memory()
          -> 写入 memories 表
          -> 尝试写入 Chroma
```

### 数据落库

工作流和普通记忆一样写入 `memories` 表。

关键字段：

```text
type = "cli_workflow"
source = "cli"
content = workflow JSON 字符串
memory_metadata = workflow JSON 元信息
```

---

## 4.6 `mem workflow run`

### 功能

检索已保存的工作流，并逐步询问用户是否执行每一步。

示例：

```powershell
mem workflow run "docker清理"
```

### CLI 调用链

```text
用户执行 mem workflow run
  -> cli/main.py: run_workflow(name)
      -> _search_memories(name, 1, "cli_workflow")
      -> json.loads(results[0]["content"])
      -> 遍历 steps
      -> typer.confirm("是否执行")
      -> subprocess.run(step, shell=True)
```

### 检索链路

工作流复用通用搜索链路：

```text
run_workflow()
  -> _search_memories(name, 1, "cli_workflow")
      -> GET /memory/search?query=name&limit=1&type=cli_workflow
      -> POST /memory/retrieve
      -> POST /cli/command/suggest
```

由于传入了 `memory_type="cli_workflow"`，最终结果会过滤为：

```text
type == "cli_workflow"
```

### 执行安全

每一步执行前都会确认：

```python
typer.confirm(...)
```

用户拒绝则跳过该步骤。

---

## 4.7 `mem list`

### 功能

查看最近保存的记忆和 CLI 命令。

示例：

```powershell
mem list --limit 10
```

### CLI 调用链

```text
用户执行 mem list
  -> cli/main.py: list(limit)
      -> GET /memory/list
      -> GET /cli/command/list
      -> 合并两个接口返回结果
      -> 打印 [id] [type] content...
```

### 后端 `/memory/list`

```text
GET /api/v1/memory/list
  -> backend/routers/memory.py: list_memories()
      -> db.query(Memory).order_by(Memory.created_at.desc()).limit(limit).all()
      -> _memory_to_dict()
```

### 后端 `/cli/command/list`

```text
GET /api/v1/cli/command/list
  -> backend/routers/cli.py: list_commands()
      -> db.query(Memory)
           .filter(Memory.type == "cli_command")
           .order_by(Memory.updated_at.desc())
           .limit(limit)
           .all()
```

### 为什么要查两个接口

`/memory/list` 返回通用记忆。

`/cli/command/list` 专门返回已记录的 CLI 命令，并按最近更新时间排序。

CLI 客户端把两类结果合并展示，方便用户看到：

- 主动保存的记忆
- 自动扫描的高频命令
- 工作流记录

---

## 4.8 `mem clear`

### 当前功能

当前 `mem clear` 只做本地确认和成功提示。

调用链：

```text
用户执行 mem clear
  -> cli/main.py: clear(force)
      -> 如果没有 --force，typer.confirm()
      -> 输出“记忆已清空”
```

### 当前限制

当前代码没有调用后端删除接口，也没有清空 SQLite 或 Chroma。

也就是说：

```powershell
mem clear --force
```

目前不会真正删除数据库中的记忆。

### 后续建议

如果要实现真实清空，需要新增后端接口，例如：

```text
DELETE /api/v1/memory/
DELETE /api/v1/cli/command/
```

并在 CLI 中调用对应接口。

---

## 5. 后端 API 详细说明

### 5.1 `POST /api/v1/memory/extract`

用途：保存一条用户主动注入的记忆。

调用方：

- `mem memorize`
- `mem workflow save` 的 fallback 分支

入口函数：

```python
backend/routers/memory.py: extract_and_store_memory()
```

内部调用：

```text
extract_and_store_memory()
  -> MemoryStoreRequest(...)
  -> store_memory()
  -> core.storage.save_memory()
```

### 5.2 `POST /api/v1/memory/`

用途：保存结构化记忆，支持 description 和 metadata。

调用方：

- `mem workflow save`

入口函数：

```python
backend/routers/memory.py: store_memory()
```

内部调用：

```text
store_memory()
  -> SimpleNamespace(**memory_data.model_dump())
  -> core.storage.save_memory()
```

### 5.3 `GET /api/v1/memory/search`

用途：搜索记忆。

调用方：

- `mem search`
- `mem workflow run`

入口函数：

```python
backend/routers/memory.py: search_memories()
```

内部调用：

```text
search_memories()
  -> _search_db()
      -> core.retriever.search_memories()
      -> 关键词兜底检索
      -> _sort_and_limit()
```

### 5.4 `POST /api/v1/memory/retrieve`

用途：兼容已有 retrieve 检索接口。

调用方：

- `_search_memories()` 在 `/memory/search` 失败或无结果时调用

入口函数：

```python
backend/routers/memory.py: retrieve_memories()
```

内部也是调用：

```text
_search_db()
```

### 5.5 `GET /api/v1/memory/list`

用途：返回最近记忆列表。

调用方：

- `mem list`

入口函数：

```python
backend/routers/memory.py: list_memories()
```

### 5.6 `GET /api/v1/memory/{memory_id}`

用途：按 ID 获取单条记忆。

入口函数：

```python
backend/routers/memory.py: get_memory()
```

内部调用：

```text
core.storage.get_memory_by_id()
```

### 5.7 `DELETE /api/v1/memory/{memory_id}`

用途：按 ID 删除单条记忆。

入口函数：

```python
backend/routers/memory.py: delete_memory()
```

内部调用：

```text
core.storage.get_memory_by_id()
core.storage.delete_memory()
```

删除时：

- 先删除 SQLite 记录。
- 再尝试删除 Chroma 向量记录。

### 5.8 `POST /api/v1/cli/command/record`

用途：记录 CLI 命令历史。

调用方：

- `mem watch`

入口函数：

```python
backend/routers/cli.py: record_command()
```

内部逻辑：

```text
查询 type=cli_command 且 content=command 的 Memory
  -> 如果存在，合并 count，更新 last_used_at
  -> 如果不存在，新增 Memory
  -> db.commit()
```

### 5.9 `POST /api/v1/cli/command/suggest`

用途：根据部分命令推荐完整命令。

调用方：

- `mem search` 在 memory 搜索没有结果时调用

入口函数：

```python
backend/routers/cli.py: suggest_command()
```

内部逻辑：

```text
db.query(Memory).filter(Memory.type == "cli_command").all()
  -> _matches_partial_command()
  -> 按 metadata.count 降序排序
  -> 返回 suggestions
```

### 5.10 `GET /api/v1/cli/command/list`

用途：列出最近记录的 CLI 命令。

调用方：

- `mem list`

入口函数：

```python
backend/routers/cli.py: list_commands()
```

---

## 6. 数据写入链路总览

### 6.1 主动记忆写入

```text
mem memorize
  -> cli.main.memorize()
  -> POST /api/v1/memory/extract
  -> memory.extract_and_store_memory()
  -> memory.store_memory()
  -> core.storage.save_memory()
  -> SQLite memories
  -> Chroma vector_store
```

### 6.2 高频命令写入

```text
mem watch
  -> cli.main.watch()
  -> 读取 shell history
  -> Counter 统计命令频次
  -> POST /api/v1/cli/command/record
  -> cli.record_command()
  -> SQLite memories(type=cli_command)
```

### 6.3 工作流写入

```text
mem workflow save
  -> cli.main.save_workflow()
  -> POST /api/v1/memory/
  -> memory.store_memory()
  -> core.storage.save_memory()
  -> SQLite memories(type=cli_workflow)
  -> Chroma vector_store
```

---

## 7. 数据检索链路总览

### 7.1 普通搜索

```text
mem search "启动webapp容器"
  -> cli.main.search()
  -> cli.main._search_memories()
  -> GET /api/v1/memory/search
  -> memory.search_memories()
  -> memory._search_db()
  -> core.retriever.search_memories()
  -> Chroma search
  -> SQLite 回查
  -> CLI 重排序
  -> 返回结果
```

### 7.2 搜索 fallback

```text
如果 GET /memory/search 失败或无结果：
  -> POST /api/v1/memory/retrieve

如果 retrieve 仍无结果：
  -> POST /api/v1/cli/command/suggest
```

### 7.3 工作流搜索

```text
mem workflow run "docker清理"
  -> _search_memories("docker清理", 1, "cli_workflow")
  -> 只保留 type=cli_workflow 的结果
  -> json.loads(content)
  -> 逐步确认执行
```

---

## 8. 检索排序策略

### 8.1 向量相似度

`core/retriever.py` 会先用 query embedding 查询 Chroma。

返回结果包含：

```json
{
  "id": "...",
  "similarity": 0.92,
  "metadata": {}
}
```

然后根据 ID 从 SQLite 回查完整 Memory。

### 8.2 CLI 专用加权

对于 `type == "cli_command"` 的结果，会计算 CLI 相关性。

综合因素：

| 因素 | 作用 |
|---|---|
| 向量相似度 | 表示语义相关 |
| count | 高频命令优先 |
| last_used_at | 最近用过的命令优先 |
| prefix match | 用户输入是命令前缀时优先 |

使用次数加权：

```text
count_score = min(count * 0.05, 0.3)
```

最近使用加权：

```text
recency_score 最大 0.2
```

前缀匹配加权：

```text
prefix_score = 0.2
```

### 8.3 关键词兜底排序

如果向量检索失败，`backend/routers/memory.py` 会使用 `_memory_search_score()`。

排序因素：

1. content 是否以 query 开头
2. 关键词命中分数
3. metadata.count
4. updated_at

这保证了没有向量库时，CLI 搜索仍然能工作。

---

## 9. 数据库初始化时机

数据库初始化发生在后端启动时。

调用链：

```text
uvicorn backend.main:app
  -> import backend/main.py
  -> FastAPI startup event
  -> init_database_schema()
  -> Base.metadata.create_all(bind=engine)
  -> 检查 memories 表字段
  -> 必要时 ALTER TABLE 补 description 和 memory_metadata
```

也可以手动运行：

```powershell
python init_db.py
```

该脚本也会调用统一的初始化逻辑。

---

## 10. CLI 与飞书机器人的数据库关系

当前 CLI 和飞书机器人共用关系数据库模型。

核心原因：

- CLI 记忆保存到 `memories` 表。
- 飞书相关记忆也设计为保存到 `memories` 表。
- 使用 `source` 字段区分来源。

例如：

```text
CLI:
source = "cli"

飞书群:
source = "feishu_group"

飞书文档:
source = "feishu_doc"
```

因此二者不是两套完全独立的关系库，而是共用同一套记忆表，通过 `source` 和 `type` 区分。

向量库也使用同一个 Chroma collection：

```text
collection name = memories
```

metadata 中会带上：

```text
type
source
user_id
team_id
```

用于后续过滤和扩展。

---

## 11. 测试体系

当前测试分三层。

### 11.1 单元测试

目录：

```text
tests/unit
```

覆盖内容：

- CLI 配置读取和写入
- `mem memorize` 请求 payload
- `mem search` 多级 fallback
- `mem clear` 当前行为
- `/cli/command/record`
- `/cli/command/suggest`
- `/cli/command/list`
- core storage
- retriever 排序
- memory 路由

### 11.2 集成测试

目录：

```text
tests/integration
```

关键文件：

```text
tests/integration/test_cli_acceptance_flow.py
```

覆盖完整 CLI 验收链路：

```text
mem watch
mem search
mem search --copy
mem workflow save
mem workflow run
mem list
```

### 11.3 参赛测试数据集

目录：

```text
test/data/cli_effectiveness_dataset.json
```

覆盖：

- 抗干扰测试
- 矛盾更新测试
- 效能指标验证

当前量化结果：

| 指标 | 数值 |
|---|---|
| 关键 CLI 记忆 | 6 条 |
| 干扰数据 | 360 条 |
| 信噪比 | 1:60 |
| 抗干扰预期 Hit@1 | 100.0% |
| 抗干扰预期 Hit@3 | 100.0% |
| 矛盾更新用例 | 3 组 |
| 最新记忆胜出率 | 100.0% |
| 平均字符输入减少 | 80.3% |
| 平均操作步数减少 | 58.0% |
| 平均耗时减少 | 78.2% |

### 11.4 当前测试命令

```powershell
pytest tests\unit tests\integration -q -p no:cacheprovider
```

最近一次结果：

```text
56 passed, 4 warnings in 1.75s
```

---

## 12. 当前已知边界

### 12.1 `mem clear` 尚未真实删除数据库

当前 `clear()` 函数只确认并输出提示，没有调用后端删除接口。

### 12.2 向量库失败会静默降级

这是有意设计。关系库是主存储，向量库是增强能力。

好处是保存不容易失败。

代价是如果 Chroma 或 embedding 长期不可用，语义搜索质量会下降，只能依赖关键词兜底。

### 12.3 当前有少量弃用警告

测试中存在：

- SQLAlchemy `declarative_base()` 弃用警告
- FastAPI `on_event` 弃用警告
- `datetime.utcnow()` 弃用警告

这些不影响当前功能，但后续可以逐步替换。

---

## 13. 后续优化建议

### 13.1 实现真实 `mem clear`

建议新增：

```text
DELETE /api/v1/memory/
DELETE /api/v1/cli/command/
```

并明确是否删除：

- 全部记忆
- 仅 CLI 记忆
- 仅当前用户记忆
- 是否同步清理向量库

### 13.2 矛盾更新机制产品化

当前测试数据已经定义矛盾更新场景，但代码层面还可以增强：

- 识别“不对”“更正”“以后用”等更新意图
- 找到同主题旧记忆
- 标记旧记忆为过期或降低权重
- 新记忆优先返回

### 13.3 完善真实评测脚本

可以把 `test/data/cli_effectiveness_dataset.json` 接入 pytest：

```text
读取 seed_memories
  -> 调用 API 注入
读取 interference_stream
  -> 批量注入干扰
读取 evaluation_queries
  -> 执行检索
  -> 计算 Hit@1 / Hit@3 / MRR
```

### 13.4 统一编码和中文显示

当前部分源码和测试输出存在中文乱码显示，应统一为 UTF-8，并检查终端编码、文件编码和测试断言文本。

---

## 14. 一句话总结

CLI 项目的技术核心是：用 Typer 提供本地命令入口，用 FastAPI 承接记忆读写请求，用 SQLite 作为可靠主存储，用 ChromaDB 提供语义检索增强，再通过 CLI 专用排序和关键词兜底机制，把用户的自然语言查询稳定地映射回可执行命令和工作流。
