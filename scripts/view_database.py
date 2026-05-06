#!/usr/bin/env python3
"""查看数据库内容的脚本"""
import sqlite3
import json
import sys
from pathlib import Path

# 设置标准输出编码为UTF-8
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = Path(__file__).parent.parent / "db" / "memory.db"

def view_database():
    if not DB_PATH.exists():
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 查看所有表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("=" * 60)
    print("📊 数据库表列表")
    print("=" * 60)
    for table in tables:
        print(f"  - {table['name']}")

    # 查看memories表
    print("\n" + "=" * 60)
    print("📝 memories 表内容")
    print("=" * 60)

    # 统计信息
    cursor.execute("SELECT COUNT(*) as total FROM memories")
    total = cursor.fetchone()['total']
    print(f"总记录数: {total}")

    cursor.execute("SELECT type, COUNT(*) as count FROM memories GROUP BY type ORDER BY count DESC")
    type_stats = cursor.fetchall()
    print("\n按类型统计:")
    for stat in type_stats:
        print(f"  {stat['type']}: {stat['count']}条")

    cursor.execute("SELECT source, COUNT(*) as count FROM memories GROUP BY source ORDER BY count DESC")
    source_stats = cursor.fetchall()
    print("\n按来源统计:")
    for stat in source_stats:
        print(f"  {stat['source']}: {stat['count']}条")

    # 显示最近的记录
    cursor.execute("""
        SELECT id, type, source, content, description, created_at, hit_count
        FROM memories
        ORDER BY created_at DESC
        LIMIT 10
    """)
    recent = cursor.fetchall()
    print("\n最近10条记忆:")
    print("-" * 60)
    for i, row in enumerate(recent, 1):
        content_preview = row['content'][:50] + "..." if len(row['content']) > 50 else row['content']
        print(f"{i}. [{row['type']}] [{row['source']}]")
        print(f"   内容: {content_preview}")
        print(f"   描述: {row['description'] or '无'}")
        print(f"   时间: {row['created_at']}")
        print(f"   命中次数: {row['hit_count']}")
        print()

    # 查看decision_memories表
    print("\n" + "=" * 60)
    print("📋 decision_memories 表内容")
    print("=" * 60)

    cursor.execute("SELECT COUNT(*) as total FROM decision_memories")
    total_decisions = cursor.fetchone()['total']
    print(f"总记录数: {total_decisions}")

    if total_decisions > 0:
        cursor.execute("""
            SELECT d.id, d.topic, d.conclusion, d.reason, m.created_at
            FROM decision_memories d
            JOIN memories m ON d.id = m.id
            ORDER BY m.created_at DESC
            LIMIT 10
        """)
        decisions = cursor.fetchall()
        print("\n最近10条决策:")
        print("-" * 60)
        for i, row in enumerate(decisions, 1):
            print(f"{i}. 主题: {row['topic']}")
            print(f"   结论: {row['conclusion'][:50]}...")
            print(f"   原因: {row['reason'] or '无'}")
            print(f"   时间: {row['created_at']}")
            print()

    # 查看CLI命令记录
    print("\n" + "=" * 60)
    print("💻 CLI命令记录")
    print("=" * 60)

    cursor.execute("""
        SELECT content, memory_metadata, hit_count, created_at
        FROM memories
        WHERE type = 'cli_command'
        ORDER BY hit_count DESC
        LIMIT 10
    """)
    cli_commands = cursor.fetchall()
    print(f"CLI命令总数: {len(cli_commands)}")
    print("\n高频命令Top10:")
    print("-" * 60)
    for i, row in enumerate(cli_commands, 1):
        metadata = json.loads(row['memory_metadata']) if row['memory_metadata'] else {}
        count = metadata.get('count', 0)
        print(f"{i}. {row['content']}")
        print(f"   使用次数: {count}, 命中次数: {row['hit_count']}")
        print()

    conn.close()

if __name__ == "__main__":
    view_database()
