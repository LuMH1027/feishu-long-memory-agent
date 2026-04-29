import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


WORKSPACE = Path(__file__).resolve().parents[1]
DB_PATH = WORKSPACE / "db" / "memory.db"
BACKEND_LOG = WORKSPACE / "demo_backend.log"


def print_step(message: str) -> None:
    print()
    print(f"========== {message} ==========")


def run_command(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print()
    print("> " + " ".join(args))
    result = subprocess.run(
        args,
        input=input_text,
        text=True,
        cwd=WORKSPACE,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"命令执行失败：{' '.join(args)}")
    return result


def run_mem(args: list[str], *, input_text: str | None = None) -> None:
    run_command([sys.executable, "-m", "cli.main", *args], input_text=input_text)


def wait_backend(port: int) -> None:
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(30):
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"后端没有按时启动：{url}，请查看日志：{BACKEND_LOG}")


def show_db(title: str) -> None:
    print_step(f"数据库快照：{title}")
    print(f"数据库文件：{DB_PATH}")
    if not DB_PATH.exists():
        print("数据库文件不存在。")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' order by name")]
    print("当前数据表：" + (", ".join(tables) if tables else "空"))
    if "memories" not in tables:
        print("memories 表不存在。")
        conn.close()
        return

    rows = conn.execute(
        """
        select id, type, source, description, content, memory_metadata, hit_count, created_at, updated_at
        from memories
        order by created_at, id
        """
    ).fetchall()
    print(f"memories 表记录数：{len(rows)}")

    for index, row in enumerate(rows, 1):
        raw_metadata = row["memory_metadata"] or "{}"
        try:
            metadata = json.loads(raw_metadata)
        except Exception:
            metadata = {"_raw": raw_metadata}

        content = row["content"] or ""
        if len(content) > 130:
            content = content[:127] + "..."

        print(f"\n[{index}] id={row['id']} type={row['type']} source={row['source']} hit_count={row['hit_count']}")
        print(f"    内容：{content}")
        print(f"    描述：{row['description']}")
        interesting = {
            key: metadata.get(key)
            for key in [
                "count",
                "shell",
                "directory",
                "directories",
                "command_pattern",
                "success_count",
                "failure_count",
                "last_exit_code",
                "status",
                "topic_key",
                "supersedes",
                "superseded_by",
                "name",
                "steps",
            ]
            if key in metadata
        }
        print("    关键元数据：" + json.dumps(interesting, ensure_ascii=False, indent=2))
    conn.close()


def configure_cli(port: int) -> None:
    print_step("配置 CLI 的后端 API 地址")
    run_mem(["configure"], input_text=f"http://127.0.0.1:{port}/api/v1\n")


def post_json(url: str, payload: dict) -> None:
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI 记忆系统完整中文演示脚本")
    parser.add_argument("--reset-db", action="store_true", help="演示前删除 db/memory.db")
    parser.add_argument("--port", type=int, default=8000, help="后端端口")
    args = parser.parse_args()

    os.chdir(WORKSPACE)
    backend_process: subprocess.Popen | None = None

    try:
        print_step("初始化数据库")
        if args.reset_db and DB_PATH.exists():
            DB_PATH.unlink()
            print(f"已删除旧数据库：{DB_PATH}")
        run_command([sys.executable, "init_db.py"])
        show_db("初始化后")

        print_step("启动后端服务")
        if BACKEND_LOG.exists():
            BACKEND_LOG.unlink()
        log_file = BACKEND_LOG.open("w", encoding="utf-8")
        backend_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=WORKSPACE,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        wait_backend(args.port)
        print(f"后端已启动：http://127.0.0.1:{args.port}")

        configure_cli(args.port)

        print_step("1. 显式记忆：mem memorize")
        run_mem(
            [
                "memorize",
                "docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2",
                "--type",
                "docker启动命令",
            ]
        )
        show_db("主动记忆写入后")

        print_step("2. 搜索记忆：mem search")
        run_mem(["search", "webapp docker 8080", "--limit", "3", "--copy"])
        show_db("搜索后，观察 hit_count 是否增加")

        print_step("3. 高频命令记录：模拟 mem watch 扫描历史命令")
        post_json(
            f"http://127.0.0.1:{args.port}/api/v1/cli/command/record",
            {
                "command": "docker ps -a --filter status=exited",
                "count": 3,
                "shell": "powershell",
                "directory": str(WORKSPACE),
            },
        )
        show_db("高频命令记录后")

        print_step("4. 前缀推荐：mem suggest")
        run_mem(["suggest", "docker", "--limit", "5"])
        show_db("前缀推荐后")

        print_step("5. 执行反馈：mem search --execute")
        run_mem(["memorize", "python -c \"print('cli demo execution ok')\"", "--type", "cli_command"])
        run_mem(["search", "cli demo execution", "--limit", "1", "--execute"])
        show_db("执行反馈后，观察 success_count 和 last_exit_code")

        print_step("6. 保存工作流：mem workflow save")
        run_mem(
            [
                "workflow",
                "save",
                "demo健康检查",
                "python -c \"print('step1 health')\"",
                "python -c \"print('step2 done')\"",
            ]
        )
        show_db("工作流保存后，观察 type=cli_workflow 的记录")

        print_step("7. 执行工作流：mem workflow run")
        run_mem(["workflow", "run", "demo健康检查"], input_text="y\ny\n")
        show_db("工作流执行后，观察每个 step 的执行反馈记录")

        print_step("8. 矛盾更新：A -> B")
        run_mem(
            [
                "memorize",
                "以后周报发给 A：python scripts/send_weekly.py --to a@example.com",
                "--type",
                "周报发送命令",
            ]
        )
        show_db("旧记忆写入后")
        run_mem(
            [
                "memorize",
                "不对，以后周报发给 B：python scripts/send_weekly.py --to b@example.com",
                "--type",
                "周报发送命令",
            ]
        )
        show_db("新记忆覆盖后，旧记忆应为 inactive，新记忆应 supersedes 旧记忆")

        print_step("9. 最终列表：mem list")
        run_mem(["list", "--limit", "20"])
        show_db("演示结束后的最终状态")

        print_step("演示完成")
        print("如果想清空数据库重新演示，可以运行：")
        print("python scripts/demo_cli_full_flow.py --reset-db")
    finally:
        if backend_process and backend_process.poll() is None:
            print_step("关闭演示后端")
            backend_process.terminate()
            try:
                backend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_process.kill()
            print(f"已关闭后端进程：{backend_process.pid}")


if __name__ == "__main__":
    main()
