import chromadb
import os
import logging
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "./db/vector_store")

class VectorClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_client()
        return cls._instance

    def _init_client(self):
        self.client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
        self._ensure_collection()

    def _ensure_collection(self):
        """获取或创建 memories 集合，如果维度不匹配则自动重建。"""
        try:
            self.collection = self.client.get_or_create_collection(
                name="memories",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            # 集合元数据损坏等极端情况，删除重建
            logger.warning(f"获取集合异常，尝试重建: {e}")
            self._recreate_collection()
            return

        # 通过尝试写入一条测试数据检测维度是否匹配
        test_id = "__dimension_test__"
        try:
            # 用当前 embedding 模型的维度创建测试向量
            from core.utils.embedding import get_embedding
            test_vec = get_embedding("test")
            dim = len(test_vec)
            self.collection.add(
                ids=[test_id],
                embeddings=[test_vec],
                documents=["test"],
                metadatas=[{"_test": "true"}]
            )
            # 写入成功，清理测试数据
            self.collection.delete(ids=[test_id])
            logger.info(f"向量集合就绪，维度: {dim}")
        except Exception as e:
            err_msg = str(e)
            if "does not match collection dimensionality" in err_msg:
                logger.warning(f"向量维度不匹配，自动重建集合: {err_msg}")
                self._recreate_collection()
            else:
                logger.warning(f"向量集合检测异常: {err_msg}")
                self._recreate_collection()

    def _recreate_collection(self):
        """删除并重建 memories 集合。"""
        try:
            self.client.delete_collection("memories")
            logger.info("已删除旧的 memories 集合")
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name="memories",
            metadata={"hnsw:space": "cosine"}
        )
        logger.info("已重建 memories 集合")
    
    def add_memory(self, memory_id: str, content: str, embedding: list, metadata: dict):
        """添加记忆到向量库"""
        self.collection.add(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[metadata]
        )
    
    def search_memories(self, query_embedding: list, top_k: int = 5, threshold: float = 0.7):
        """搜索相关记忆"""
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["distances", "metadatas"]
        )
        
        if not results["ids"][0]:
            return []
        
        # 过滤低于阈值的结果
        filtered = []
        metadatas = results.get("metadatas", [[]])[0] or []
        for index, (mem_id, distance) in enumerate(zip(results["ids"][0], results["distances"][0])):
            similarity = 1 - distance
            if similarity >= threshold:
                filtered.append({
                    "id": mem_id,
                    "similarity": similarity,
                    "metadata": metadatas[index] if index < len(metadatas) else {}
                })
        
        return filtered
    
    def delete_memory(self, memory_id: str):
        """删除记忆"""
        self.collection.delete(ids=[memory_id])

vector_client = VectorClient()
