"""
企业级记忆引擎 - 录屏自动化演示脚本

用法：
    # 终端 1：启动后端
    python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

    # 终端 2：配置 CLI 后运行本脚本
    python -m cli.main configure
    # 输入: http://127.0.0.1:8000/api/v1
    python 交付物/demo_record.py --reset-db

    # 终端 3（飞书群聊演示时启动）：
    python scripts/run_feishu_sdk_events.py

脚本会自动执行可以自动化的步骤，到需要手动操作的地方会暂停并提示。
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

WORKSPACE = Path(__file__).resolve().parents[1]
DB_PATH = WORKSPACE / "db" / "memory.db"

# ── 工具函数 ──────────────────────────────────────────────

def banner(text: str, char: str = "=", width: int = 60) -> None:
    print()
    print(char * width)
    print(f"  {text}")
    print(char * width)
    print()


def subtitle(text: str) -> None:
    """打印字幕（视频后期叠加用）"""
    print(f"  【字幕】{text}")
    print()


def manual_banner(step_name: str, instructions: list[str]) -> None:
    """打印手动操作提示"""
    print()
    print("+" + "=" * 58 + "+")
    print(f"|  👆 手动操作：{step_name:<43}|")
    print("+" + "=" * 58 + "+")
    for i, inst in enumerate(instructions, 1):
        print(f"  {i}. {inst}")
    print()
    input("  >>> 操作完成后按回车继续 <<<")
    print()


def pause(seconds: float, msg: str = "") -> None:
    if msg:
        print(f"  {msg}")
    time.sleep(seconds)


def run_mem(args: list[str], *, show_output: bool = True) -> str:
    """运行 CLI 命令，返回输出"""
    cmd = [sys.executable, "-m", "cli.main", *args]
    result = subprocess.run(
        cmd, text=True, cwd=WORKSPACE,
        encoding="utf-8", errors="replace",
        capture_output=True,
    )
    output = result.stdout.strip()
    if show_output:
        print(f"  $ python -m cli.main {' '.join(args)}")
        if output:
            for line in output.split("\n"):
                print(f"  {line}")
        print()
    return output


def post_api(path: str, payload: dict, *, show_output: bool = True) -> dict:
    """发送 POST 请求，返回 JSON"""
    url = f"http://127.0.0.1:8000/api/v1{path}"
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ❌ API 请求失败: {e}")
        return {}

    if show_output:
        print(f"  POST {path}")
        print(f"  → {json.dumps(result, ensure_ascii=False, indent=2)}")
        print()
    return result


# ── 自动化阶段 ──────────────────────────────────────────────

def phase_1_cli_memorize() -> None:
    """第一阶段：CLI 记忆注入（自动）"""
    banner("第一阶段：CLI 记忆注入")
    subtitle("把常用的长命令存进记忆系统，以后再也不用手打了")

    commands = [
        ("docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2", "docker启动命令"),
        ("kubectl logs deploy/api-server -n prod --tail=200 -f", "k8s排障命令"),
        ("pg_dump -h 10.0.8.12 -U ops -d orders_prod -F c -f backup/orders_prod.dump", "数据库备份命令"),
        ("rsync -avz --delete dist/ deploy@10.0.8.30:/srv/www/console/", "发布命令"),
    ]
    for cmd, type_name in commands:
        run_mem(["memorize", cmd, "--type", type_name])
        pause(1.0)

    subtitle("四条常用运维命令已入库")
    pause(2.0)


def phase_2_feishu_decisions() -> None:
    """第二阶段：飞书决策注入（自动）"""
    banner("第二阶段：飞书决策自动抽取")
    subtitle("模拟飞书群聊消息，机器人自动提取团队决策")

    decisions = [
        "以后 project-a 统一用 prod 部署，不再使用 staging",
        "周报以后发给 B，不再发给 A",
        "5月10日前完成数据库迁移，统一用 MySQL 8.0",
    ]
    for msg in decisions:
        subtitle(f"飞书群消息：「{msg}」")
        post_api("/feishu/decision/extract", {"content": msg})
        pause(2.5)

    subtitle("三条团队决策自动入库，无需人工整理")
    pause(2.0)


def phase_3_prefix_suggest() -> None:
    """第三阶段：前缀推荐（自动）"""
    banner("第三阶段：前缀推荐")
    subtitle("输入命令前缀，智能排序推荐")

    for prefix in ["docker", "kubectl"]:
        run_mem(["suggest", prefix, "--limit", "5"])
        pause(2.0)

    subtitle("比 Tab 补全更聪明 —— 它知道你最常用哪个")
    pause(2.0)


def phase_4_message_routing() -> None:
    """第四阶段：消息路由（自动）"""
    banner("第四阶段：飞书消息路由")
    subtitle("三种消息，自动路由：决策入库、查询检索、闲聊忽略")

    messages = [
        ("以后统一用 Jest 做单元测试", "决策消息 → 自动入库"),
        ("查一下我们之前用什么部署环境", "查询消息 → 检索记忆"),
        ("今天天气不错", "普通消息 → 忽略"),
    ]
    for msg, desc in messages:
        subtitle(f"「{msg}」→ {desc}")
        post_api("/feishu/message/analyze", {"content": msg, "chat_id": "demo_chat_001"})
        pause(2.5)

    subtitle("智能路由，不浪费资源")
    pause(2.0)


def phase_5_feishu_contradiction() -> None:
    """第五阶段：飞书矛盾更新（自动）"""
    banner("第五阶段：飞书决策矛盾更新")
    subtitle("新决策自动覆盖旧决策，团队永远执行最新方案")

    subtitle("旧决策：project-b 以后部署用 staging")
    post_api("/feishu/decision/extract", {"content": "project-b 以后部署用 staging"})
    pause(2.0)

    subtitle("新决策：更正，project-b 以后部署用 prod，不再使用 staging")
    post_api("/feishu/decision/extract", {"content": "更正，project-b 以后部署用 prod，不再使用 staging"})
    pause(2.0)

    subtitle("旧决策自动失效，只保留最新方案")
    pause(2.0)


def phase_6_query_and_cross_domain() -> None:
    """第六阶段：历史查询 + 跨域检索（自动）"""
    banner("第六阶段：历史查询 & 跨域联动")
    subtitle("飞书决策 → CLI 推荐，CLI 命令 → 飞书查询")

    subtitle("查询：飞书群中查「部署环境」相关决策")
    post_api("/feishu/memory/query", {"query": "部署环境", "chat_id": "demo_chat_001"})
    pause(2.5)

    subtitle("跨域：飞书群里查「docker 启动 webapp」→ 命中 CLI 命令记忆")
    post_api("/feishu/memory/query", {"query": "docker 启动 webapp", "chat_id": "demo_chat_001"})
    pause(2.5)

    subtitle("两个方向，一个记忆池，双向联动")
    pause(2.0)


# ── 主流程 ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="企业级记忆引擎 - 录屏自动化演示")
    parser.add_argument("--reset-db", action="store_true", help="演示前清空数据库")
    parser.add_argument("--skip-feishu", action="store_true", help="跳过飞书相关步骤")
    args = parser.parse_args()

    os.chdir(WORKSPACE)

    # 初始化
    banner("初始化")
    if args.reset_db and DB_PATH.exists():
        try:
            DB_PATH.unlink()
            print(f"  已删除旧数据库：{DB_PATH}")
        except PermissionError:
            print(f"  ❌ 数据库被占用，请先关闭后端服务（终端 1 的 uvicorn），再重新运行本脚本")
            print(f"  提示：按 Ctrl+C 关闭后端，然后重新运行 python 交付物/demo_record.py --reset-db")
            sys.exit(1)
    subprocess.run([sys.executable, "init_db.py"], cwd=WORKSPACE)
    print("  数据库初始化完成")
    pause(1.0)

    # ═══════════════════════════════════════════════════════
    #  Part 1：CLI 方向
    # ═══════════════════════════════════════════════════════

    banner("【Part 1：CLI 记忆引擎 - 面向开发者】", char="#")

    # ── 自动段 1：CLI 记忆注入 ──
    phase_1_cli_memorize()

    # ── 手动段 1：语义搜索 ──
    banner("【手动操作】语义搜索", char="*")
    subtitle("用自然语言描述意图，AI 语义检索找到最匹配的命令")
    manual_banner("语义搜索", [
        "在终端输入：python -m cli.main search \"启动webapp容器\"",
        "观察：系统用语义理解找到了 docker 命令",
        "再输入：python -m cli.main search \"查看生产环境api日志\"",
        "观察：换个说法也能找到 kubectl 命令",
    ])
    subtitle("怎么说都能找到，不用记参数，不用翻文档")

    # ── 自动段 2：前缀推荐 ──
    phase_3_prefix_suggest()

    # ── 手动段 2：矛盾更新 ──
    banner("【手动操作】矛盾更新", char="*")
    subtitle("说「不对，改成 XXX」，系统自动识别纠正意图")
    manual_banner("矛盾更新", [
        "输入旧记忆：",
        "  python -m cli.main memorize \"以后周报发给 A：python scripts/send_weekly.py --to a@example.com\" --type \"周报发送命令\"",
        "",
        "输入新记忆（带否定词）：",
        "  python -m cli.main memorize \"不对，以后周报发给 B：python scripts/send_weekly.py --to b@example.com\" --type \"周报发送命令\"",
        "",
        "搜索验证：",
        "  python -m cli.main search \"发送周报\"",
        "观察：只显示发给 B 的命令，旧记忆已被自动覆盖",
    ])
    subtitle("旧记忆自动作废，只保留最新决策")

    # ── 手动段 3：工作流 ──
    banner("【手动操作】工作流", char="*")
    subtitle("多步操作合成一个工作流，一键执行")
    manual_banner("工作流保存与查看", [
        "保存工作流：",
        "  python -m cli.main workflow save \"生产环境健康检查\" \"docker ps -a --filter name=api\" \"kubectl get pods -n prod\" \"curl -s http://api.prod.internal/health\"",
        "",
        "列出工作流：",
        "  python -m cli.main workflow list",
    ])
    subtitle("三步操作合成一个工作流，下次一键执行")

    # ═══════════════════════════════════════════════════════
    #  Part 2：飞书方向
    # ═══════════════════════════════════════════════════════

    if not args.skip_feishu:
        banner("【Part 2：飞书团队记忆 - 面向团队】", char="#")

        # ── 自动段 3：飞书决策注入 ──
        phase_2_feishu_decisions()

        # ── 自动段 4：消息路由 ──
        phase_4_message_routing()

        # ── 自动段 5：飞书矛盾更新 ──
        phase_5_feishu_contradiction()

        # ── 自动段 6：历史查询 + 跨域检索 ──
        phase_6_query_and_cross_domain()

    # ── 手动段 4：跨域 CLI 搜索 ──
    banner("【手动操作】跨域联动 - CLI 搜索", char="*")
    subtitle("飞书决策影响 CLI 推荐")
    manual_banner("跨域搜索", [
        "搜索「部署」：",
        "  python -m cli.main search \"部署\"",
        "观察：飞书入库的部署决策也会出现在搜索结果中",
        "",
        "搜索「docker」：",
        "  python -m cli.main search \"docker\"",
        "观察：CLI 命令和飞书决策共享同一个记忆池",
    ])
    subtitle("飞书决策 → CLI 推荐，双向联动")

    # ═══════════════════════════════════════════════════════
    #  Part 3：飞书群聊真实交互
    # ═══════════════════════════════════════════════════════

    banner("【Part 3：飞书群聊真实交互】", char="#")
    subtitle("在飞书群里 @机器人，看它自动回复决策卡片")

    manual_banner("启动飞书机器人监听", [
        "打开一个新终端窗口（终端 3），输入：",
        "  cd e:\\feishu-long-memory-agent",
        "  python scripts/run_feishu_sdk_events.py",
        "",
        "等待看到 WebSocket 连接成功的日志",
        "然后切回录屏画面，继续下一步",
    ])

    manual_banner("飞书群聊 - 决策沉淀", [
        "打开飞书客户端，进入测试群",
        "",
        "发送第 1 条消息：",
        "  以后前端统一用 TypeScript，不再使用 JavaScript",
        "观察：机器人自动回复蓝色决策卡片",
        "",
        "发送第 2 条消息：",
        "  API 接口统一用 RESTful，废弃 GraphQL",
        "观察：机器人自动回复蓝色决策卡片",
        "",
        "发送第 3 条消息（含截止日期）：",
        "  5月15日前完成代码规范统一，项目名 project-x",
        "观察：机器人回复的卡片中包含截止日期",
    ])
    subtitle("机器人自动识别决策意图，回复结构化卡片")

    manual_banner("飞书群聊 - 决策矛盾更新", [
        "在飞书群中发送：",
        "  更正，前端统一用 Vue3，不再使用 TypeScript",
        "观察：机器人回复新决策卡片",
        "",
        "再发送查询消息：",
        "  @机器人 查一下前端用什么框架",
        "观察：机器人返回最新决策（Vue3），旧的 TypeScript 决策已被覆盖",
    ])
    subtitle("新决策自动覆盖旧决策，团队永远执行最新方案")

    manual_banner("飞书群聊 - 查询 CLI 命令记忆", [
        "在飞书群中发送：",
        "  @机器人 怎么启动 webapp 容器",
        "观察：机器人返回绿色 CLI 命令卡片",
        "这是 CLI 记忆被飞书查询命中的跨域联动效果",
    ])
    subtitle("飞书群里问一句，机器人给出 CLI 里存的命令")

    # ═══════════════════════════════════════════════════════
    #  Part 4：系统监控 & 收尾
    # ═══════════════════════════════════════════════════════

    banner("【Part 4：系统监控 & 收尾】", char="#")

    # ── 手动段：健康检查 + 数据库 ──
    banner("【手动操作】健康检查 & 数据库全貌", char="*")
    subtitle("生产级的可观测性")
    manual_banner("健康检查与数据库", [
        "在浏览器打开：http://127.0.0.1:8000/health/detailed",
        "观察：数据库、向量库、Embedding 服务全部健康",
        "",
        "在终端输入：",
        "  python scripts/view_database.py",
        "观察：所有记忆的统计信息和详细内容",
    ])
    subtitle("数据库、向量库、Embedding 服务，全部健康")

    # ── 收尾 ──
    banner("演示完成", char="=")
    subtitle("企业级记忆引擎 —— CLI 记命令，飞书记决策，一个记忆池，双向联动")
    print("  ┌─────────────────────────────────────────┐")
    print("  │         企业级记忆引擎                    │")
    print("  │                                         │")
    print("  │  CLI 方向：                              │")
    print("  │  · 抗干扰 Hit@1: 100%                   │")
    print("  │  · 矛盾更新胜出率: 100%                  │")
    print("  │  · 字符输入减少: 80.3%                   │")
    print("  │  · 耗时减少: 78.2%                      │")
    print("  │                                         │")
    print("  │  飞书方向：                              │")
    print("  │  · 决策抽取准确率: 100%                   │")
    print("  │  · 消息路由正确性: 100%                   │")
    print("  │  · 卡片模板生成: 100% (21/21)            │")
    print("  │                                         │")
    print("  │  测试：222/223 passed (99.6%)            │")
    print("  └─────────────────────────────────────────┘")
    print()


if __name__ == "__main__":
    main()
