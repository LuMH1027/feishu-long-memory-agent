# test_chroma.py
from db.vector.client import vector_client


def test_vector_db():
    print("1. 正在向 ChromaDB 写入测试向量数据...")
    # 模拟添加一条记忆: ChromaDB 集合已初始化为 1536 维，所以我们需要提供长度为 1536 的伪向量
    test_embedding = [0.1] * 1536
    vector_client.add_memory(
        memory_id="test-vector-1",
        content="发现了一个关于 ChromaDB 的严重 bug，需要修复",
        embedding=test_embedding,
        metadata={"type": "bug_fix", "user": "test_user"}
    )
    print("写入成功！")

    print("\n2. 正在进行相似度检索...")
    # 使用近义向量去检索
    query_vector = [0.1] * 1536

    # 搜索相似记忆
    results = vector_client.search_memories(
        query_embedding=query_vector,
        top_k=1,
        threshold=0.5
    )

    print("\n==== 检索结果 ====")
    if results:
        for res in results:
            print(f"ID: {res['id']}")
            print(f"相似度: {res['similarity']:.4f}")
            print(f"元数据: {res['metadata']}")
    else:
        print("未找到结果")

    print("\n3. 正在清理测试数据...")
    vector_client.delete_memory("test-vector-1")
    print("清理完成。")


if __name__ == "__main__":
    test_vector_db()
