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
    """获取 JWT 签名密钥，从配置文件读取
    :return: JWT 密钥字符串
    """
    return get("jwt.secret_key", "wenhui-novel-jwt-secret-key-2024")


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
    """获取 DeepSeek API 密钥，从配置文件读取
    :return: API 密钥字符串
    """
    return get("deepseek.api_key", "")


def deepseek_base_url() -> str:
    """获取 DeepSeek API 基础地址，从配置文件读取
    :return: API 基础 URL
    """
    return get("deepseek.base_url", "https://api.deepseek.com")


def deepseek_model() -> str:
    """获取 DeepSeek 模型名称
    :return: 模型名称，默认 deepseek-chat
    """
    return get("deepseek.model", "deepseek-chat")


def deepseek_long_model() -> str:
    """获取 DeepSeek 长文本模型名称（章节正文生成专用）

    flash 模型生成的句子过于平滑，AI 检测工具（困惑度+突发性统计）容易标记；
    正文生成改用 deepseek-v4-pro，对"人味"规则执行更彻底、AI 味更淡。
    其余轻量功能（概要/提取/续写）仍用 deepseek.model。
    :return: 长文本模型名称，默认 deepseek-v4-pro
    """
    return get("deepseek.model_long", "deepseek-v4-pro")


def vip_default_plan() -> str:
    """获取默认 VIP 套餐类型
    :return: 套餐类型，默认 vip_monthly"""
    return get("vip.default_plan", "vip_monthly")


def show_all_works() -> bool:
    """首页是否展示所有作品（true=所有人可见，false=仅自己可见）
    :return: 布尔值，默认 True
    """
    return get("app.show_all_works", True)


def reload():
    """热重载后强制重新读取（uvicorn --reload 时模块级缓存不刷新）"""
    global _config_cache
    _config_cache = None


# ============================================================
#  章节生成参数（字数/token/截断控制）
# ============================================================

def gen_word_count() -> int:
    """默认目标字数"""
    return int(get("ai.generation.word_count", 4000))


def gen_word_count_max() -> int:
    """前端字数输入上限"""
    return int(get("ai.generation.word_count_max", 4000))


def gen_word_count_ratio() -> float:
    """prompt 要求字数上浮倍数"""
    return float(get("ai.generation.word_count_ratio", 1.6))


def gen_max_tokens_multiplier() -> int:
    """max_tokens 倍数"""
    return int(get("ai.generation.max_tokens_multiplier", 4))


def gen_max_tokens_min() -> int:
    """max_tokens 下限"""
    return int(get("ai.generation.max_tokens_min", 16000))


def gen_hard_cap_ratio() -> float:
    """超长截断倍数"""
    return float(get("ai.generation.hard_cap_ratio", 2.0))


def gen_hard_cap_min_extra() -> int:
    """超长截断保底"""
    return int(get("ai.generation.hard_cap_min_extra", 3000))
