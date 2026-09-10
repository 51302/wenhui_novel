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


_ENV_KEYS = {
    "deepseek.api_key": "DEEPSEEK_API_KEY",
    "mysql.password": "MYSQL_PASSWORD",
    "jwt.secret_key": "JWT_SECRET_KEY",
    "email.resend_api_key": "RESEND_API_KEY",
    "alipay.app_private_key": "ALIPAY_APP_PRIVATE_KEY",
    "alipay.app_public_key": "ALIPAY_APP_PUBLIC_KEY",
    "alipay.alipay_public_key": "ALIPAY_PUBLIC_KEY",
}


def get(key: str, default=None):
    if key in _ENV_KEYS:
        env_val = os.environ.get(_ENV_KEYS[key])
        if env_val is not None and env_val.strip():
            return env_val
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
    return get("deepseek.base_url", "https://api.deepseek.com/v1/chat/completions")


def deepseek_model() -> str:
    """获取 DeepSeek 模型名称
    :return: 模型名称，默认 deepseek-chat
    """
    return get("deepseek.model", "deepseek-chat")


def deepseek_long_model() -> str:
    """获取 DeepSeek 长文本模型名称（章节正文生成专用）

    flash 模型生成的句子过于平滑，AI 检测工具（困惑度+突发性统计）容易标记；
    正文生成/续写/重新生成改用 deepseek-v4-pro，对"人味"规则执行更彻底、AI 味更淡。
    其余轻量功能（记忆体提取/剧本/概要）仍用 deepseek.model。
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


def calc_dynamic_max_tokens(word_count: int, input_chars: int) -> int:
    """根据实际输入大小动态计算 max_tokens
    
    算法逻辑：
    1. 输出token需求 = 字数 × 1.4（中文1字≈1.4token）
    2. 输入越大，AI需要更多输出token来组织内容 → 按输入规模动态调整倍率
    3. 保底不低于 min_tokens，上限不超过 max_tokens_max
    
    Args:
        word_count: 目标字数（如2500）
        input_chars: 输入总字符数（系统提示词+记忆体+概要+用户提示词）
    """
    # 基础输出token需求（中文1字≈1.4token，加20%冗余）
    base_output = int(word_count * 1.4 * 1.2)
    
    # 根据输入规模动态调整倍率
    # 输入越少 → 倍率越低（节省token）
    # 输入越多 → 倍率越高（确保AI有足够token组织内容）
    if input_chars < 5000:
        multiplier = 1.0   # 输入很少，基础输出就够了
    elif input_chars < 10000:
        multiplier = 1.1   # 输入适中，略加冗余
    elif input_chars < 20000:
        multiplier = 1.2   # 输入较多，需要更多空间
    else:
        multiplier = 1.3   # 输入很大，最大冗余
    
    dynamic_tokens = int(base_output * multiplier)
    
    # 保底和上限
    min_tokens = gen_max_tokens_min()
    max_tokens_max = int(get("ai.generation.max_tokens_max", 6000))
    
    return max(min(dynamic_tokens, max_tokens_max), min_tokens)


def gen_hard_cap_ratio() -> float:
    """超长截断倍数"""
    return float(get("ai.generation.hard_cap_ratio", 2.0))


def gen_hard_cap_min_extra() -> int:
    """超长截断保底"""
    return int(get("ai.generation.hard_cap_min_extra", 3000))


def gen_api_timeout() -> int:
    """正文生成API超时（秒），默认240s"""
    return int(get("ai.generation.api_timeout", 240))
