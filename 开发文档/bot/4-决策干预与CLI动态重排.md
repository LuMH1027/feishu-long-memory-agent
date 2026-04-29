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