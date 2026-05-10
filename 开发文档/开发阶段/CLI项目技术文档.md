# CLI 记忆系统项目技术文档

更新时间：2026-04-29

本文档说明本项目 CLI 方向的完整功能、技术路线、模块职责、调用链路和最新优化结果。当前 CLI 方向已经形成从“命令采集 -> 长期记忆 -> 检索推荐 -> 执行反馈 -> 自动评测”的完整闭环。

---

## 1. 项目定位

CLI 记忆系统面向开发者效率场景，解决终端中长命令、复杂参数、项目路径偏好和多步工作流难以记忆与复用的问题。

系统支持：

- 用户主动教给系统一条记忆。
- 自动扫描 shell 历史，记录高频命令。
- 根据自然语言或命令前缀搜索历史命令。
- 保存和运行多步工作流。
- 根据当前项目目录进行上下文感知推荐。
- 根据命令结构、执行成功率、最近使用时间和频率排序。
- 识别“更正/不对/以后用”等矛盾更新语义，避免旧记忆污染。
- 通过 evaluation 测试量化抗干扰、矛盾更新和效率提升效果。

典型场景：

```powershell
mem memorize "docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2" --type "docker启动命令"
mem search "启动webapp容器"
mem suggest "docker"
mem workflow save "docker清理" "docker system prune -f" "docker volume prune -f"
```

---

## 2. 总体架构

系统采用：

```text
Typer CLI + FastAPI 后端 + SQLite 关系库 + ChromaDB 向量库 + pytest 评测
```

架构链路：

```text
用户终端
  |
  | mem configure / memorize / search / suggest / watch / workflow / list
  v
cli/main.py
  |
  | requests HTTP
  v
backend/main.py (FastAPI)
  |
  +-- backend/routers/cli.py
  |      |
  |      +-- /api/v1/cli/command/record
  |      +-- /api/v1/cli/command/suggest
  |      +-- /api/v1/cli/command/list
  |
  +-- backend/routers/memory.py
         |
         +-- /api/v1/memory/extract
         +-- /api/v1/memory/
         +-- /api/v1/memory/search
         +-- /api/v1/memory/retrieve
         +-- /api/v1/memory/list
         |
         +-- core/storage.py
         +-- core/retriever.py
         +-- core/command_parser.py
                |
                +-- SQLite memories 表
                +-- ChromaDB vector_store
```

### 2.1 存储设计

关系数据库 SQLite 是主存储，ChromaDB 是语义检索增强。

保存记忆时：

```text
先写 SQLite -> 再尝试写 ChromaDB
```

如果 embedding 或 ChromaDB 失败，不影响关系库保存成功。

检索时：

```text
优先向量检索 -> SQLite 回查 -> CLI 专用排序 -> 关键词兜底
```

这种设计保证了系统稳定性：向量库不可用时，CLI 搜索仍可通过关键词和元数据匹配工作。

---

## 3. 核心模块职责

### 3.1 `cli/main.py`

CLI 用户入口，基于 Typer 实现。

主要职责：

- 定义 `mem` 命令组。
- 读取后端 API 地址。
- 发送 HTTP 请求到 FastAPI。
- 统一搜索结果格式。
- 读取 shell history。
- 执行命令或复制命令。
- 采集当前目录上下文。
- 执行后回写 `exit_code`。

关键函数：

| 函数 | 作用 |
|---|---|
| `get_api_base()` | 读取 API 地址，优先全局配置，其次 `.env` |
| `_request()` | 统一发送 HTTP 请求 |
| `_current_directory()` | 获取当前目录，作为项目上下文 |
| `_record_command_usage()` | 执行后回写命令、目录和 exit code |
| `_search_memories()` | 多级检索入口 |
| `_normalize_result()` | 统一 memory 和 command suggestion 返回结构 |

### 3.2 `backend/main.py`

FastAPI 应用入口。

主要职责：

- 创建 FastAPI app。
- 注册 CLI 和 memory 路由。
- 服务启动时初始化数据库。
- 提供 `/health` 健康检查。

注册关系：

```python
app.include_router(cli.cli_router, prefix="/api/v1")
app.include_router(memory.router, prefix="/api/v1/memory")
```

### 3.3 `backend/dependencies.py`

数据库依赖模块。

主要职责：

- 读取 `DATABASE_URL`。
- 创建 SQLAlchemy engine。
- 创建 `SessionLocal`。
- 提供 `get_db()`。
- 提供 `init_database_schema()`。

启动时会执行：

```python
Base.metadata.create_all(bind=engine)
```

并兼容性补齐：

- `description`
- `memory_metadata`

### 3.4 `db/relational/models.py`

核心关系模型。

`Memory` 表字段：

| 字段 | 说明 |
|---|---|
| `id` | 记忆 ID |
| `content` | 记忆正文，如完整 CLI 命令 |
| `type` | 记忆类型，如 `cli_command`、`cli_workflow` |
| `source` | 来源，如 `cli`、`feishu_group` |
| `description` | 记忆描述 |
| `memory_metadata` | JSON 字符串，保存 count、directory、command_pattern、success_count 等扩展信息 |
| `user_id` | 用户 ID |
| `team_id` | 团队 ID |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `expire_at` | 过期时间 |
| `hit_count` | 检索命中次数 |

CLI 命令不单独建表，而是保存在 `memories` 表中：

```text
type = "cli_command"
source = "cli"
```

工作流同样保存在 `memories` 表中：

```text
type = "cli_workflow"
source = "cli"
```

### 3.5 `backend/routers/cli.py`

CLI 专用后端接口。

接口：

```text
POST /api/v1/cli/command/record
POST /api/v1/cli/command/suggest
GET  /api/v1/cli/command/list
```

主要能力：

- 记录高频命令。
- 合并重复命令。
- 保存目录上下文。
- 保存命令解析结果。
- 保存执行反馈。
- 根据前缀、目录、频率、成功率推荐命令。

`memory_metadata` 示例：

```json
{
  "count": 8,
  "shell": "powershell",
  "directory": "E:/workspace/project-a",
  "directories": {
    "E:/workspace/project-a": 8
  },
  "first_used_at": "2026-04-28T...",
  "last_used_at": "2026-04-28T...",
  "command_pattern": {
    "program": "docker",
    "subcommand": "run",
    "command_family": "docker run",
    "flags": {
      "-p": "8080:80",
      "-v": "/data:/app/data",
      "--name": "webapp"
    },
    "positionals": ["my-image:1.2"],
    "paths": ["/data:/app/data"]
  },
  "success_count": 3,
  "failure_count": 1,
  "last_exit_code": 0
}
```

### 3.6 `backend/routers/memory.py`

通用记忆后端接口。

接口：

```text
POST   /api/v1/memory/
POST   /api/v1/memory/extract
GET    /api/v1/memory/search
POST   /api/v1/memory/retrieve
GET    /api/v1/memory/list
GET    /api/v1/memory/{memory_id}
DELETE /api/v1/memory/{memory_id}
```

主要能力：

- 保存普通记忆和工作流记忆。
- 检索记忆。
- 关键词兜底搜索。
- 中文意图词映射。
- 中文短语匹配。
- 矛盾更新处理。
- 过滤 inactive 旧记忆。

矛盾更新 metadata 示例：

旧记忆：

```json
{
  "status": "inactive",
  "topic_key": "cli:周报发送命令::",
  "superseded_by": "new-memory-id"
}
```

新记忆：

```json
{
  "status": "active",
  "topic_key": "cli:周报发送命令::",
  "supersedes": ["old-memory-id"]
}
```

### 3.7 `core/storage.py`

核心存储模块。

主要职责：

- 保存记忆到 SQLite。
- 尝试写入 ChromaDB。
- 按 ID 查询记忆。
- 删除记忆。

重要设计：

```text
关系库先成功，向量库失败不阻断主流程
```

### 3.8 `core/retriever.py`

核心检索和重排序模块。

CLI 排序信号：

- 向量相似度
- 命令前缀匹配
- 使用频率
- 最近使用时间
- 执行成功率

`calculate_cli_relevance_score()` 会综合这些信号：

```text
base_score
+ count_score
+ recency_score
+ prefix_score
+ success_score
```

### 3.9 `core/command_parser.py`

命令模式抽取模块。

输入：

```text
docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2
```

输出：

```json
{
  "program": "docker",
  "subcommand": "run",
  "command_family": "docker run",
  "flags": {
    "-p": "8080:80",
    "-v": "/data:/app/data",
    "--name": "webapp"
  },
  "positionals": ["my-image:1.2"],
  "paths": ["/data:/app/data"]
}
```

作用：

- 让推荐不只依赖完整字符串。
- 支持按参数、路径、子命令搜索。
- 为“常用参数组合”记忆提供结构化基础。

---

## 4. CLI 命令功能与调用链

### 4.1 `mem configure`

配置后端 API 地址。

调用链：

```text
mem configure
  -> cli.main.configure()
  -> 写入 ~/.mem_agent/config.ini
```

不调用后端。

### 4.2 `mem memorize`

主动保存记忆。

调用链：

```text
mem memorize
  -> cli.main.memorize()
  -> POST /api/v1/memory/extract
  -> memory.extract_and_store_memory()
  -> memory.store_memory()
  -> core.storage.save_memory()
  -> SQLite memories
  -> ChromaDB
```

### 4.3 `mem search`

搜索命令、普通记忆或工作流。

调用链：

```text
mem search "启动webapp容器"
  -> cli.main.search()
  -> _search_memories(query, limit, type, directory)
      1. GET /api/v1/memory/search
      2. POST /api/v1/memory/retrieve
      3. POST /api/v1/cli/command/suggest
  -> _normalize_result()
```

支持：

```powershell
mem search "docker exited"
mem search "docker exited" --copy
mem search "docker exited" --execute
mem search "docker exited" --type cli_command
```

`--execute` 会执行并回写：

```text
subprocess.run()
  -> returncode
  -> _record_command_usage()
  -> POST /api/v1/cli/command/record
  -> success_count / failure_count 更新
```

### 4.4 `mem suggest`

面向 shell completion 的轻量推荐命令。

示例：

```powershell
mem suggest "docker"
```

调用链：

```text
mem suggest
  -> cli.main.suggest()
  -> POST /api/v1/cli/command/suggest
  -> 输出纯命令文本
```

这个命令不输出解释文本，方便后续接入 PowerShell/Bash/Zsh 自动补全脚本。

### 4.5 `mem watch`

扫描 shell 历史并记录高频命令。

调用链：

```text
mem watch
  -> cli.main.watch()
  -> 读取 shell history
  -> Counter 统计频次
  -> 过滤 count >= threshold 且长度 > 10 的命令
  -> POST /api/v1/cli/command/record
  -> backend.routers.cli.record_command()
  -> memories(type=cli_command)
```

当前会上报：

```json
{
  "command": "...",
  "count": 3,
  "shell": "powershell",
  "directory": "当前目录"
}
```

### 4.6 `mem workflow save`

保存多步工作流。

调用链：

```text
mem workflow save
  -> cli.main.save_workflow()
  -> POST /api/v1/memory/
  -> memory.store_memory()
  -> core.storage.save_memory()
  -> memories(type=cli_workflow)
```

### 4.7 `mem workflow run`

检索并逐步执行工作流。

调用链：

```text
mem workflow run
  -> cli.main.run_workflow()
  -> _search_memories(name, 1, "cli_workflow", directory)
  -> json.loads(workflow)
  -> typer.confirm()
  -> subprocess.run(step)
  -> _record_command_usage(step, exit_code)
```

每一步执行后都会回写执行结果。

### 4.8 `mem list`

查看最近记忆和 CLI 命令。

调用链：

```text
mem list
  -> GET /api/v1/memory/list
  -> GET /api/v1/cli/command/list
  -> 合并展示
```

### 4.9 `mem clear`

当前只做本地确认和提示。

当前限制：

```text
不会真正删除 SQLite 或 ChromaDB 中的数据
```

后续可新增：

```text
DELETE /api/v1/memory/
DELETE /api/v1/cli/command/
```

---

## 5. 检索与排序策略

### 5.1 多级检索链路

```text
GET /memory/search
  -> 向量检索
  -> SQLite 回查
  -> 过滤 inactive
  -> 关键词兜底
  -> 排序

POST /memory/retrieve
  -> 兼容 retrieve 检索

POST /cli/command/suggest
  -> CLI 命令兜底推荐
```

### 5.2 关键词和中文意图兜底

`backend/routers/memory.py` 中 `_memory_search_score()` 会匹配：

- `content`
- `description`
- `metadata`
- 英文 token
- 中文意图词映射
- 中文 2 字短语片段

中文意图映射示例：

```text
启动 -> run/start
容器 -> docker/container
清理 -> prune/clean
查看 -> list/ls/ps
```

中文短语示例：

```text
发送周报 -> 发送 / 送周 / 周报
```

### 5.3 CLI 命令推荐排序

`/cli/command/suggest` 排序信号：

1. 前缀匹配
2. 当前目录匹配
3. 执行成功率
4. 使用次数
5. 最近使用时间

目录匹配规则：

```text
完全同目录：高权重
父子目录：中权重
同目录名：低权重
```

成功率规则：

```text
success_score = success_count / (success_count + failure_count) * 0.2
```

### 5.4 向量检索排序

`core/retriever.py` 中对 CLI 记忆进一步加权：

```text
similarity_score
+ frequency score
+ recency score
+ prefix score
+ success score
```

这样即使向量召回多个候选，也会优先返回更常用、更近期、更符合当前上下文、更成功的命令。

---

## 6. 记忆治理机制

### 6.1 重复命令合并

`record_command()` 按以下条件判断重复：

```text
Memory.type == "cli_command"
Memory.content == request.command
```

重复时不新建记录，而是更新：

- `count`
- `last_used_at`
- `directory`
- `directories`
- `command_pattern`
- `exit_code`
- `success_count`
- `failure_count`

### 6.2 执行反馈闭环

当用户通过 CLI 执行命令：

```powershell
mem search "test" --execute
mem workflow run "deploy"
```

系统会记录：

```json
{
  "last_exit_code": 0,
  "success_count": 5,
  "failure_count": 1
}
```

推荐时成功率更高的命令优先。

### 6.3 矛盾更新机制

识别关键词：

```text
不对 / 更正 / 改成 / 以后用 / 以后改 / 不再使用 / 更新
```

写入新记忆时：

```text
查找同 source/type/user_id/team_id 的 active 旧记忆
  -> 旧记忆 status = inactive
  -> 旧记忆 superseded_by = 新记忆 ID
  -> 新记忆 supersedes = [旧记忆 ID]
```

检索时会过滤：

```text
metadata.status == "inactive"
```

典型场景：

```text
旧记忆：以后周报发给 A
新记忆：不对，以后周报发给 B
搜索：发送周报
结果：只返回 B
```

---

## 7. 与飞书和 OpenClaw 的结合方式

CLI 系统可以作为统一长期记忆底座中的“操作记忆层”。

```text
CLI 记录真实操作命令和执行结果
飞书记录项目决策、讨论上下文和协作入口
OpenClaw 负责任务编排和执行决策
SQLite/ChromaDB 提供统一记忆检索
```

典型联动：

```text
飞书群里问：怎么启动 webapp？
  -> 飞书机器人调用 /memory/search
  -> 召回 CLI 记忆
  -> 推送历史命令卡片
  -> 用户确认后由 CLI/OpenClaw 执行
  -> 执行结果回写 /cli/command/record
```

这样方向 A 和方向 B 可以自然衔接：

```text
飞书沉淀“为什么这么做”
CLI 沉淀“具体怎么做”
统一记忆库负责跨场景复用
```

---

## 8. 测试体系

当前测试分四层。

### 8.1 单元测试

目录：

```text
tests/unit
```

覆盖：

- CLI 配置读取
- `mem memorize`
- `mem search`
- `mem suggest`
- `mem watch`
- `mem workflow`
- `/cli/command/record`
- `/cli/command/suggest`
- `/memory/search`
- 命令解析
- 执行反馈
- 矛盾更新
- 向量客户端

### 8.2 集成测试

目录：

```text
tests/integration
```

核心文件：

```text
tests/integration/test_cli_acceptance_flow.py
```

覆盖完整链路：

```text
mem watch
mem search
mem search --copy
mem workflow save
mem workflow run
mem list
```

### 8.3 Evaluation 测试

目录：

```text
tests/evaluation
```

核心文件：

```text
tests/evaluation/test_cli_effectiveness_dataset.py
```

读取数据集：

```text
test/data/cli_effectiveness_dataset.json
```

自动验证：

- 抗干扰测试
- 矛盾更新测试
- 效能指标测试

### 8.4 量化指标

当前数据集指标：

| 指标 | 数值 |
|---|---|
| 关键 CLI 记忆 | 6 条 |
| 干扰数据 | 360 条 |
| 信噪比 | 1:60 |
| 抗干扰 Hit@1 | 100.0% |
| 抗干扰 Hit@3 | 100.0% |
| MRR | 100.0% |
| 矛盾更新用例 | 3 组 |
| 最新记忆胜出率 | 100.0% |
| 平均字符输入减少 | 80.3% |
| 平均操作步数减少 | 58.0% |
| 平均耗时减少 | 78.2% |

最近全量测试结果：

```powershell
pytest tests -q -p no:cacheprovider
```

```text
67 passed, 4 warnings in 5.76s
```

---

## 9. 当前已完成能力对照赛题

| 赛题要求 | 当前完成情况 |
|---|---|
| 显式记忆 | `mem memorize` 已完成 |
| 隐式记忆 | `mem watch` 高频统计已完成 |
| 高频命令模式 | `count`、`command_pattern` 已完成 |
| 常用参数组合 | `core/command_parser.py` 已初步完成 |
| 项目路径偏好 | `directory/directories` 已完成基础版 |
| 上下文感知推荐 | suggest/search 排序已支持目录加权 |
| 前缀推荐 | `mem suggest` 已完成，待接 shell completion |
| 工作流记忆 | `mem workflow save/run` 已完成 |
| 执行反馈 | `exit_code/success_count/failure_count` 已完成 |
| 矛盾更新 | `inactive/supersedes/superseded_by` 已完成 |
| 量化评测 | `tests/evaluation` 已完成 |

---

## 10. 当前边界与后续优化

### 10.1 `mem clear` 尚未真实删除数据库

当前 `mem clear` 只做本地确认和提示，没有调用后端删除接口。

后续可新增：

```text
DELETE /api/v1/memory/
DELETE /api/v1/cli/command/
```

### 10.2 Shell completion 尚未正式接入

当前已经有：

```powershell
mem suggest "prefix"
```

但还没有写 PowerShell/Bash/Zsh 的补全脚本。

### 10.3 中文乱码仍需清理

部分历史文件和测试输出存在乱码文本，功能不受影响，但会影响展示观感。

### 10.4 弃用警告

当前测试仍有：

- SQLAlchemy `declarative_base()` 弃用警告
- FastAPI `on_event` 弃用警告
- `datetime.utcnow()` 弃用警告

---

## 11. 一句话总结

CLI 记忆系统以 Typer 提供本地命令入口，以 FastAPI 承接记忆读写请求，以 SQLite 作为可靠主存储，以 ChromaDB 提供语义检索增强，并通过项目上下文、命令模式抽取、执行反馈、矛盾更新和自动化评测，把开发者真实操作经验沉淀为可检索、可复用、可治理的长期记忆。
