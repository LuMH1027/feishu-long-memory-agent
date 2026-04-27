#!/usr/bin/env python3
"""初始化数据库脚本"""
from backend.dependencies import engine, Base
from backend.dependencies import init_database_schema
from db.relational.models import Memory, DecisionMemory
from db.vector.client import vector_client

def init_relational_db():
    """初始化关系型数据库"""
    print("正在初始化关系型数据库...")
    init_database_schema()
    print("✅ 关系型数据库表创建完成")

def init_vector_db():
    """初始化向量数据库"""
    print("正在初始化向量数据库...")
    # 测试向量库连接
    test_embedding = [0.0] * 1536  # OpenAI ada-002 embedding维度
    vector_client.add_memory(
        memory_id="test_init",
        content="初始化测试",
        embedding=test_embedding,
        metadata={"type": "test"}
    )
    vector_client.delete_memory("test_init")
    print("✅ 向量数据库初始化完成")

if __name__ == "__main__":
    init_relational_db()
    init_vector_db()
    print("\n🎉 所有数据库初始化完成！")
