"""
企业级记忆引擎 - 全自动演示日志脚本

用法：
    python 交付物/demo_auto_log.py --reset-db

自动运行所有演示步骤，输出同时打印到终端和写入 demo_output.log。
不需要手动操作，不需要录屏。
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

WORKSPACE = Path(__file__).resolve().parents[1]
DB_PATH = WORKSPACE / "db" / "memory.db"
LOG_PATH = WORKSPACE / "交付物" / "demo_output.log"
BACKEND_LOG = WORKSPACE / "demo_backend.log"

# ── 日志双写 ──────────────────────────────────────────────

class Tee:
    """同时输出到终端和日志文件"""
    def __init__(self, log_file):
        self.terminal = sys.stdout
        self.log = open(log_file, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


# ── 工具函数 ──────────────────────────────────────────────

def banner(text: str, char: str = "=", width: int = 60) -> None:
    print()
    print(char * width)
    print(f"  {text}")
    print(char * width)
    print()


def sub(text: str) -> None:
    print(f"\n--- {text} ---")


def pause(seconds: float, msg: str = "") -> None:
    if msg:
        print(f"  {msg}")
    time.sleep(seconds)


def run_cmd(args: list[str], input_text: str = None) -> str:
    result = subprocess.run(
        args, input=input_text, text=True, cwd=WORKSPACE,
        encoding="utf-8", errors="replace", capture_output=True,
    )
    output = (result.stdout + result.stderr).strip()
    print(f"  $ {' '.join(args)}")
    if output:
        for line in output.split("\n"):
            print(f"  {line}")
    print()
    return output


def run_mem(args: list[str]) -> str:
    return run_cmd([sys.executable, "-m", "cli.main", *args])


def post_api(path: str, payload: dict) -> dict:
    url = f"http://127.0.0.1:8000/api/v1{path}"
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ❌ API 失败: {e}")
        return {}
    print(f"  POST {path}")
    print(f"  → {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
    print()
    return result


def get_api(path: str) -> dict:
    url = f"http://127.0.0.1:8000/api/v1{path}"
    try:
        with urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ❌ API 失败: {e}")
        return {}


def wait_backend(port: int, timeout: int = 30) -> bool:
    for _ in range(timeout):
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


# ── 演示步骤 ──────────────────────────────────────────────

def step_01_memorize():
    banner("步骤 1：显式记忆注入 (mem memorize)")
    print("  开发者将常用命令保存到记忆系统\n")

    commands = [
        ("docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2", "docker启动命令"),
        ("kubectl logs deploy/api-server -n prod --tail=200 -f", "k8s排障命令"),
        ("pg_dump -h 10.0.8.12 -U ops -d orders_prod -F c -f backup/orders_prod.dump", "数据库备份命令"),
        ("rsync -avz --delete dist/ deploy@10.0.8.30:/srv/www/console/", "发布命令"),
    ]
    for cmd, type_name in commands:
        run_mem(["memorize", cmd, "--type", type_name])
        pause(0.5)


def step_02_search():
    banner("步骤 2：语义搜索 (mem search)")
    print("  用自然语言描述意图，系统找到最匹配的命令\n")

    queries = ["启动webapp容器", "查看生产api日志", "备份订单数据库"]
    for q in queries:
        sub(f"搜索：{q}")
        run_mem(["search", q, "--limit", "3"])
        pause(1.0)


def step_03_suggest():
    banner("步骤 3：前缀推荐 (mem suggest)")
    for prefix in ["docker", "kubectl"]:
        sub(f"前缀：{prefix}")
        run_mem(["suggest", prefix, "--limit", "5"])
        pause(0.5)


def step_04_watch():
    banner("步骤 4：高频命令记录（模拟 mem watch）")
    print("  模拟扫描 shell 历史，自动记录高频命令\n")

    commands = [
        ("docker ps -a --filter status=exited", 5),
        ("git log --oneline -10", 8),
        ("npm run build", 3),
    ]
    for cmd, count in commands:
        post_api("/cli/command/record", {
            "command": cmd, "count": count,
            "shell": "powershell", "directory": str(WORKSPACE),
        })
        pause(0.5)


def step_05_contradiction():
    banner("步骤 5：矛盾更新演示")
    print("  先记录旧决策，再用新决策覆盖\n")

    sub("写入旧记忆")
    run_mem(["memorize", "以后周报发给 A：python scripts/send_weekly.py --to a@example.com", "--type", "周报发送命令"])

    sub("写入新记忆（覆盖旧记忆）")
    run_mem(["memorize", "不对，以后周报发给 B：python scripts/send_weekly.py --to b@example.com", "--type", "周报发送命令"])

    sub("验证：搜索 '发送周报'")
    run_mem(["search", "发送周报", "--limit", "3"])
    pause(1.0)


def step_06_workflow():
    banner("步骤 6：工作流保存与执行 (mem workflow)")
    sub("保存工作流")
    run_mem(["workflow", "save", "生产环境健康检查",
             "docker ps -a --filter name=api",
             "kubectl get pods -n prod",
             "curl -s http://api.prod.internal/health"])

    sub("列出工作流")
    run_mem(["workflow", "list"])


def step_07_feishu_decision():
    banner("步骤 7：飞书决策抽取与入库")
    print("  模拟飞书群聊中的团队决策自动沉淀\n")

    decisions = [
        ("以后 project-a 统一用 prod 部署，不再使用 staging", "部署环境决策"),
        ("周报以后发给 B，不再发给 A", "周报发送偏好"),
        ("5月10日前完成数据库迁移，统一用 MySQL 8.0", "数据库选型决策（含截止日期）"),
    ]
    for msg, desc in decisions:
        sub(f"[{desc}] {msg}")
        r = post_api("/feishu/decision/extract", {"content": msg})
        pause(1.0)


def step_08_routing():
    banner("步骤 8：飞书消息路由演示")
    print("  决策→入库、查询→检索、普通→忽略\n")

    messages = [
        ("以后统一用 Jest 做单元测试", "决策消息"),
        ("查一下我们之前用什么部署环境", "查询消息"),
        ("今天天气不错", "普通消息"),
    ]
    for msg, desc in messages:
        sub(f"[{desc}] {msg}")
        post_api("/feishu/message/analyze", {"content": msg, "chat_id": "demo_chat_001"})
        pause(1.0)


def step_09_feishu_contradiction():
    banner("步骤 9：飞书决策矛盾更新")
    sub("旧决策：project-b 以后部署用 staging")
    post_api("/feishu/decision/extract", {"content": "project-b 以后部署用 staging"})
    pause(1.0)

    sub("新决策：更正，以后部署用 prod")
    post_api("/feishu/decision/extract", {"content": "更正，project-b 以后部署用 prod，不再使用 staging"})
    pause(1.0)

    sub("验证：查询 project-b 部署决策")
    post_api("/feishu/memory/query", {"query": "project-b 部署环境", "chat_id": "demo_chat_001"})


def step_10_cross_domain():
    banner("步骤 10：跨域联动")
    sub("飞书决策影响 CLI 推荐")
    run_mem(["search", "部署", "--limit", "3"])

    sub("CLI 搜索 docker")
    run_mem(["search", "docker", "--limit", "3"])

    sub("飞书查询 CLI 命令记忆")
    post_api("/feishu/memory/query", {"query": "docker 启动 webapp", "chat_id": "demo_chat_001"})


def step_11_health():
    banner("步骤 11：健康检查")
    r = get_api("/health/detailed")
    print(f"  健康状态：{json.dumps(r, ensure_ascii=False, indent=2)[:500]}")
    print()


def step_12_list():
    banner("步骤 12：全部记忆列表")
    run_mem(["list", "--limit", "20"])


# ── 主流程 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="全自动演示日志")
    parser.add_argument("--reset-db", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    os.chdir(WORKSPACE)

    # 双写日志
    tee = Tee(LOG_PATH)
    sys.stdout = tee

    print(f"演示开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"日志文件：{LOG_PATH}")

    backend_process = None
    try:
        # 初始化数据库
        banner("初始化")
        if args.reset_db and DB_PATH.exists():
            DB_PATH.unlink()
            print(f"  已删除旧数据库：{DB_PATH}")
        run_cmd([sys.executable, "init_db.py"])

        # 启动后端
        sub("启动后端服务")
        if BACKEND_LOG.exists():
            BACKEND_LOG.unlink()
        log_f = BACKEND_LOG.open("w", encoding="utf-8")
        backend_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=WORKSPACE, stdout=log_f, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        if not wait_backend(args.port):
            print("  ❌ 后端启动超时")
            return
        print(f"  后端已启动：http://127.0.0.1:{args.port}")

        # 配置 CLI
        run_mem(["configure"], )
        # 直接写配置文件
        from pathlib import Path as P
        cfg_dir = P.home() / ".mem_agent"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "config.ini").write_text(
            f"[default]\napi_base = http://127.0.0.1:{args.port}/api/v1\n",
            encoding="utf-8",
        )
        print(f"  CLI 已配置：http://127.0.0.1:{args.port}/api/v1")

        # ── CLI 方向 ──
        banner("【Part 1：CLI 方向 - 面向开发者】", char="#")
        step_01_memorize()
        step_02_search()
        step_03_suggest()
        step_04_watch()
        step_05_contradiction()
        step_06_workflow()

        # ── 飞书方向 ──
        banner("【Part 2：飞书方向 - 面向团队】", char="#")
        step_07_feishu_decision()
        step_08_routing()
        step_09_feishu_contradiction()

        # ── 跨域联动 ──
        banner("【Part 3：跨域联动】", char="#")
        step_10_cross_domain()

        # ── 系统监控 ──
        banner("【Part 4：系统监控】", char="#")
        step_11_health()
        step_12_list()

        # ── 收尾 ──
        banner("演示完成", char="=")
        print(f"演示结束时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"完整日志已保存到：{LOG_PATH}")

    finally:
        if backend_process and backend_process.poll() is None:
            backend_process.terminate()
            try:
                backend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_process.kill()
            print("\n  后端已关闭")
        sys.stdout = tee.terminal
        tee.close()
        print(f"\n日志已保存到：{LOG_PATH}")


if __name__ == "__main__":
    main()
