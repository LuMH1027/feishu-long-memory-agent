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
# 初始化数据库
python init_db.py

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

# 前缀推荐
mem suggest "docker" --limit 5

# 列出所有记忆
mem list --limit 20

# 保存工作流
mem workflow save "生产健康检查" "docker ps -a" "kubectl get pods -n prod"

# 执行工作流
mem workflow run "生产健康检查"
```

### 飞书机器人

在群聊中 @机器人 发送消息，系统会自动判断消息类型：

| 消息类型 | 示例 | 机器人行为 |
|---------|------|-----------|
| 决策消息 | `以后统一用 Jest 做单元测试` | 提取决策 → 入库 → 推送蓝色卡片 |
| 查询消息 | `之前用什么部署环境？` | 检索相关记忆 → 推送卡片 |
| 矛盾更新 | `更正，以后用 prod 不用 staging` | 覆盖旧决策 → 推送更新卡片 |
| 普通消息 | `今天天气不错` | 忽略，不回复 |

### 飞书决策卡片

机器人会推送结构化的决策卡片，包含：

- 决策主题和结论
- 推荐方案 / 废弃方案
- 相关项目和截止日期
- 记录时间

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
│   └── card_templates.py # 卡片模板
├── demo/               # 演示脚本和素材
├── scripts/            # 工具脚本
└── tests/              # 测试
```

## Demo 演示

```bash
# 全自动日志（截图友好，一条命令跑完 12 步）
python demo/auto_log.py --reset-db

# 交互式录屏（有暂停提示，适合录视频）
python demo/demo_record.py --reset-db
```

详见 [demo/README.md](demo/README.md)。

## 许可证

MIT
