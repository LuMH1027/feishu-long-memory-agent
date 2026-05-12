# 企业级记忆引擎

一个跨越 CLI 与飞书的统一记忆系统，帮助开发者和团队沉淀、唤醒、复用碎片化知识。

## 核心能力

- **CLI 记忆引擎** — 自然语言搜索命令、前缀推荐、矛盾自动更新、工作流编排
- **飞书团队记忆** — 群聊决策自动抽取、智能路由、卡片推送、跨消息矛盾检测
- **跨域联动** — 飞书决策影响 CLI 推荐，CLI 命令可被飞书查询
- **混合存储** — SQLite 关系库 + ChromaDB 向量库，语义搜索 + 关键词匹配双通道

## 架构

```
┌─────────────────────────────────────────────────────┐
│                    信息捕获层                         │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│   │ CLI 客户端 │    │ 飞书机器人 │    │ API 接口  │      │
│   └─────┬────┘    └─────┬────┘    └─────┬────┘      │
│         └───────────────┼───────────────┘            │
│                         ▼                            │
│              ┌──────────────────┐                    │
│              │   记忆引擎核心    │                    │
│              │  ┌────────────┐  │                    │
│              │  │ 决策提取器  │  │  ← LLM + 正则双保险 │
│              │  │ 矛盾检测器  │  │                    │
│              │  │ 语义检索器  │  │                    │
│              │  └────────────┘  │                    │
│              │         ▼        │                    │
│              │  ┌────────────┐  │                    │
│              │  │ 混合数据库  │  │  ← SQLite + ChromaDB│
│              │  └────────────┘  │                    │
│              └──────────────────┘                    │
│                         ▼                            │
│              ┌──────────────────┐                    │
│              │    知识应用层     │                    │
│              │  CLI 智能推荐    │                    │
│              │  飞书卡片推送    │                    │
│              └──────────────────┘                    │
└─────────────────────────────────────────────────────┘
```

## 快速开始

### 环境要求

- Python 3.10+
- Git

### 安装

```bash
git clone <repo-url>
cd feishu-long-memory-agent
pip install -e .
```

### 配置

复制并编辑环境变量：

```bash
cp .env.example .env
```

`.env` 中需要配置：

| 变量 | 说明 | 示例 |
|------|------|------|
| `OPENAI_API_KEY` | Embedding/LLM API Key | `sk-xxx` |
| `OPENAI_BASE_URL` | API 地址（支持第三方代理） | `https://api.siliconflow.cn/v1` |
| `EMBEDDING_MODEL` | Embedding 模型 | `BAAI/bge-m3` |
| `LLM_MODEL` | LLM 模型 | `Qwen3-VL-8B-Instruct` |
| `FEISHU_APP_ID` | 飞书应用 ID（可选） | `cli_xxx` |
| `FEISHU_APP_SECRET` | 飞书应用密钥（可选） | `xxx` |

### 启动

```bash
# 运行环境自检（可选但推荐）
python scripts/preflight_check.py

# 初始化/重置数据库
python scripts/reset_db.py        # 重置并重建
python scripts/reset_db.py --no-reinit  # 仅清空不重建

# 启动后端
uvicorn backend.main:app --reload --port 8000

# 配置 CLI（另一个终端）
mem configure
# 输入: http://127.0.0.1:8000/api/v1
```

## 使用指南

### CLI 命令

```bash
# 记忆命令
mem memorize "docker run -p 8080:80 --name webapp my-image:1.2" --type "docker启动命令"

# 语义搜索（自然语言）
mem search "启动webapp容器"

# 搜索 + 展示降级模式
mem search "启动容器" --explain
# ✅ 语义搜索 | 找到 3 条
# ⚠️ Embedding 不可用，降级为关键词搜索 | 找到 2 条

# 前缀推荐
mem suggest "docker" --limit 5

# 列出所有记忆
mem list --limit 20

# 保存工作流
mem workflow save "生产健康检查" "docker ps -a" "kubectl get pods -n prod"

# 执行工作流
mem workflow run "生产健康检查"

# 仪表盘（系统全貌一瞥）
mem stats

# 速记便签（无需 --type）
mem note "今晚8点记得备份数据库"

# 最近更新 / 最常使用
mem recent --limit 10
mem popular --limit 10

# 软删除 + 回收站 + 恢复
mem delete <memory_id>
mem trash
mem restore <memory_id>

# 命令别名
mem alias save kp "kubectl get pods -n prod"
mem alias run kp
mem alias list

# 降权 / 反馈（越用越准）
mem dismiss <memory_id>
mem feedback <memory_id> --useful

# 决策时间线
mem timeline "部署"

# 话题订阅
mem subscribe add "API"
mem subscribe list

# 关联图谱
mem related "部署"
```

### 飞书机器人

#### 启动飞书长连接

飞书 SDK 通过 WebSocket 实时接收群聊消息。在 `.env` 中配置好飞书凭证后执行：

```bash
# 先确认后端已经在运行
uvicorn backend.main:app --port 8000

# 另开终端，启动飞书事件监听
python scripts/run_feishu_sdk_events.py
```

**前置条件**：

| 条件 | 检查方式 |
|------|---------|
| `lark-oapi` 已安装 | `pip list | grep lark-oapi` |
| `.env` 中 `FEISHU_APP_ID` 已配置 | 不能是 `your_xxx` 占位值 |
| `.env` 中 `FEISHU_APP_SECRET` 已配置 | 不能是 `your_xxx` 占位值 |
| 飞书应用已启用**事件订阅** | 飞书开放平台 → 应用 → 事件订阅 |
| 飞书应用已订阅 `im.message.receive_v1` | 事件订阅配置页 |
| 飞书应用已发布上线（或配置了测试群） | 飞书开放平台 → 应用 → 安全设置 |

**自动 Mock 模式**：如果 `lark-oapi` 未安装或飞书凭证未配置，启动脚本会自动切到 Mock 模式——消息仅打印到终端，不会连接真实飞书。Mock 模式下可使用 HTTP API 直接测试：
```bash
# 模拟飞书群消息（Mock 模式下使用）
curl -X POST http://127.0.0.1:8000/api/v1/feishu/message/analyze \
  -H "Content-Type: application/json" \
  -d '{"content":"以后统一用 Jest 做单元测试","chat_id":"demo","user_id":"alice"}'
```

#### 机器人行为

在群聊中 @机器人 发送消息，系统自动判断消息意图（规则模式）或 LLM 7 类分类：

| 消息类型 | 示例 | 机器人行为 |
|---------|------|-----------|
| 新决策 | `以后统一用 Jest 做单元测试` | 提取决策 → 推送待确认卡片 → 👍/👎 确认/打回 → 入库 |
| 修正决策 | `不对，改成用 Vitest` | 识别为 `decision_revise` → 走矛盾更新 |
| 确认决策 | `那就按张工说的做` | 识别为 `decision_confirm` → 加固置信度 |
| 模糊意图 | `以后用那个新的部署方式` | 识别为 `unclear` → 追问澄清 |
| 查询消息 | `之前用什么部署环境？` | 检索相关记忆 → 推送卡片 |
| 普通闲聊 | `今天天气不错` | 忽略，不回复 |

> 设置 `USE_LLM_DECISION_EXTRACTION=1` 启用 LLM 意图分类，替代关键词规则。

**更多飞书功能**：机器人入群自动发送欢迎介绍；`@机器人 最近有什么决策` 浏览历史决策。

#### 飞书决策卡片

机器人推送待确认决策卡片，通过 Reaction 实现人审机决：

- **待确认卡片**：包含 `[确认采纳]` `[打回]` 按钮
- **Reaction 确认**：👍 确认采纳（3 人 👍 自动确认）、👎 打回删除
- **文本打回**：`@机器人 打回` 附带理由撤回
- 卡片展示决策主题、结论、原因、推荐/废弃方案、截止日期和记录时间

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 关系存储 | SQLAlchemy + SQLite |
| 向量存储 | ChromaDB（余弦相似度） |
| Embedding | BAAI/bge-m3（1024 维） |
| LLM | Qwen3-VL-8B-Instruct |
| CLI | Typer |
| 飞书集成 | lark-oapi（官方 Python SDK） |

## 项目结构

```
├── backend/            # FastAPI 后端
│   ├── main.py         # 应用入口
│   ├── routers/        # API 路由（CLI、飞书、健康检查）
│   └── dependencies.py # 依赖注入
├── cli/                # Typer CLI 客户端
│   └── main.py         # mem 命令定义
├── core/               # 核心业务逻辑
│   ├── storage.py      # 记忆存储（关系库 + 向量库）
│   ├── retriever.py    # 语义检索
│   ├── decision_extractor.py  # 决策提取（LLM + 正则）
│   └── command_parser.py      # 命令解析
├── db/                 # 数据层
│   ├── relational/     # SQLAlchemy 模型
│   └── vector/         # ChromaDB 客户端
├── feishu_bot/         # 飞书机器人
│   ├── sdk_events.py   # WebSocket 事件处理
│   ├── sdk_messages.py # 消息发送（文本/卡片）
│   ├── card_templates.py # 卡片模板
│   └── mock.py         # SDK Mock 模式（免飞书凭证可演示）
├── demo/               # 演示脚本和素材
├── scripts/            # 工具脚本
│   ├── preflight_check.py   # 环境自检
│   ├── reset_db.py          # 数据库重置
│   ├── benchmark_search.py  # 搜索性能基准
│   └── view_database.py     # 数据库查询
└── tests/              # 测试
```

## Demo 演示

三种演示脚本，按场景选用：

```bash
# 叙事版（4 分钟故事线，适合答辩路演）
python demo/demo_story.py --reset-db

# 全自动日志（截图友好，一条命令跑完 12 步）
python demo/auto_log.py --reset-db
python demo/auto_log.py --start-from 5    # 断点续跑

# 交互式录屏（有暂停提示，适合录视频，5 个阶段）
python demo/demo_record.py --reset-db
python demo/demo_record.py --start-from 3  # 从阶段 3 继续
```

**飞书 Mock 模式**：未安装 `lark-oapi` 或未配置飞书凭证时，自动切换到消息模拟输出：

```bash
FEISHU_MOCK_MODE=1 python demo/demo_story.py --reset-db
```

### 搜索性能基准

```bash
# 自动预填 500 条、20 queries × 5 轮
python scripts/benchmark_search.py --seed 500

# 输出:
#   搜索性能基准 (100 queries, 500条记忆库):
#     p50: 12ms | p95: 45ms | p99: 89ms
#     Embedding: avg 8ms | DB查询: avg 3ms
```

## 许可证

MIT
