import chromadb
import os
from dotenv import load_dotenv

load_dotenv()

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
        self.collection = self.client.get_or_create_collection(
            name="memories",
            metadata={"hnsw:space": "cosine"}
        )
    
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
        for mem_id, distance in zip(results["ids"][0], results["distances"][0]):
            similarity = 1 - distance
            if similarity >= threshold:
                filtered.append({
                    "id": mem_id,
                    "similarity": similarity
                })
        
        return filtered
    
    def delete_memory(self, memory_id: str):
        """删除记忆"""
        self.collection.delete(ids=[memory_id])

vector_client = VectorClient()
