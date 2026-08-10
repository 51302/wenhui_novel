
from elasticsearch import Elasticsearch
from typing import Optional
from app.config import get as cfg_get

ES_HOST = cfg_get("elasticsearch.host", "http://localhost:9200")
INDEX_NOVELS = "novels"


class ESService:

    def __init__(self):
        """初始化ES连接，创建HTTP客户端并确保索引存在"""
        try:
            self.client = Elasticsearch(
                ES_HOST,
                # 连接池优化：保持长连接，减少握手开销
                maxsize=20,
                retry_on_timeout=True,
                timeout=5,
                max_retries=2,
            )
            self._ensure_index()
        except Exception:
            self.client = None

    def _ensure_index(self):
        """确保ES索引存在，不存在则创建（含ik分词器映射）"""
        if self.client and not self.client.indices.exists(index=INDEX_NOVELS):
            self.client.indices.create(
                index=INDEX_NOVELS,
                body={
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {
                        "properties": {
                            "novel_unique_id": {"type": "keyword"},
                            "title": {"type": "text", "analyzer": "ik_max_word"},
                            "author_name": {"type": "text", "analyzer": "ik_max_word"},
                            "target_reader": {"type": "keyword"},
                            "genre": {"type": "keyword"},
                            "description": {"type": "text", "analyzer": "ik_max_word"},
                            "cover_image": {"type": "keyword"},
                            "sign_type": {"type": "keyword"},
                            "created_at": {"type": "date"}
                        }
                    }
                }, ignore=400
            )

    def index_novel(self, doc: dict) -> bool:
        """索引一篇小说作品到ES
        :param doc: 作品文档（含novel_unique_id/title等字段）
        :return: 索引是否成功
        """
        if not self.client:
            return False
        try:
            self.client.index(index=INDEX_NOVELS, id=doc["novel_unique_id"], document=doc)
            return True
        except Exception:
            return False

    def search_novels(self, keyword: str, page: int = 1, page_size: int = 12, exclude_exclusive: bool = False) -> Optional[dict]:
        """在ES中按关键词全文搜索作品
        :param keyword: 搜索关键词
        :param page: 页码
        :param page_size: 每页数量
        :param exclude_exclusive: 是否排除独家作品
        :return: ES原始搜索结果，失败返回None
        """
        if not self.client:
            return None
        try:
            body = {
                "query": {
                    "multi_match": {
                        "query": keyword,
                        "fields": ["title^2", "author_name^2", "description"]
                    }
                },
                "from": (page - 1) * page_size,
                "size": page_size
            }
            if exclude_exclusive:
                body["query"] = {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": keyword,
                                    "fields": ["title^2", "author_name^2", "description"]
                                }
                            }
                        ],
                        # 兼容存量文档：sign_type=non_exclusive 或 无 sign_type 字段（视为非独家）
                        "filter": [
                            {
                                "bool": {
                                    "should": [
                                        {"term": {"sign_type": "non_exclusive"}},
                                        {"bool": {"must_not": [{"exists": {"field": "sign_type"}}]}}
                                    ]
                                }
                            }
                        ]
                    }
                }
            result = self.client.search(
                index=INDEX_NOVELS,
                body=body
            )
            return result
        except Exception:
            return None

    def delete_novel(self, novel_unique_id: str):
        """从ES索引中删除指定作品
        :param novel_unique_id: 作品唯一ID
        """
        if self.client:
            try:
                self.client.delete(index=INDEX_NOVELS, id=novel_unique_id, ignore=404)
            except Exception:
                pass


es_service = ESService()
