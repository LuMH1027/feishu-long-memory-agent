# 4. 统一权重体系与决策干预CLI动态重排

## 目标
实现闭环流转的最点睛之笔，用高维度团队决策约束个人终端命令环境下的提示候选。保证飞书和 CLI 并肩协作。

## 涉及文件
- `backend/routers/cli.py`
- `core/retriever.py`

## 开发完成标准
- 升级 `search` 与 `suggest` 接口中的检索重排链路，构建 **向量检索 + 关键词兜底 + CLI 专用混合重排** 机制。首先统筹命令前缀、使用频率、最近使用时间、项目目录上下文与执行成功率（利用 `directory` 与 `execution_feedback` 元数据）进行初始评估。
- **团队决策动态重排机制**：如果 CLI 中命令文本所涉及的 `flags`、`paths` 等关键参数被最新入库的飞书决策判定为过期/负向评价（例如旧有的 staging 环境命令），大幅降低其推荐评分。
- 反向提升命中最新规范属性（如 `prod` 命令）操作的召回排名。

## 重点机制测试
```bash
# 模拟冲突更新以及推荐结果演变
# 1. 飞书中下达决策："弃用 staging 采用 prod"（被 bot/2-记忆提取录入）
# 2. 终端侧开发者输入：mem suggest "deploy project-a"
#
# 预期终端侧展示：
# - 优先推荐：kubectl apply -f k8s/prod.yaml
# - 降维甚至剔除：kubectl apply -f k8s/staging.yaml
```

## 2026-04-29 实现记录

本阶段已完成团队决策对 CLI 推荐排序的干预：

1. `backend/routers/cli.py` 的 `/api/v1/cli/command/suggest` 会读取活跃的 `project_decision` 记忆。
2. 当命令命中 `preferred_terms`，例如 `prod`，排序分提升。
3. 当命令命中 `rejected_terms`，例如 `staging`，排序分降低。
4. 该策略与原有 CLI 排序信号共同生效：
   - 前缀匹配
   - 目录上下文
   - 团队决策偏好
   - 执行成功率
   - 使用频率
   - 最近使用时间
5. 已新增单元测试证明：即使 `staging` 命令历史使用次数更高，只要飞书决策声明 `prod` 替代 `staging`，`prod` 命令仍会在 `suggest` 中排到更前。
