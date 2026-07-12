"""
统一配置加载器 —— 所有模块通过此文件读取 config.yaml，避免散落读取
"""
import os
import yaml

# config.yaml 路径
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conf", "config.yaml")

# 只加载一次
_config_cache = None


def _load() -> dict:
    """加载 config.yaml 配置文件（带缓存，仅加载一次）
    :return: 配置字典
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
    else:
        _config_cache = {}
    return _config_cache


def get(key: str, default=None):
    """从 config.yaml 获取配置项，支持点号路径 如 'redis.host'"""
    cfg = _load()
    for k in key.split("."):
        if isinstance(cfg, dict):
            cfg = cfg.get(k)
        else:
            return default
    return cfg if cfg is not None else default


# ============================================================
#  常用配置快捷访问
# ============================================================

def jwt_secret() -> str:
    """获取 JWT 签名密钥，优先读取环境变量 JWT_SECRET_KEY
    :return: JWT 密钥字符串
    """
    return os.getenv("JWT_SECRET_KEY", get("jwt.secret_key", "wenhui-novel-jwt-secret-key-2024"))


def jwt_algorithm() -> str:
    """获取 JWT 签名算法
    :return: 算法名称，默认 HS256
    """
    return get("jwt.algorithm", "HS256")


def jwt_expire_minutes() -> int:
    """获取 JWT Token 过期时间
    :return: 过期分钟数，默认 43200（30天）
    """
    return int(get("jwt.expire_minutes", 43200))


def deepseek_api_key() -> str:
    """获取 DeepSeek API 密钥，优先读取环境变量 DEEPSEEK_API_KEY
    :return: API 密钥字符串
    """
    return os.getenv("DEEPSEEK_API_KEY", get("deepseek.api_key", ""))


def deepseek_base_url() -> str:
    """获取 DeepSeek API 基础地址，优先读取环境变量 DEEPSEEK_BASE_URL
    :return: API 基础 URL
    """
    return os.getenv("DEEPSEEK_BASE_URL", get("deepseek.base_url", "https://api.deepseek.com"))


def deepseek_model() -> str:
    """获取 DeepSeek 模型名称
    :return: 模型名称，默认 deepseek-chat
    """
    return get("deepseek.model", "deepseek-chat")


def vip_default_plan() -> str:
    """获取默认 VIP 套餐类型
    :return: 套餐类型，默认 vip_monthly"""
    return get("vip.default_plan", "vip_monthly")


def reload():
    """热重载后强制重新读取（uvicorn --reload 时模块级缓存不刷新）"""
    global _config_cache
    _config_cache = None
