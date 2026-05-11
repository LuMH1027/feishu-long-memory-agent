#!/usr/bin/env python3
"""数据库重置脚本 —— 独立于后端启动，可在任意时机执行"""

import argparse
import os
import shutil
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE = Path(__file__).resolve().parents[1]


def reset_relational(db_url: str) -> None:
    """重置关系型数据库"""
    if "sqlite" not in db_url:
        # 远程数据库：清空表内容
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM decision_memories"))
            conn.execute(text("DELETE FROM memories"))
        engine.dispose()
        print("✅ 关系型数据库表已清空")
        return

    db_rel = db_url.replace("sqlite:///", "")
    db_path = WORKSPACE / db_rel
    if db_path.exists():
        db_path.unlink()
        print(f"✅ 已删除: {db_path}")
    else:
        print(f"⚠️  数据库文件不存在: {db_path}")


def reset_vector(vector_path: str) -> None:
    """重置向量数据库"""
    v_path = WORKSPACE / vector_path
    if v_path.exists():
        shutil.rmtree(v_path)
        print(f"✅ 已删除: {v_path}")
    else:
        print(f"⚠️  向量库目录不存在: {v_path}")


def run_init() -> None:
    """运行 init_db.py 重建数据库"""
    import subprocess
    r = subprocess.run(
        [sys.executable, "init_db.py"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in r.stdout.splitlines():
        print(f"  {line}")
    if r.returncode != 0:
        print(r.stderr)
        print("❌ 数据库重建失败")
        sys.exit(1)
    print("✅ 数据库重建完成")


def main() -> int:
    parser = argparse.ArgumentParser(description="数据库重置脚本")
    parser.add_argument("--no-reinit", action="store_true", help="只删除不重建")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    db_url = os.getenv("DATABASE_URL", "sqlite:///./db/memory.db")
    vector_path = os.getenv("VECTOR_DB_PATH", "./db/vector_store")

    print("🔄 重置关系型数据库...")
    reset_relational(db_url)
    print("🔄 重置向量数据库...")
    reset_vector(vector_path)

    if not args.no_reinit:
        print("🔄 重建数据库...")
        run_init()

    print("\n🎉 数据库重置完成，可启动后端")
    return 0


if __name__ == "__main__":
    sys.exit(main())
