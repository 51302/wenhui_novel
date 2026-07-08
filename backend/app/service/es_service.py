import os
from elasticsearch import Elasticsearch
from typing import Optional

ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NOVELS = "novels"


class ESService:

    def __init__(self):
        try:
            self.client = Elasticsearch(ES_HOST)
            self._ensure_index()
        except Exception:
            self.client = None

    def _ensure_index(self):
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
                            "created_at": {"type": "date"}
                        }
                    }
                }, ignore=400
            )

    def index_novel(self, doc: dict) -> bool:
        if not self.client:
            return False
        try:
            self.client.index(index=INDEX_NOVELS, id=doc["novel_unique_id"], document=doc)
            return True
        except Exception:
            return False

    def search_novels(self, keyword: str, page: int = 1, page_size: int = 12) -> Optional[dict]:
        if not self.client:
            return None
        try:
            result = self.client.search(
                index=INDEX_NOVELS,
                body={
                    "query": {
                        "multi_match": {
                            "query": keyword,
                            "fields": ["title^2", "author_name^2", "description"]
                        }
                    },
                    "from": (page - 1) * page_size,
                    "size": page_size
                }
            )
            return result
        except Exception:
            return None

    def delete_novel(self, novel_unique_id: str):
        if self.client:
            try:
                self.client.delete(index=INDEX_NOVELS, id=novel_unique_id, ignore=404)
            except Exception:
                pass


es_service = ESService()
