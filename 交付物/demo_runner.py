"""
企业级记忆引擎 - 交互式演示脚本

用法：
    python 交付物/demo_runner.py --reset-db

演示内容：
    【CLI 方向 - 面向开发者】
    1. 显式记忆注入：mem memorize 保存常用命令
    2. 语义搜索：mem search 用自然语言找命令
    3. 高频命令自动记录：模拟 mem watch 扫描 shell 历史
    4. 前缀推荐：mem suggest 智能排序推荐
    5. 工作流保存与执行：mem workflow save/run

    【飞书方向 - 面向团队】
    6. 决策抽取与入库：从飞书群消息中自动提取团队决策
    7. 消息路由演示：决策消息 vs 查询消息 vs 普通消息
    8. 交互卡片生成：决策卡片、命令卡片、工作流卡片
    9. 矛盾更新：新决策自动覆盖旧决策
    10. 历史决策查询：飞书群中查询团队历史决策

    【跨域联动】
    11. 飞书决策影响 CLI 推荐
    12. CLI 命令反哺飞书查询
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request


WORKSPACE = Path(__file__).resolve().parents[1]
DB_PATH = WORKSPACE / "db" / "memory.db"
BACKEND_LOG = WORKSPACE / "demo_backend.log"


# ── 工具函数 ──────────────────────────────────────────────

def banner(text: str) -> None:
    width = 60
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)


def sub_banner(text: str) -> None:
    print(f"\n--- {text} ---")


def run_command(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(args)}")
    result = subprocess.run(
        args, input=input_text, text=True,
        cwd=WORKSPACE, encoding="utf-8", errors="replace",
    )
    return result


def run_mem(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
    return run_command([sys.executable, "-m", "cli.main", *args], input_text=input_text)


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str) -> dict:
    with urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_backend(port: int, timeout: int = 30) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(timeout):
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def show_db_summary(title: str) -> None:
    sub_banner(f"数据库快照：{title}")
    if not DB_PATH.exists():
        print("  (数据库不存在)")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, type, source, content, hit_count, memory_metadata FROM memories ORDER BY created_at"
    ).fetchall()
    active = [r for r in rows if json.loads(r['memory_metadata'] or '{}').get('status', 'active') != 'inactive']
    inactive = [r for r in rows if json.loads(r['memory_metadata'] or '{}').get('status') == 'inactive']
    print(f"  总记录: {len(rows)} | 有效: {len(active)} | 已覆盖: {len(inactive)}")
    for r in rows:
        meta = json.loads(r['memory_metadata'] or '{}')
        status = meta.get('status', 'active')
        marker = "  " if status == 'active' else "[覆盖]"
        content = r['content'][:80] + ("..." if len(r['content']) > 80 else "")
        print(f"  {marker} [{r['type']}] {content}")
    conn.close()


# ── 演示步骤 ──────────────────────────────────────────────

def demo_step_1_memorize(port: int) -> None:
    """显式记忆注入"""
    banner("步骤 1：显式记忆注入 (mem memorize)")
    print("  开发者将常用命令显式保存到记忆系统\n")

    commands = [
        ("docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2", "docker启动命令"),
        ("kubectl logs deploy/api-server -n prod --tail=200 -f", "k8s排障命令"),
        ("pg_dump -h 10.0.8.12 -U ops -d orders_prod -F c -f backup/orders_prod_$(date +%F).dump", "数据库备份命令"),
        ("rsync -avz --delete dist/ deploy@10.0.8.30:/srv/www/console/", "发布命令"),
    ]
    for content, type_name in commands:
        run_mem(["memorize", content, "--type", type_name])

    show_db_summary("注入 4 条关键命令后")


def demo_step_2_search(port: int) -> None:
    """语义搜索"""
    banner("步骤 2：语义搜索 (mem search)")
    print("  用自然语言描述意图，系统找到最匹配的命令\n")

    queries = ["启动webapp容器", "查看生产api日志", "备份订单库"]
    for q in queries:
        sub_banner(f"搜索：{q}")
        run_mem(["search", q, "--limit", "2"])


def demo_step_3_watch(port: int) -> None:
    """高频命令自动记录"""
    banner("步骤 3：高频命令自动记录 (模拟 mem watch)")
    print("  模拟扫描 shell 历史，自动记录高频命令\n")

    commands_to_record = [
        ("docker ps -a --filter status=exited", 5),
        ("git log --oneline -10", 8),
        ("npm run build", 3),
    ]
    for cmd, count in commands_to_record:
        post_json(
            f"http://127.0.0.1:{port}/api/v1/cli/command/record",
            {"command": cmd, "count": count, "shell": "powershell", "directory": str(WORKSPACE)},
        )
        print(f"  记录：{cmd} (频次: {count})")

    show_db_summary("高频命令记录后")


def demo_step_4_suggest(port: int) -> None:
    """前缀推荐"""
    banner("步骤 4：前缀推荐 (mem suggest)")
    print("  输入命令前缀，返回智能排序的推荐列表\n")

    for prefix in ["docker", "git"]:
        sub_banner(f"前缀：{prefix}")
        run_mem(["suggest", prefix, "--limit", "5"])


def demo_step_5_contradiction(port: int) -> None:
    """矛盾更新"""
    banner("步骤 5：矛盾更新演示")
    print("  先记录一条旧决策，再用新决策覆盖它\n")

    sub_banner("写入旧记忆")
    run_mem([
        "memorize",
        "以后周报发给 A：python scripts/send_weekly.py --to a@example.com",
        "--type", "周报发送命令",
    ])
    show_db_summary("旧记忆写入后")

    sub_banner("写入新记忆（覆盖旧记忆）")
    run_mem([
        "memorize",
        "不对，以后周报发给 B：python scripts/send_weekly.py --to b@example.com",
        "--type", "周报发送命令",
    ])
    show_db_summary("新记忆覆盖后（旧记忆应标记为 inactive）")

    sub_banner("验证：搜索 '发送周报'")
    run_mem(["search", "发送周报", "--limit", "3"])


def demo_step_6_feishu_decision(port: int) -> None:
    """飞书决策抽取与入库"""
    banner("步骤 6：飞书方向 - 决策抽取与入库")
    print("  模拟飞书群聊中的团队决策自动沉淀为长期记忆\n")

    decisions = [
        ("以后 project-a 统一用 prod 部署，不再使用 staging", "部署环境决策"),
        ("周报以后发给 B，不再发给 A", "周报发送偏好"),
        ("5月10日前完成数据库迁移，统一用 MySQL 8.0", "数据库选型决策（含截止日期）"),
    ]
    for msg, desc in decisions:
        sub_banner(f"[{desc}] 飞书消息：{msg}")
        result = post_json(
            f"http://127.0.0.1:{port}/api/v1/feishu/decision/extract",
            {"message": msg},
        )
        print(f"  is_decision: {result.get('is_decision')}")
        print(f"  topic: {result.get('topic')}")
        print(f"  conclusion: {result.get('conclusion')}")
        print(f"  project: {result.get('project')}")
        print(f"  preferred_terms: {result.get('preferred_terms')}")
        print(f"  rejected_terms: {result.get('rejected_terms')}")
        print(f"  deadline: {result.get('deadline')}")
        print(f"  confidence: {result.get('confidence')}")

    show_db_summary("飞书决策入库后（3 条 project_decision 记忆）")


def demo_step_7_feishu_routing(port: int) -> None:
    """飞书消息路由演示"""
    banner("步骤 7：飞书方向 - 消息路由演示")
    print("  飞书机器人按消息类型自动路由：决策→入库、查询→检索、普通→忽略\n")

    messages = [
        ("以后统一用 Jest 做单元测试", "决策消息 → 自动入库并回复决策卡片"),
        ("查一下我们之前用什么部署环境", "查询消息 → 检索记忆并回复查询卡片"),
        ("今天天气不错", "普通消息 → 忽略"),
    ]
    for msg, expected in messages:
        sub_banner(f"消息：{msg}")
        result = post_json(
            f"http://127.0.0.1:{port}/api/v1/feishu/message/analyze",
            {"message": msg, "chat_id": "demo_chat_001"},
        )
        action = result.get("action", "unknown")
        print(f"  预期行为：{expected}")
        print(f"  实际路由：action={action}")


def demo_step_8_feishu_cards(port: int) -> None:
    """飞书交互卡片生成"""
    banner("步骤 8：飞书方向 - 交互卡片生成")
    print("  系统为不同类型的记忆生成对应的飞书交互卡片\n")

    # 查询记忆并展示卡片格式
    sub_banner("查询记忆（模拟飞书卡片内容）")
    result = get_json(f"http://127.0.0.1:{port}/api/v1/memory/?limit=5")
    memories = result if isinstance(result, list) else result.get("memories", result.get("items", []))

    for mem in memories[:3]:
        mem_type = mem.get("type", "unknown")
        content = mem.get("content", "")[:60]
        if mem_type == "project_decision":
            print(f"  [蓝色决策卡片] {content}")
            print(f"    → 包含：topic / conclusion / reason / deadline")
            print(f"    → 操作按钮：采纳 | 复制结论")
        elif mem_type == "cli_command":
            print(f"  [绿色命令卡片] {content}")
            print(f"    → 包含：命令内容 / 使用频次 / 成功率 / 目录")
            print(f"    → 操作按钮：复制命令 | 执行命令")
        else:
            print(f"  [紫色通用卡片] {content}")

    print("\n  卡片发送降级机制：交互卡片 → 文本消息（SDK 发送失败时自动降级）")


def demo_step_9_feishu_contradiction(port: int) -> None:
    """飞书决策矛盾更新"""
    banner("步骤 9：飞书方向 - 决策矛盾更新")
    print("  飞书群中的新决策自动覆盖旧决策\n")

    sub_banner("旧决策：以后部署用 staging")
    r1 = post_json(
        f"http://127.0.0.1:{port}/api/v1/feishu/decision/extract",
        {"message": "project-b 以后部署用 staging"},
    )
    print(f"  topic: {r1.get('topic')}, preferred: {r1.get('preferred_terms')}")

    sub_banner("新决策：更正，以后部署用 prod")
    r2 = post_json(
        f"http://127.0.0.1:{port}/api/v1/feishu/decision/extract",
        {"message": "更正，project-b 以后部署用 prod，不再使用 staging"},
    )
    print(f"  topic: {r2.get('topic')}, preferred: {r2.get('preferred_terms')}")
    print(f"  rejected: {r2.get('rejected_terms')}")

    sub_banner("验证：查询 project-b 的部署决策")
    result = post_json(
        f"http://127.0.0.1:{port}/api/v1/feishu/memory/query",
        {"query": "project-b 部署环境", "chat_id": "demo_chat_001"},
    )
    print(f"  查询结果：{json.dumps(result, ensure_ascii=False, indent=2)[:300]}")


def demo_step_10_cross_domain(port: int) -> None:
    """跨域检索演示"""
    banner("步骤 10：跨域联动 - 飞书决策影响 CLI 推荐")
    print("  飞书中确认 '用 prod' 后，CLI 推荐也会优先展示 prod 相关命令\n")

    sub_banner("CLI 搜索 '部署'（受飞书决策影响）")
    run_mem(["search", "部署", "--limit", "3"])

    sub_banner("CLI 搜索 'docker'（含使用频次排序）")
    run_mem(["search", "docker", "--limit", "3"])

    sub_banner("飞书查询 CLI 命令记忆（跨域检索）")
    result = post_json(
        f"http://127.0.0.1:{port}/api/v1/feishu/memory/query",
        {"query": "docker 启动 webapp", "chat_id": "demo_chat_001"},
    )
    print(f"  飞书端查询 CLI 命令：{json.dumps(result, ensure_ascii=False, indent=2)[:300]}")


def demo_step_5b_workflow(port: int) -> None:
    """工作流演示"""
    banner("步骤 5b：工作流保存与执行 (mem workflow)")
    print("  将多步操作保存为工作流，一键执行\n")

    sub_banner("保存工作流：健康检查")
    run_mem([
        "workflow", "save", "生产环境健康检查",
        "docker ps -a --filter name=api",
        "kubectl get pods -n prod",
        "curl -s http://api.prod.internal/health",
    ])

    sub_banner("列出工作流")
    run_mem(["workflow", "list"])


def demo_step_final_list(port: int) -> None:
    """最终状态"""
    banner("最终状态：全部记忆列表 (mem list)")
    run_mem(["list", "--limit", "20"])
    show_db_summary("演示结束")


# ── 主流程 ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="企业级记忆引擎 - 交互式演示")
    parser.add_argument("--reset-db", action="store_true", help="演示前清空数据库")
    parser.add_argument("--port", type=int, default=8000, help="后端端口")
    parser.add_argument("--skip-feishu", action="store_true", help="跳过飞书相关演示")
    args = parser.parse_args()

    os.chdir(WORKSPACE)
    backend_process = None

    try:
        # 初始化
        banner("初始化")
        if args.reset_db and DB_PATH.exists():
            DB_PATH.unlink()
            print(f"  已删除旧数据库：{DB_PATH}")
        run_command([sys.executable, "init_db.py"])
        print("  数据库初始化完成")

        # 启动后端
        sub_banner("启动后端服务")
        if BACKEND_LOG.exists():
            BACKEND_LOG.unlink()
        log_file = BACKEND_LOG.open("w", encoding="utf-8")
        backend_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=WORKSPACE, stdout=log_file, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        if not wait_backend(args.port):
            print("  后端启动超时，请检查日志：demo_backend.log")
            return
        print(f"  后端已启动：http://127.0.0.1:{args.port}")

        # 配置 CLI
        run_mem(["configure"], input_text=f"http://127.0.0.1:{args.port}/api/v1\n")

        # ── CLI 方向演示 ──
        banner("【第一部分：CLI 方向 - 面向开发者】")
        demo_step_1_memorize(args.port)
        demo_step_2_search(args.port)
        demo_step_3_watch(args.port)
        demo_step_4_suggest(args.port)
        demo_step_5_contradiction(args.port)
        demo_step_5b_workflow(args.port)

        # ── 飞书方向演示 ──
        if not args.skip_feishu:
            banner("【第二部分：飞书方向 - 面向团队】")
            demo_step_6_feishu_decision(args.port)
            demo_step_7_feishu_routing(args.port)
            demo_step_8_feishu_cards(args.port)
            demo_step_9_feishu_contradiction(args.port)

            banner("【第三部分：跨域联动】")
            demo_step_10_cross_domain(args.port)

        demo_step_final_list(args.port)

        banner("演示完成")
        print("  所有功能演示结束。")
        print("  如需重新运行：python 交付物/demo_runner.py --reset-db")

    finally:
        if backend_process and backend_process.poll() is None:
            backend_process.terminate()
            try:
                backend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_process.kill()
            print("\n  后端已关闭")


if __name__ == "__main__":
    main()
