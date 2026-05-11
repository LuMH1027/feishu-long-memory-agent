#!/usr/bin/env python3
"""搜索性能基准测试 —— 量化搜索性能数据"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE = Path(__file__).resolve().parents[1]

SAMPLE_QUERIES = [
    "部署", "启动容器", "查看日志", "备份数据库", "发布",
    "docker", "kubectl", "健康检查", "迁移", "重启服务",
    "配置环境", "安装依赖", "测试", "监控", "回滚",
    "连接数据库", "清缓存", "编译", "打包", "部署到生产",
]

SEED_COMMANDS = [
    "docker run -p 8080:80 -v /data:/app/data --name webapp my-image:1.2",
    "kubectl logs deploy/api-server -n prod --tail=200 -f",
    "pg_dump -h 10.0.8.12 -U ops -d orders_prod -F c -f backup/orders_prod.dump",
    "rsync -avz --delete dist/ deploy@10.0.8.30:/srv/www/console/",
    "docker-compose -f prod.yml up -d",
    "kubectl get pods -n prod --sort-by=.status.startTime",
    "npm run build -- --mode production",
    "git log --oneline -20 --graph --all",
    "curl -s http://api.prod.internal/health | jq .status",
    "systemctl restart nginx",
]


def ensure_backend(port: int) -> bool:
    """确保后端运行，若未运行则启动"""
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            if r.status == 200:
                return True
    except Exception:
        pass

    print(f"启动后端 (port={port})...")
    backend_log = WORKSPACE / "scripts" / "benchmark_backend.log"
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=WORKSPACE,
        stdout=backend_log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for _ in range(30):
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    print("  后端已启动")
                    return True
        except Exception:
            time.sleep(1)
    print("  后端启动超时")
    return False


def seed_memories(port: int, count: int) -> int:
    """预填测试记忆数据"""
    base_url = f"http://127.0.0.1:{port}/api/v1"
    seeded = 0
    for i in range(count):
        cmd_idx = i % len(SEED_COMMANDS)
        variation = f" (变体{i // len(SEED_COMMANDS)})" if i >= len(SEED_COMMANDS) else ""
        payload = {
            "content": SEED_COMMANDS[cmd_idx] + variation,
            "type": "cli_command",
            "description": f"测试命令 {i}",
            "source": "cli",
            "user_id": "benchmark",
        }
        try:
            req = Request(
                f"{base_url}/memory/",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as r:
                if r.status == 200:
                    seeded += 1
        except Exception:
            pass
    return seeded


def run_benchmark(port: int, queries: list[str], rounds: int) -> dict:
    """运行搜索基准测试"""
    base_url = f"http://127.0.0.1:{port}/api/v1"
    timings: list[float] = []

    for rnd in range(rounds):
        for q in queries:
            start = time.perf_counter()
            try:
                req = Request(
                    f"{base_url}/memory/search?query={q}&limit=5",
                    headers={"Content-Type": "application/json"},
                    method="GET",
                )
                with urlopen(req, timeout=15) as r:
                    r.read()
            except Exception:
                pass
            elapsed = (time.perf_counter() - start) * 1000  # ms
            timings.append(elapsed)

    # 独立测量 Embedding 耗时
    embedding_timings: list[float] = []
    try:
        from core.utils.embedding import get_embedding
        for q in queries[:5]:
            start = time.perf_counter()
            get_embedding(q)
            embedding_timings.append((time.perf_counter() - start) * 1000)
    except Exception:
        pass

    timings.sort()
    n = len(timings)

    return {
        "total_queries": n,
        "p50": timings[n // 2],
        "p95": timings[int(n * 0.95)],
        "p99": timings[int(n * 0.99)],
        "min": timings[0],
        "max": timings[-1],
        "mean": statistics.mean(timings),
        "embedding_avg_ms": statistics.mean(embedding_timings) if embedding_timings else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="搜索性能基准测试")
    parser.add_argument("--port", type=int, default=8000, help="后端端口")
    parser.add_argument("--seed", type=int, default=0, metavar="N",
                        help="预填 N 条测试记忆 (0=不填)")
    parser.add_argument("--queries", type=int, default=20, help="查询数量")
    parser.add_argument("--rounds", type=int, default=5, help="轮数")
    args = parser.parse_args()

    print("=" * 50)
    print("  搜索性能基准测试")
    print("=" * 50)
    print()

    # 环境检查
    if not ensure_backend(args.port):
        print("❌ 后端未就绪")
        return 1

    # 预填数据
    if args.seed > 0:
        print(f"预填 {args.seed} 条测试记忆...")
        seeded = seed_memories(args.port, args.seed)
        print(f"  已填入 {seeded} 条\n")

    # 预热
    print("预热中...")
    run_benchmark(args.port, SAMPLE_QUERIES[:3], 2)
    print()

    # 正式测试
    queries = SAMPLE_QUERIES[:min(args.queries, len(SAMPLE_QUERIES))]
    print(f"运行基准 ({len(queries)} queries × {args.rounds} rounds)...")
    result = run_benchmark(args.port, queries, args.rounds)

    # 结果展示
    print()
    print("=" * 50)
    print(f"  搜索性能基准 ({result['total_queries']} queries, {args.seed}条记忆库):")
    print(f"    p50: {result['p50']:.1f}ms | p95: {result['p95']:.1f}ms | p99: {result['p99']:.1f}ms")
    print(f"    min: {result['min']:.1f}ms | max: {result['max']:.1f}ms | avg: {result['mean']:.1f}ms")
    if result["embedding_avg_ms"] > 0:
        db_avg = result["mean"] - result["embedding_avg_ms"]
        print(f"    Embedding: avg {result['embedding_avg_ms']:.1f}ms | DB查询: avg {max(db_avg, 0):.1f}ms")
    print("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
