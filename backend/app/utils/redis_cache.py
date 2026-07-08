import json
import random
import redis
from typing import Optional, Any, Callable


class RedisCache:

    def __init__(self, host: str = "localhost", port: int = 6379,
                 password: str = "", db: int = 0, default_ttl: int = 3600):
        self.default_ttl = default_ttl
        try:
            self.client = redis.Redis(
                host=host, port=port, password=password, db=db,
                decode_responses=True, socket_connect_timeout=5
            )
            self.client.ping()
        except Exception:
            self.client = None

    def get(self, key: str) -> Optional[Any]:
        if not self.client:
            return None
        try:
            data = self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        if not self.client:
            return False
        ttl = ttl or self.default_ttl
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        ttl = ttl + random.randint(0, ttl // 10)
        try:
            return self.client.setex(key, ttl, value)
        except Exception:
            return False

    def delete(self, *keys: str):
        if not self.client:
            return
        try:
            self.client.delete(*keys)
        except Exception:
            pass

    def delete_pattern(self, pattern: str):
        if not self.client:
            return
        try:
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
        except Exception:
            pass

    def ping(self) -> bool:
        if not self.client:
            return False
        try:
            return self.client.ping()
        except Exception:
            return False


redis_client: Optional[RedisCache] = None
