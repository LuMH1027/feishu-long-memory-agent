# CLI 完整功能演示脚本

主脚本：

```powershell
python scripts\demo_cli_full_flow.py
```

PowerShell 启动脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo_cli_full_flow.ps1
```

## 运行方式

保留现有数据库数据，直接追加演示数据：

```powershell
python scripts\demo_cli_full_flow.py
```

清空 `db/memory.db` 后重新演示：

```powershell
python scripts\demo_cli_full_flow.py --reset-db
```

指定后端端口：

```powershell
python scripts\demo_cli_full_flow.py --reset-db --port 8001
```

如果你更习惯 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo_cli_full_flow.ps1 -ResetDb
```

## 脚本会做什么

1. 初始化数据库。
2. 启动 FastAPI 后端。
3. 配置 CLI API 地址。
4. 执行 `mem memorize`，展示显式记忆如何写入 `memories` 表。
5. 执行 `mem search`，展示检索后 `hit_count` 的变化。
6. 调用 `/cli/command/record`，模拟 `mem watch` 记录高频命令。
7. 执行 `mem suggest`，展示前缀推荐。
8. 执行 `mem search --execute`，展示 `success_count` 和 `last_exit_code`。
9. 执行 `mem workflow save/run`，展示工作流记忆和步骤执行反馈。
10. 执行矛盾更新示例，展示旧记忆 `inactive` 和新记忆 `supersedes`。
11. 执行 `mem list`，展示最终记忆列表。

每一步之后，脚本都会直接读取 SQLite：

```text
db/memory.db
```

并打印：

- 当前表列表
- `memories` 行数
- 每条记忆的 `id/type/source/content/hit_count`
- 关键 metadata：
  - `count`
  - `directory`
  - `directories`
  - `command_pattern`
  - `success_count`
  - `failure_count`
  - `last_exit_code`
  - `status`
  - `supersedes`
  - `superseded_by`
  - `steps`

## 注意事项

- 脚本会临时启动后端进程，结束时自动关闭。
- 后端日志写入：

```text
demo_backend.log
```

- `--reset-db` 或 `-ResetDb` 会删除 `db/memory.db`，只建议在演示环境使用。
