import json
import random
import redis
from typing import Optional, Any, Callable


class RedisCache:
    """Redis 缓存客户端封装，提供带容错的读写删除操作"""

    def __init__(self, host: str = "localhost", port: int = 6379,
                 password: str = "", db: int = 0, default_ttl: int = 3600):
        """初始化 Redis 连接，连接失败时 client 设为 None 不阻断服务启动
        :param host: Redis 服务器地址
        :param port: Redis 服务器端口
        :param password: Redis 认证密码
        :param db: Redis 数据库编号
        :param default_ttl: 默认过期时间（秒）
        """
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
        """从缓存读取并反序列化 JSON 数据
        :param key: 缓存键
        :return: 反序列化后的数据，缓存未命中或异常时返回 None
        """
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
        """写入缓存，dict/list 自动序列化为 JSON，TTL 附加随机抖动防止缓存雪崩
        :param key: 缓存键
        :param value: 缓存值
        :param ttl: 过期时间（秒），不传则使用默认 TTL
        :return: 写入成功返回 True，失败返回 False
        """
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
        """删除一个或多个缓存键
        :param keys: 可变数量的缓存键
        """
        if not self.client:
            return
        try:
            self.client.delete(*keys)
        except Exception:
            pass

    def delete_pattern(self, pattern: str):
        """按通配符模式批量删除缓存键（如 'user:*'）
        :param pattern: Redis 键匹配模式
        """
        if not self.client:
            return
        try:
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
        except Exception:
            pass

    def ping(self) -> bool:
        """检测 Redis 连接是否可用
        :return: 连接正常返回 True，否则返回 False
        """
        if not self.client:
            return False
        try:
            return self.client.ping()
        except Exception:
            return False

    # ----------------------------------------------------------------
    #  Hash 操作（用于记忆体持久存储，无 TTL）
    # ----------------------------------------------------------------
    def hget(self, key: str, field: str) -> Optional[str]:
        """获取 Hash 中指定字段的值"""
        if not self.client:
            return None
        try:
            return self.client.hget(key, field)
        except Exception:
            return None

    def hset(self, key: str, field: str, value: str) -> bool:
        """设置 Hash 字段值"""
        if not self.client:
            return False
        try:
            return bool(self.client.hset(key, field, value))
        except Exception:
            return False

    def hgetall(self, key: str) -> dict:
        """获取 Hash 全部字段"""
        if not self.client:
            return {}
        try:
            return self.client.hgetall(key) or {}
        except Exception:
            return {}

    def hdel(self, key: str, *fields: str) -> int:
        """删除 Hash 中一个或多个字段"""
        if not self.client or not fields:
            return 0
        try:
            return self.client.hdel(key, *fields)
        except Exception:
            return 0

    def exists(self, key: str) -> bool:
        """检查 key 是否存在"""
        if not self.client:
            return False
        try:
            return bool(self.client.exists(key))
        except Exception:
            return False

    # ----------------------------------------------------------------
    #  List 操作（用于任务队列）
    # ----------------------------------------------------------------
    def rpush(self, key: str, value: str) -> bool:
        """向 List 尾部追加元素"""
        if not self.client:
            return False
        try:
            return bool(self.client.rpush(key, value))
        except Exception:
            return False

    def blpop(self, key: str, timeout: int = 0) -> tuple:
        """阻塞式弹出 List 头部元素
        :return: (key, value) 或 None
        """
        if not self.client:
            return None
        try:
            return self.client.blpop(key, timeout=timeout)
        except Exception:
            return None

    def lrange(self, key: str, start: int = 0, end: int = -1) -> list:
        """获取 List 范围内的元素"""
        if not self.client:
            return []
        try:
            return self.client.lrange(key, start, end) or []
        except Exception:
            return []

    # ----------------------------------------------------------------
    #  兼容性别名（供旧代码使用 setex 直接调用）
    # ----------------------------------------------------------------
    def setex(self, key: str, ttl: int, value: str) -> bool:
        """设置带过期时间的键值对（兼容旧代码）"""
        return self.set(key, value, ttl=ttl)


redis_client: Optional[RedisCache] = None
