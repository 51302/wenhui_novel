# -*- coding: utf-8 -*-
"""AI 特征规则引擎：从 conf/ai_feature_rules.json 加载检测/清洗规则并执行。

设计目标：新增 AI 特征时只需在 JSON 配置里追加条目，本文件与 text_cleaner 无需改动。
- 配置按文件 mtime 缓存，编辑保存后下一次调用自动重读（热加载，无需重启后端）。
- detect 规则 → 并入 check_ai_features 报告（命中数 >= threshold 才上报）。
- clean 规则 → 并入 clean_generated_text 清洗（action 支持 delete/replace/keep_group/redup）。
- regex_refs  → text_cleaner 复杂逻辑按名读取正则（get_regex），支持 template 型（{wordsN} 引用 wordlist）。
- wordlist    → 词表数据（get_wordlist），供代码与模板正则引用。
"""
import json
import os
import re

_RULES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "conf", "ai_feature_rules.json")

_cache = {"mtime": None, "data": None}
_regex_cache = {}


def load_rules():
    """读取配置文件；文件变化时自动重读（热加载）。损坏时保留上次可用配置。"""
    try:
        mtime = os.path.getmtime(_RULES_PATH)
    except OSError:
        return {"detect": [], "clean": [], "regex_refs": {}, "wordlist": {}}
    if _cache["mtime"] != mtime:
        try:
            with open(_RULES_PATH, encoding="utf-8") as f:
                data = json.load(f)
            _cache["data"] = data
            _cache["mtime"] = mtime
        except Exception:
            # 配置语法错误时沿用旧配置，避免清洗链路崩溃
            if _cache["data"] is None:
                _cache["data"] = {"detect": [], "clean": [], "regex_refs": {}, "wordlist": {}}
                _cache["mtime"] = mtime
    return _cache["data"] or {"detect": [], "clean": [], "regex_refs": {}, "wordlist": {}}


def get_wordlist(name: str) -> list:
    """按名读取词表（wordlist 节）。不存在返回空 list。"""
    return load_rules().get("wordlist", {}).get(name, []) or []


def _build_pattern(item, data):
    """把 regex_refs 条目编译为正则。item 可为字符串，或 {template, words} 模板。"""
    if isinstance(item, str):
        try:
            return re.compile(item)
        except re.error:
            return None
    if isinstance(item, dict) and "template" in item:
        template = item["template"]
        for i, ref in enumerate(item.get("words", [])):
            words = data.get("wordlist", {}).get(ref, [])
            joined = "|".join(re.escape(str(w)) for w in words)
            template = template.replace("{words%d}" % i, joined)
        try:
            return re.compile(template)
        except re.error:
            return None
    return None


def get_regex(name: str):
    """按名读取编译后的正则（regex_refs 节），支持 template 型自动拼接词表。不存在返回 None。"""
    data = load_rules()
    mtime = _cache["mtime"]
    cached = _regex_cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    item = data.get("regex_refs", {}).get(name)
    if item is None:
        return None
    pat = _build_pattern(item, data)
    if pat is not None:
        _regex_cache[name] = (mtime, pat)
    return pat


def _compile(rule):
    try:
        return re.compile(rule.get("regex", ""))
    except re.error:
        return None


def apply_config_detect(text: str) -> dict:
    """执行全部 detect 规则，返回 {特征名: 命中数}（仅 >= threshold 的项）。"""
    report = {}
    for rule in load_rules().get("detect", []):
        pat = _compile(rule)
        if not pat:
            continue
        n = len(pat.findall(text))
        if n >= int(rule.get("threshold", 1)):
            report[rule.get("name", "未命名特征")] = n
    return report


def apply_config_clean(text: str) -> tuple:
    """执行全部 clean 规则，返回 (清洗后文本, {stats_key: 替换次数})。"""
    stats = {}
    for rule in load_rules().get("clean", []):
        pat = _compile(rule)
        if not pat:
            continue
        action = rule.get("action", "delete")
        if action == "delete":
            new_text, n = pat.subn("", text)
        elif action == "replace":
            new_text, n = pat.subn(rule.get("replacement", ""), text)
        elif action == "keep_group":
            g = int(rule.get("group", 1))
            new_text, n = pat.subn(lambda m, g=g: m.group(g), text)
        elif action == "redup":
            # 白名单外的单字叠字病句 → 删重复字；合法叠词自动跳过（白名单来自配置）
            redup_ok = frozenset(get_wordlist("REDUP_OK"))
            hits = [m.group(0) for m in pat.finditer(text)
                    if m.group(0) not in redup_ok and m.group(1) * 2 not in redup_ok]
            n = len(hits)
            if n:
                new_text = text
                for h in hits:
                    new_text = new_text.replace(h, h[0], 1)
            else:
                continue
        else:
            continue
        if n:
            stats[rule.get("stats_key", rule.get("name", "config"))] = n
            text = new_text
    return text, stats
