import os
import chromadb
from typing import List, Dict, Optional


class ChromaMemoryStore:
    """基于 ChromaDB 的向量记忆存储，用于小说创作上下文的语义检索"""

    def __init__(self, persist_path: str = "./vector_db_data", collection_name: str = "novel_memory"):
        """初始化 ChromaDB 持久化客户端，自动创建 collection
        :param persist_path: 向量数据持久化目录
        :param collection_name: collection 名称
        """
        self.persist_path = persist_path
        self.collection_name = collection_name
        os.makedirs(persist_path, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persist_path)
        try:
            self.collection = self.client.get_collection(self.collection_name)
        except Exception:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={"description": "小说创作记忆存储"}
            )

    def add_memory(self, doc_id: str, text: str, metadata: Dict = None) -> bool:
        """添加一条向量记忆记录
        :param doc_id: 文档唯一 ID
        :param text: 文档文本内容
        :param metadata: 附加元数据
        :return: 添加成功返回 True，失败返回 False
        """
        try:
            self.collection.add(documents=[text], ids=[doc_id], metadatas=[metadata or {}])
            return True
        except Exception as e:
            print(f"ChromaDB add error: {e}")
            return False

    def search_memory(self, query: str, n_results: int = 5) -> List[Dict]:
        """语义搜索最相似的记忆记录
        :param query: 查询文本
        :param n_results: 返回的最大结果数
        :return: 包含 document 和 metadata 的字典列表
        """
        try:
            results = self.collection.query(query_texts=[query], n_results=n_results)
            memories = []
            if results and results.get("documents") and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results.get("metadatas", [[{}]])[0][i] if results.get("metadatas") else {}
                    memories.append({"document": doc, "metadata": meta})
            return memories
        except Exception as e:
            print(f"ChromaDB search error: {e}")
            return []


    def delete_memory(self, doc_id: str) -> bool:
        """删除指定 ID 的向量记录"""
        try:
            self.collection.delete(ids=[doc_id])
            return True
        except Exception as e:
            print(f"ChromaDB delete error: {e}")
            return False

    def delete_by_prefix(self, prefix: str) -> int:
        """按 ID 前缀批量删除向量记录（如 'novel_id_' 前缀）"""
        try:
            ids = self.collection.get()
            to_delete = [id for id in (ids.get("ids") or []) if id.startswith(prefix)]
            if to_delete:
                self.collection.delete(ids=to_delete)
            return len(to_delete)
        except Exception as e:
            print(f"ChromaDB delete_by_prefix error: {e}")
            return 0


chroma_memory: Optional[ChromaMemoryStore] = None
