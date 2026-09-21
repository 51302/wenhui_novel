# -*- coding: utf-8 -*-
"""生成后 AI 味检测评分（纯代码，不调 LLM，零成本）。

复用 conf/ai_feature_rules.json 的 detect 规则做正则命中计数，
再叠加项目对齐的统计特征（破折号/明喻/句长突发度/短句占比/五感），
输出 0-100 评分与命中明细，供生成链路记录日志/后续门禁用。

评分口径与 novel-anti-ai skill 一致：高危项 +12、超限项 +6、节奏项 +6。
只读不改文本——去味仍由 text_cleaner 程序化清洗负责。
"""
import json
import os
import re
import threading

_RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "conf", "ai_feature_rules.json",
)

_cache = {"mtime": None, "rules": []}
_lock = threading.Lock()


def _load_detect_rules() -> list:
    """热加载 ai_feature_rules.json 的 detect 数组（带 mtime 缓存，损坏沿用旧值）。"""
    try:
        mtime = os.path.getmtime(_RULES_PATH)
    except OSError:
        return list(_cache["rules"])
    if _cache["mtime"] == mtime:
        return list(_cache["rules"])
    with _lock:
        try:
            mtime = os.path.getmtime(_RULES_PATH)
            if _cache["mtime"] == mtime:
                return list(_cache["rules"])
            with open(_RULES_PATH, encoding="utf-8") as f:
                data = json.load(f)
            rules = data.get("detect") or []
            _cache["rules"] = [r for r in rules if r.get("regex")]
            _cache["mtime"] = mtime
        except Exception:
            if _cache["rules"] is None:
                _cache["rules"] = []
                _cache["mtime"] = mtime
    return list(_cache["rules"])


# 与 novel-anti-ai / UNIVERSAL_ANTI_AI_GUIDE 口径一致的统计特征
_SIMILE_WORDS = ("像", "仿佛", "如同", "宛如", "犹如", "好似")
_SENSE_WORDS = {
    "视觉": ("看见", "看到", "目光", "眼前", "色", "光"),
    "听觉": ("听到", "声响", "声音", "传来", "嗡", "响"),
    "嗅觉": ("闻到", "气味", "香气", "腥", "臭", "味"),
    "触觉": ("触到", "冰凉", "滚烫", "勒", "疼", "麻"),
    "味觉": ("尝到", "苦涩", "甘甜", "酸", "辣", "咸"),
}


def _split_sentences(text: str):
    return [s for s in re.split(r"[。！？!?；\n]", text) if s.strip()]


def _burstiness_factor(text: str) -> float:
    """句长突发度：句子长短越悬殊越接近 1。全篇匀长 → 0。"""
    sentences = _split_sentences(text)
    if len(sentences) < 4:
        return 0.5
    lengths = [len(s) for s in sentences]
    mean = sum(lengths) / len(lengths)
    if mean <= 0:
        return 0.5
    variance = sum((n - mean) ** 2 for n in lengths) / len(lengths)
    return min(1.0, (variance ** 0.5) / mean)


def score_ai_taste(text: str, max_chars: int = 4000) -> dict:
    """对文本做 AI 味评分（对齐 novel-anti-ai 口径）。

    :param text: 生成后正文
    :param max_chars: 采样上限（尾部样本即可代表，控制耗时）
    :return: {"score": 0-100, "level": 判定, "items": [名称+命中数], "burstiness": float}
    """
    result = {"score": 0, "level": "干净", "items": [], "burstiness": 0.0}
    sample = text[-max_chars:] if len(text) > max_chars else text
    if len(sample) < 200:
        result["level"] = "样本不足"
        result["items"].append({"name": "样本不足200字，不做评分", "count": 0})
        return result

    score = 0
    items = []

    # ---- 高危项（+12）----
    em_dash = sample.count("——")
    if em_dash >= 1:
        score += 12
        items.append({"name": "破折号——（要求=0）", "count": em_dash})

    not_is = len(re.findall(r"不是[^，。；！？]{1,20}[，,]是", sample))
    if not_is >= 2:
        score += 12
        items.append({"name": "不是X是Y 解释句（上限1）", "count": not_is})

    neg_triple = len(re.findall(r"(?:不是[^，。；！？]{1,10}，){2,}不是|(?:没有[^，。；！？]{1,10}，){2,}没有", sample))
    if neg_triple >= 1:
        score += 12
        items.append({"name": "否定三连排比", "count": neg_triple})

    # ---- 超限项（+6）----
    simile = sum(sample.count(w) for w in _SIMILE_WORDS)
    if simile > 3:
        score += 6
        items.append({"name": f"明喻>{3}处（现{simile}）", "count": simile})

    jp_para = len(re.findall(r"(?m)^是[^，。；！？]{1,20}[。．]", sample))
    if jp_para > 1:
        score += 6
        items.append({"name": "判断句独立成段（上限1）", "count": jp_para})

    senses_hit = sum(1 for words in _SENSE_WORDS.values() if any(w in sample for w in words))
    if senses_hit > 2:
        score += 6
        items.append({"name": f"五感命中>{2}种（现{senses_hit}）", "count": senses_hit})

    weiwei = len(re.findall(r"微微[^\s，。；！？]{1,4}", sample))
    if weiwei >= 1:
        score += 6
        items.append({"name": "微微X 弱化副词（项目要求一律删）", "count": weiwei})

    ellipsis = sample.count("……")
    if ellipsis > 2:
        score += 6
        items.append({"name": f"省略号……>{2}处（现{ellipsis}）", "count": ellipsis})

    # ---- 高危项补强：点题/升华收尾（HUMAN_VOICE_MANDATE 禁工整收尾）----
    summing = len(re.findall(r"这一刻|这一切|一切的一切|他终于明白|他终于懂了|命运的安排|仿佛一切都是注定", sample))
    if summing >= 1:
        score += 12
        items.append({"name": "点题/升华收尾词", "count": summing})

    # ---- 节奏项（+6）----
    sentences = _split_sentences(sample)
    total = len(sentences)
    short_para = sum(1 for s in sentences if len(s) <= 12)
    ratio = short_para / total if total else 0
    if not (0.15 <= ratio <= 0.35):
        score += 6
        items.append({"name": f"短句独立段占比不在15%-35%（现{ratio:.0%}）", "count": short_para})

    burst = _burstiness_factor(sample)
    result["burstiness"] = round(burst, 3)
    if burst < 0.35:
        score += 6
        items.append({"name": f"句长突发度低（{burst:.2f}，句长偏均匀）", "count": 0})

    # ---- ai_feature_rules.json detect 规则命中（每条命中≥threshold 计 1 项 +6）----
    rules_hit = 0
    for rule in _load_detect_rules():
        try:
            regex = rule.get("regex", "")
            if not regex:
                continue
            count = len(re.findall(regex, sample))
            threshold = int(rule.get("threshold", 1))
            if count >= threshold:
                rules_hit += 1
                if rules_hit <= 6:  # 明细最多列 6 条，避免日志爆炸
                    items.append({"name": rule.get("name", "规则"), "count": count})
        except re.error:
            continue
    if rules_hit:
        score += 6 * rules_hit

    result["score"] = min(100, score)
    result["items"] = items
    if result["score"] <= 20:
        result["level"] = "干净"
    elif result["score"] <= 40:
        result["level"] = "大体像人"
    elif result["score"] <= 60:
        result["level"] = "混合"
    else:
        result["level"] = "偏AI/纯AI腔"
    return result
