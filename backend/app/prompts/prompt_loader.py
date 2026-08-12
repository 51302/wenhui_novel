# -*- coding: utf-8 -*-
"""提示词配置加载器：统一从 conf/prompts.yaml 加载全部提示词与模板数据。

特性：
- 修改提示词只需编辑 backend/app/conf/prompts.yaml，保存后下一次调用自动重读
  （按文件 mtime 热加载），无需重启后端、无需改代码。
- 内部引用：值中出现 ``__键名__`` 时，加载后自动替换为同文件该键的值
  （用于复用公共段落，例如提取 Prompt 引用维度说明），支持嵌套引用。
- 配置文件损坏时沿用上次可用配置，不影响线上服务。

用法：
    from app.prompts.prompt_loader import get_prompt, get_config
    text = get_prompt("GENERATE_SYSTEM_PROMPT")          # 字符串提示词
    styles = get_config("AUTHOR_STYLES") or []           # 任意结构化数据
"""
import os
import re
import threading

import yaml

_CONF_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "conf", "prompts.yaml")

_cache = {"mtime": None, "data": None}
_lock = threading.Lock()

# 内部引用标记：__键名__（键名允许带前导下划线，如 __ _MEMORY_DIMENSION_PROMPT_PART__ 记作 __MEMORY_DIMENSION_PROMPT_PART__）
_REF_RE = re.compile(r"__([A-Z_][A-Z0-9_]*)__")
_MAX_REF_ROUNDS = 10  # 防循环引用


def _resolve_refs(data):
    """把字符串值中的 __键名__ 引用替换为对应键的值（原地修改）。

    键名匹配时先按原名查找，再尝试前导下划线变体
    （如 __MEMORY_DIMENSION_PROMPT_PART__ → _MEMORY_DIMENSION_PROMPT_PART）。
    """

    def _lookup(name):
        if name in data:
            return data[name]
        underscored = "_" + name
        return data.get(underscored, None)

    for _ in range(_MAX_REF_ROUNDS):
        changed = False
        for key, value in data.items():
            if not isinstance(value, str) or "__" not in value:
                continue

            def repl(m, _lookup=_lookup):
                ref = _lookup(m.group(1))
                return ref if ref is not None else m.group(0)

            new_value = _REF_RE.sub(repl, value)
            if new_value != value:
                data[key] = new_value
                changed = True
        if not changed:
            break
    return data


def _load():
    """读取 yaml（带 mtime 缓存），失败时沿用上次可用配置。"""
    try:
        mtime = os.path.getmtime(_CONF_PATH)
    except OSError:
        return _cache["data"] or {}
    if _cache["mtime"] == mtime:
        return _cache["data"] or {}
    with _lock:
        # 双重检查：锁内再比对一次
        try:
            mtime = os.path.getmtime(_CONF_PATH)
        except OSError:
            return _cache["data"] or {}
        if _cache["mtime"] == mtime:
            return _cache["data"] or {}
        try:
            with open(_CONF_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            _cache["data"] = _resolve_refs(data)
            _cache["mtime"] = mtime
        except Exception:
            # 配置文件异常时沿用上次可用配置，避免影响线上
            if _cache["data"] is None:
                _cache["data"] = {}
                _cache["mtime"] = mtime
    return _cache["data"] or {}


def get_config(key, default=None):
    """读取任意配置项（含结构化数据）。"""
    return _load().get(key, default)


def get_prompt(name):
    """读取字符串提示词模板，未定义时返回空字符串。"""
    value = get_config(name)
    return value if isinstance(value, str) else ""
