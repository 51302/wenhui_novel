import os
import shutil
import threading
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
        except KeyError as e:
            if '_type' in str(e):
                # ChromaDB 0.6.x 迁移问题：修复空 config_json_str
                self._fix_config_type()
                self.collection = self.client.get_collection(self.collection_name)
            else:
                self.collection = self.client.create_collection(
                    name=self.collection_name,
                    metadata={"description": "小说创作记忆存储"}
                )
        except Exception:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={"description": "小说创作记忆存储"}
            )

    def _fix_config_type(self):
        """修复 ChromaDB 0.6.x 迁移导致的 config_json_str 缺少 _type 问题"""
        import sqlite3, json
        db_file = os.path.join(self.persist_path, 'chroma.sqlite3')
        try:
            conn = sqlite3.connect(db_file)
            cur = conn.cursor()
            cur.execute("SELECT id, config_json_str FROM collections WHERE name = ?", (self.collection_name,))
            rows = cur.fetchall()
            for col_id, config_str in rows:
                config = json.loads(config_str or '{}')
                if '_type' not in config:
                    config['_type'] = 'CollectionConfigurationInternal'
                    cur.execute('UPDATE collections SET config_json_str = ? WHERE id = ?',
                               (json.dumps(config), col_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

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


# ============================================================================
# 旧模块级单例（保持兼容，main.py 初始化后设置）
# ============================================================================
chroma_memory: Optional[ChromaMemoryStore] = None


# ============================================================================
# NovelMemoryStoreManager —— 每本书独立 ChromaDB 实例管理器
# ============================================================================

class NovelMemoryStoreManager:
    """管理每本书的独立 ChromaDB 实例，实现记忆体物理隔离。

    每本书的向量数据存储在: {base_path}/{novel_unique_id}/
    内部自动生成独立的 chroma.sqlite3 文件，确保：
    - 删除一本书可直接删除整个目录
    - 不同书之间的记忆不会混淆
    - 避免单文件膨胀和锁竞争
    """

    def __init__(self, base_path: str = None):
        """初始化管理器
        :param base_path: 向量数据持久化的基础目录（如 backend/vector_db_data）
        """
        self._base_path = base_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vector_db_data"
        )
        self._stores: Dict[str, ChromaMemoryStore] = {}
        self._lock = threading.Lock()
        os.makedirs(self._base_path, exist_ok=True)

    def get_store(self, novel_unique_id: str) -> Optional[ChromaMemoryStore]:
        """获取或创建某本书的独立 ChromaMemoryStore 实例
        数据目录: {base_path}/{novel_unique_id}/
        隔离文件: chroma.sqlite3（由 ChromaDB 自动管理）
        :param novel_unique_id: 书籍唯一ID
        :return: ChromaMemoryStore 实例，失败返回 None
        """
        with self._lock:
            if novel_unique_id in self._stores:
                return self._stores[novel_unique_id]

            persist_path = os.path.join(self._base_path, novel_unique_id)
            try:
                store = ChromaMemoryStore(
                    persist_path=persist_path,
                    collection_name="novel_memory"
                )
                self._stores[novel_unique_id] = store
                return store
            except Exception as e:
                print(f"[NovelMemoryStoreManager] 创建 {novel_unique_id} 的记忆存储失败: {e}")
                return None

    def close_store(self, novel_unique_id: str):
        """关闭并移除某本书的 store 实例（释放资源）
        :param novel_unique_id: 书籍唯一ID
        """
        with self._lock:
            if novel_unique_id in self._stores:
                del self._stores[novel_unique_id]

    def delete_store(self, novel_unique_id: str) -> bool:
        """删除某本书的全部向量数据（目录 + 内存实例）
        :param novel_unique_id: 书籍唯一ID
        :return: 删除成功返回 True
        """
        with self._lock:
            if novel_unique_id in self._stores:
                del self._stores[novel_unique_id]

        persist_path = os.path.join(self._base_path, f"{novel_unique_id}.sqlite")
        if os.path.exists(persist_path):
            try:
                shutil.rmtree(persist_path)
                return True
            except Exception as e:
                print(f"[NovelMemoryStoreManager] 删除 {novel_unique_id} 数据失败: {e}")
                return False
        return True


# 模块级管理器单例（由 main.py 在 lifespan 中初始化）
novel_memory_manager: Optional[NovelMemoryStoreManager] = None
