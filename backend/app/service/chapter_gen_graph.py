"""章节创作 Agent：LangGraph 状态图编排

把 generate_with_ai / regenerate_with_ai / continue_with_ai 三条命令式链路
重构为 StateGraph 显式编排，节点函数仅封装现有 service 方法，业务逻辑零改动：

  chapter 子图（mode=new / regenerate）:
    START → repair_load → assign → retrieve_memory → prev_ending → build_prompt
          → call_llm →(error→END | ok→postprocess)→ save → END

  continue 子图（mode=continue）:
    START → load_existing → call_continue_api
          →(error→END | ok→append_save)→ refresh_memory → END

价值：
  - 每步中间状态可观测/可断点（State 即状态快照）
  - 失败路径显式路由（call_llm / call_continue_api → error → END）
  - 未来要加「AI检测超标 → LLM定向改写 → 复检」回环，只需在 postprocess 后加一条条件边
"""

import json
import os
import re
import uuid
from typing import TypedDict, Any, Awaitable, Callable

from app.prompts.chapter_prompts import get_memory_category_names
from langgraph.graph import StateGraph, START, END
from app.utils.logger import system_logger

__all__ = ["ChapterGenState", "run_chapter_gen", "get_chapter_graph", "get_continue_graph"]


def _log_memory_breakdown(memory_body: str, tag: str = ""):
    """解析记忆体并输出各维度字数统计（调用API前使用）"""
    import re
    if not memory_body:
        system_logger.info(f"[记忆体-调用前] {tag} 记忆体为空")
        return
    sections = re.split(r'\n(?=【)', memory_body)
    parts = []
    total = 0
    for sec in sections:
        m = re.match(r'【(.+?)】', sec)
        if m:
            dim = m.group(1)
            char_count = len(sec)
            total += char_count
            parts.append(f"{dim}={char_count}字")
    system_logger.info(
        f"[记忆体-调用前] {tag} 共{len(parts)}个维度 | {' | '.join(parts)} | 总计={total}字")


class ChapterGenState(TypedDict, total=False):
    """章节生成共享状态（LangGraph State）

    - 入参字段：mode / db / novel_unique_id / chapter_unique_id / user_id 等
    - 中间产物：各节点写入，最终态即一次生成的完整轨迹
    """
    # ---- 入参（generate / regenerate / continue 通用）----
    mode: str                        # "new" | "regenerate" | "continue"
    novel_unique_id: str
    user_id: int
    chapter_name: str
    chapter_summary: str
    word_count: int
    author_style: str
    chapter_template: str
    skills: str
    skill_ids: str
    use_anti_ai: bool
    on_chunk: Callable[[str], Awaitable[None]] | None
    created_by: str
    db: Any                          # SQLAlchemy Session（LangGraph 不序列化 state，可直接持有）
    # regenerate 专属
    chapter_unique_id: str
    # ---- 中间产物 ----
    counts: dict                     # 三源统计
    memory_body: str                 # 修复+检索后记忆
    next_num: int                    # 新章节号（new）
    fill_mode: str                   # outline / overwrite / new
    fill_row: Any                    # 待填充/覆盖的 MySQL 草稿行
    title: str                       # 规范化章节名
    summary: str                     # 有效概要（含 Redis 缓存兜底）
    cur_num: int                     # 当前章号（regenerate/continue）
    chapter: Any                     # 目标章对象
    last_ending: str                 # 上一章末尾 500 字
    dup_text: str                    # 查重文本（最近 200 字）
    settings: dict
    character_cards: list
    prompt: str
    skill_prompt: str
    selected_skills: list
    effective_skills: list
    skill_versions: dict
    generated_text: str
    clean_stats: dict
    summary_scope_result: dict
    actual_word_count: int
    richness: dict                   # 丰富度指标（句数/对白占比），驱动增厚补齐
    fact_check_result: str           # PASS / SKIP / UNKNOWN 或合法幻觉列表原文
    review_skill: dict
    fact_check_warnings: list
    hallucinations: list             # 幻觉条目列表
    rewrite_count: int               # 已执行的幻觉定向改写轮数（防死循环）
    error: str                       # 失败出口
    # continue 专属
    existing_content: str
    continued_text: str
    total_word_count: int


# ============================================================
# chapter 子图节点（mode=new / regenerate 共用）
# ============================================================

async def node_repair_load(state: dict) -> dict:
    """加载记忆体（优先从Redis快速加载；三源修复仅在Redis缺失时触发）

    regenerate 模式先查章获得 novel_unique_id（原方法在查章后加载记忆），
    并把 chapter 写入 state 供 node_assign 复用（避免二次查询）。
    """
    from app.config import get as cfg
    from app.dao.chapter_dao import ChapterDAO
    from app.service.chapter_gen_service import ChapterGenService

    novel_unique_id = state.get("novel_unique_id") or ""
    if not novel_unique_id and state.get("mode") == "regenerate":
        chapter = ChapterDAO.get_by_unique_id(state["db"], state["chapter_unique_id"])
        if not chapter:
            return {"error": "章节不存在"}
        novel_unique_id = chapter.novel_unique_id
        result: dict = {"memory_body": "", "chapter": chapter, "novel_unique_id": novel_unique_id}
    else:
        result = {}

    # 快速加载：优先从Redis获取，不触发三源修复
    from app.service.chapter_service import ChapterService
    memory_body = ChapterService._load_memory(novel_unique_id)

    # 去重：Redis可能积累了重复维度段，按维度名合并去重
    if memory_body:
        import re as _re
        _sections = _re.split(r'\n(?=【)', memory_body)
        _dims = {}
        for _sec in _sections:
            _m = _re.match(r'【(.+?)】', _sec)
            if _m:
                _name = _m.group(1)
                _dims[_name] = (_dims[_name] + "\n" + _sec.split("\n", 1)[-1]
                                if _name in _dims else _sec)
            elif _dims:
                # 没有标题的段落追加到上一个维度
                _last = list(_dims.keys())[-1]
                _dims[_last] += "\n" + _sec
        memory_body = "\n\n".join(_dims.values())
        system_logger.info(f"[记忆体去重] 去重后 {len(_dims)} 个维度，{len(memory_body)} 字")

    if not memory_body:
        # Redis无缓存时才触发三源修复（会消耗额外AI调用）
        skip_repair = cfg("memory.skip_repair_on_generate", False)
        if skip_repair:
            system_logger.info(f"[三源修复] 跳过（skip_repair_on_generate=true），记忆体为空")
            memory_body = ""
        else:
            memory_body = await ChapterGenService.repair_and_load_memory(novel_unique_id, state["db"])

    result["memory_body"] = memory_body
    return result


async def node_assign(state: dict) -> dict:
    """章节号分配 + 概要解析

    - new：三源统计 → 概要草稿填充 / 覆盖旧正文草稿 / 新建，三路取一
    - regenerate：解析当前章号 cur_num + 概要（草稿阶段从 Redis 缓存补充）
    """
    from app.dao.chapter_dao import ChapterDAO
    from app.service.chapter_service import ChapterService
    from app.service.chapter_gen_service import ChapterGenService

    mode = state.get("mode")
    novel_unique_id = state["novel_unique_id"]

    if mode == "regenerate":
        # 复用 node_repair_load 已加载的 chapter；防御性兜底再查一次
        chapter = state.get("chapter") or ChapterDAO.get_by_unique_id(
            state["db"], state["chapter_unique_id"])
        if not chapter:
            return {"error": "章节不存在"}
        cur_num = ChapterGenService.chapter_no(chapter)
        if cur_num <= 0:
            return {"error": "章节号解析失败，无法确定上一章"}
        summary = (state.get("chapter_summary") or "").strip() or (chapter.chapter_summary or "").strip()
        if not summary:
            # 草稿阶段概要不落库（发布后才转入 MySQL）：从 Redis 缓存补充
            try:
                cached = ChapterService._get_outline_cache(chapter.novel_unique_id)
                match = next((o for o in cached if (o.get("chapter_number") or 0) == cur_num), None)
                if match:
                    summary = (match.get("chapter_summary") or "").strip()
            except Exception:
                pass
        if not summary:
            return {"error": "章节缺少概要，无法重新生成正文"}
        return {
            "chapter": chapter,
            "novel_unique_id": chapter.novel_unique_id,
            "cur_num": cur_num, "summary": summary, "title": chapter.chapter_name,
        }

    # ---- mode == "new"：章节号分配（优先级 = 填充概要草稿 → 覆盖正文草稿 → 新建）----
    counts = ChapterGenService.count_sources(novel_unique_id, state["db"])
    mysql_all = ChapterDAO.get_by_novel_id(state["db"], novel_unique_id)
    # 概要草稿：未发布、无正文（word_count=0）、有概要内容 → 生成正文时填充，避免章节号错位
    outline_drafts = [c for c in mysql_all
                      if not c.is_published and not (c.word_count or 0)
                      and (c.chapter_summary or "").strip()]
    # 已有正文草稿：未发布且有正文字数 → 每作品仅保留一个，生成时覆盖最新的那个
    body_drafts = [c for c in mysql_all if not c.is_published and (c.word_count or 0) > 0]

    if outline_drafts:
        next_num = min(c.chapter_number or 0 for c in outline_drafts)
        fill_mode = "outline"
        fill_row = next((c for c in outline_drafts if c.chapter_number == next_num), None)
    elif body_drafts:
        overwrite_target = max(body_drafts, key=lambda c: c.chapter_number or 0)
        next_num = overwrite_target.chapter_number or 0
        fill_mode = "overwrite"
        fill_row = overwrite_target
    else:
        # 修复可能补插了 mysql 缺失章节，因此修复后重新统计再计算，避免与已补插章节号重复
        if not counts["consistent"]:
            counts = ChapterGenService.count_sources(novel_unique_id, state["db"])
        mysql_chapters = counts["mysql"]["chapters"]
        txt_chapters = counts["txt"]["chapters"]
        mysql_max = mysql_chapters[-1]["num"] if mysql_chapters else 0
        txt_max = txt_chapters[-1]["num"] if txt_chapters else 0
        next_num = max(mysql_max, txt_max) + 1
        fill_mode = "new"
        fill_row = None

    title = ChapterService._normalize_chapter_title(next_num, state.get("chapter_name", ""))
    summary = (state.get("chapter_summary") or "").strip() or ((fill_row.chapter_summary or "").strip() if fill_row else "")
    if not summary:
        try:
            cached = ChapterService._get_outline_cache(novel_unique_id)
            match = next((o for o in cached if (o.get("chapter_number") or 0) == next_num), None)
            if match:
                summary = (match.get("chapter_summary") or "").strip()
        except Exception:
            pass
    if not summary:
        return {"error": "章节缺少概要，无法生成正文"}
    try:
        cached = ChapterService._get_outline_cache(novel_unique_id)
        cached = sorted(
            (o for o in cached if isinstance(o, dict) and o.get("chapter_summary")),
            key=lambda o: int(o.get("chapter_number") or 0),
        )
        if cached:
            first = cached[0]
            first_num = int(first.get("chapter_number") or 0)
            first_summary = (first.get("chapter_summary") or "").strip()
            requested_summary = (state.get("chapter_summary") or "").strip()
            if next_num != first_num or requested_summary != first_summary:
                return {"error": f"请先使用第{first_num}章概要生成正文，发布后才能进入下一章"}
            summary = first_summary
    except Exception as exc:
        return {"error": f"校验当前章节概要失败：{exc}"}
    return {
        "counts": counts, "next_num": next_num, "fill_mode": fill_mode,
        "fill_row": fill_row, "title": title,
        "summary": summary,
    }


async def node_retrieve_memory(state: dict) -> dict:
    """按需检索对应章节的记忆（注入上限由配置控制，max_chars=0 表示不限制）"""
    from app.config import get as cfg
    from app.service.chapter_gen_service import ChapterGenService
    cur = state.get("cur_num") or state.get("next_num")
    max_chars = cfg("memory.max_inject_chars", 0)
    memory_body = ChapterGenService.retrieve_memory(
        state.get("memory_body") or "", state.get("summary") or "",
        current_chapter_num=cur, max_chars=max_chars if max_chars > 0 else None)
    return {"memory_body": memory_body}


async def node_prev_ending(state: dict) -> dict:
    from app.service.chapter_gen_service import ChapterGenService
    current_num = state.get("cur_num") if state.get("mode") == "regenerate" else state.get("next_num")
    if current_num is None or current_num < 1:
        return {"error": "章节号解析失败，无法确定上一章"}
    try:
        last_ending, dup_text, last_name = ChapterGenService.get_prev_ending(
            state["db"], state["novel_unique_id"],
            exclude_chapter_id=state.get("chapter_unique_id"),
            current_chapter_num=current_num)
    except (ValueError, OSError) as exc:
        return {"error": f"读取上一章失败：{exc}"}
    return {"last_ending": last_ending, "dup_text": dup_text}


def _join_character_text(character_cards) -> str:
    """角色卡前 6 张的关键字段拼成文本，供 Skill 选择做题材/风格命中。"""
    if not isinstance(character_cards, list):
        return ""
    return " ".join(
        str(card.get(key) or "")
        for card in character_cards[:6]
        for key in ("name", "personality", "position", "intro")
        if isinstance(card, dict)
    )


def _select_and_merge_skills(state: dict, novel_unique_id: str, character_cards,
                             summary: str, settings_content: str):
    """按作品/章节上下文选择并合并 Skill（新章生成与续写共用）。

    显式风格 = 章节级 skill_ids + 旧版 skills + 章节级 author_style + 作品默认 writing_style（继承）；
    反AI 质量层由 use_anti_ai 门控（默认开）。
    """
    from app.service.chapter_service import ChapterService
    from app.skills.merger import SkillMerger
    from app.skills.selector import SkillSelector
    explicit = ",".join(p for p in [
        state.get("skill_ids", "") or "",
        state.get("skills", "") or "",
        state.get("author_style", "") or "",
        ChapterService._get_novel_writing_style(novel_unique_id),
    ] if p)
    selection = SkillSelector().select(
        genre=ChapterService._get_novel_genre(novel_unique_id),
        summary=summary or "",
        settings=settings_content or "",
        character_text=_join_character_text(character_cards),
        explicit=explicit,
        include_quality=state.get("use_anti_ai", True),
    )
    return SkillMerger().merge(selection)


async def node_build_prompt(state: dict) -> dict:
    """作品设定 + 角色卡 + 自动模板适配 + 提示词组装（提示词工程内容不变）"""
    from app.service.chapter_service import ChapterService
    from app.service.chapter_gen_service import ChapterGenService
    settings = ChapterService._get_novel_settings(state["novel_unique_id"])
    character_cards = ChapterService._load_character_cards(state["db"], state["novel_unique_id"])
    template = state.get("chapter_template") or ""
    if not template:
        template = ChapterService._resolve_default_template(state["db"], state["novel_unique_id"])
    skill_result = _select_and_merge_skills(
        state, state["novel_unique_id"], character_cards,
        state.get("summary", ""), settings.get("content", ""))
    prompt = ChapterGenService.build_prompt(
        chapter_name=state.get("title") or state.get("chapter_name", ""),
        memory_body=state.get("memory_body", ""),
        settings_text=settings.get("content", ""),
        last_chapter_ending=state.get("last_ending", ""),
        chapter_summary=state.get("summary", ""),
        word_count=state.get("word_count", 2000),
        include_combat_meme=True,
        # 作家 Skill 已在 skill_context 中合并；不再通过旧 author_style 参数重复注入。
        author_style="",
        chapter_template=template,
        character_cards=character_cards,
        recent_duplicate_text=state.get("dup_text", ""),
        skill_context=skill_result.prompt,
        use_anti_ai=state.get("use_anti_ai", True),
    )
    system_logger.info(
        f"[Skill选择] anti_ai={state.get('use_anti_ai', True)} "
        f"selected={skill_result.skill_ids} "
        f"effective={skill_result.effective_ids} "
        f"dropped={skill_result.dropped_ids} versions={skill_result.versions}"
    )
    return {
        "settings": settings,
        "character_cards": character_cards,
        "prompt": prompt,
        "skill_prompt": skill_result.prompt,
        "selected_skills": list(skill_result.skill_ids),
        "effective_skills": list(skill_result.effective_ids),
        "skill_versions": skill_result.versions,
    }


async def node_call_llm(state: dict) -> dict:
    """调用 DeepSeek 生成正文（只调用一次，不重试不扩写）

    统一传 summary/genre：场景指南按本章概要命中注入（生成路径原为漏传，图化时对齐 regenerate）
    """
    from app.config import calc_dynamic_max_tokens
    from app.utils.logger import system_logger
    from app.service.chapter_service import ChapterService
    from app.service.ai_chat_service import estimate_tokens as _est_tok
    word_count = state.get("word_count", 2000)

    # 动态计算 max_tokens：根据实际输入大小决定输出token上限
    memory_body = state.get("memory_body", "")
    summary = state.get("summary", "")
    prompt_text = state.get("prompt", "")
    last_ending = state.get("last_ending", "")

    # 估算输入总字符数（系统提示词+记忆体+概要+用户提示词+续写尾部）
    from app.prompts.chapter_prompts import build_generate_system_prompt
    system_prompt_text = build_generate_system_prompt(
        summary=summary,
        genre=ChapterService._get_novel_genre(state["novel_unique_id"]),
        use_anti_ai=state.get("use_anti_ai", True))
    input_chars = len(system_prompt_text) + len(memory_body) + len(summary) + len(prompt_text) + len(last_ending)
    max_tokens = calc_dynamic_max_tokens(word_count, input_chars)

    # 调用前详细日志 + token 预估
    _log_memory_breakdown(memory_body, "正文生成")

    from app.service.ai_chat_service import (
        estimate_generation_tokens, log_token_estimate,
        estimate_tokens as _est_tok)
    from app.prompts.chapter_prompts import build_generate_system_prompt
    # 构建系统提示词用于预估（与 _call_generation_api 内部一致）
    system_prompt_text = build_generate_system_prompt(
        summary=summary,
        genre=ChapterService._get_novel_genre(state["novel_unique_id"]),
        use_anti_ai=state.get("use_anti_ai", True))
    token_est = estimate_generation_tokens(
        system_prompt=system_prompt_text, memory_body=memory_body,
        prompt=prompt_text, summary=summary, last_ending=last_ending,
        max_tokens=max_tokens, word_count=word_count)
    log_token_estimate("正文生成", token_est)

    genre = ChapterService._get_novel_genre(state["novel_unique_id"])
    import time
    t_ai = time.time()
    on_chunk = state.get("on_chunk")
    generated_text, err = await ChapterService._call_generation_api(
        prompt_text, max_tokens, summary=summary, genre=genre, on_chunk=on_chunk,
        use_anti_ai=state.get("use_anti_ai", True))
    ai_elapsed = time.time() - t_ai
    system_logger.info(f"[AI调用耗时] 正文生成={ai_elapsed:.1f}秒 | max_tokens={max_tokens} | 输入={input_chars}字")
    if err or not generated_text:
        return {"error": err or "章节生成失败"}
    return {"generated_text": generated_text}


def _find_repeated_dialogue(text: str, min_length: int = 12) -> list[str]:
    import re

    quotes = re.findall(r'[“"]([^”"\n]{%d,})[”"]' % min_length, text or "")
    counts = {}
    for quote in quotes:
        normalized = re.sub(r'\s+', '', quote).strip()
        counts[normalized] = counts.get(normalized, 0) + 1
    return [quote for quote, count in counts.items() if count > 1]


def _diagnose_repetition(cleaned: str, stats: dict, reference: str) -> None:
    """生成与续写共用重复诊断；仅告警，不修改正文。"""
    # 重复类清洗结果单独告警：模型"同一场景改写后重写一遍"时靠这几项暴露。
    # intra_dup=已删掉的改写重复段；intra_dup_warn=相似但未达删除阈值的疑似段；
    # long_repeat=已删掉的长句/台词逐字复读；dup_para=逐字雷同段；repeat=短句复读。
    repeat_keys = ("intra_dup", "intra_dup_warn", "long_repeat", "dup_para", "repeat")
    repeat_stats = {k: stats[k] for k in repeat_keys if stats.get(k)}
    if repeat_stats:
        system_logger.warning(f"[重复检测] {repeat_stats}")

    # 生成参照上一章结尾；续写参照已有全文。相似命中不代表语义重复，只告警。
    try:
        from app.service.chapter_service import _detect_duplicate_sentences
        dup_check = _detect_duplicate_sentences(cleaned, reference)
        if dup_check.get("has_duplicates"):
            hits = [d.get("generated", "")[:30]
                    for d in dup_check.get("duplicate_sentences", [])[:3]]
            system_logger.warning(
                f"[跨章查重] 与参照前文重复 {dup_check['duplicate_count']} 句: {hits}")
    except Exception as e:
        system_logger.warning(f"[跨章查重] 检测失败（不影响生成）: {e}")


def _measure_richness(text: str, target: int) -> dict:
    """内容丰富度指标：句数 + 对白占比（与测试口径一致）

    - sent_count: 按 。！？!? 切分的有效句数
    - dialog_ratio: 「」/“”/"" 引号内容字数占比
    - thin_reasons: 触发增厚补齐的原因列表（句数过少 / 对白过少）
    """
    flat = re.sub(r'\s', '', text or '')
    if not flat:
        return {"sent_count": 0, "dialog_ratio": 0.0, "thin_reasons": ["正文为空"]}
    sents = [s for s in re.split(r'[。！？!?]', re.sub(r'\n', '', text or '')) if s.strip()]
    sent_count = len(sents)
    dial = sum(len(m) for m in re.findall(r'[「“"][^」”"]*[」”"]', text or ''))
    dial_ratio = dial / max(1, len(flat))

    thin = []
    # 句数下限：按目标字数折算（2000字 → 80句），低于即视为叙述过薄
    sent_floor = max(int(target / 25), 40)
    if sent_count < sent_floor:
        thin.append(f"句数{sent_count}<{sent_floor}")
    # 对白占比下限 8%：动作/心理戏占比过高时读者体感沉闷
    if dial_ratio < 0.08:
        thin.append(f"对白{dial_ratio:.0%}<8%")
    return {"sent_count": sent_count, "dialog_ratio": round(dial_ratio, 4),
            "thin_reasons": thin}


async def _fill_to_min_word_count(
    state: dict,
    cleaned: str,
    stats: dict,
    before_len: int,
    target: int,
    lower_bound: int,
    reasons: list | None = None,
) -> None:
    """字数/丰富度补齐（仅补 1 次，写入 state['generated_text'/'clean_stats'/'actual_word_count']）。

    用续写 Prompt 模板补齐剩余字数，context 取当前正文末尾 tail_chars 字。
    追加内容走同一套程序化清洗，不新增新事件/新人物/新设定。

    reasons: 触发原因列表（["字数不足"] / ["句数少", "对白少"]），
             含丰富度项时追加对白推进与短句拆分约束。
    """
    from app.config import get as cfg
    from app.service.ai_chat_service import chat_completion, log_ai_call
    from app.prompts.chapter_prompts import (
        CONTINUE_PROMPT, CONTINUE_CHAOT_RULES, SELF_CHECK_LIST,
        build_generate_system_prompt,
    )
    from app.service.text_cleaner import clean_generated_text
    from app.config import (
        deepseek_writer_model, deepseek_writer_api_key,
        deepseek_writer_base_url, gen_api_timeout,
    )

    reasons = reasons or ["字数不足"]
    thin_reasons = [r for r in reasons if r not in ("字数不足", "正文为空")]

    chapter = state.get("chapter")
    chapter_name = chapter.chapter_name if chapter else ""
    summary = state.get("summary") or (chapter.chapter_summary if chapter else "") or ""
    memory_body = state.get("memory_body", "") or ""
    tail_chars = cfg("ai.api_params.continue_writing.tail_chars", 2000)
    context_content = cleaned[-tail_chars:] if len(cleaned) > tail_chars else cleaned
    if "字数不足" in reasons:
        remaining = max(target - before_len, 800)  # 至少补 800
    else:
        # 丰富度补齐：字数已达标，只补一段对白密集的场景来稀释比值
        remaining = 800

    # 疯批专属规则（沿用续写图的判断逻辑）
    chaot_rules = ""
    try:
        cc = state.get("character_cards")
        if isinstance(cc, list) and cc:
            pers_all = (cc[0].get("personality") or "") + " " + (cc[0].get("intro") or "")
            if _re.search(r'疯|疯批|疯癫|癫|偏执|病娇|嘴贱|反骨|狂', pers_all):
                chaot_rules = CONTINUE_CHAOT_RULES
    except Exception:
        pass

    fill_prompt = CONTINUE_PROMPT.format(
        protagonist_block="",
        chaot_rules=chaot_rules,
        memory_body=memory_body,
        chapter_name=chapter_name,
        chapter_summary=summary,
        context_content=context_content,
        word_count=remaining,
        min_words=remaining,
    ) + (
        "\n\n🔴【补齐模式特殊约束】"
        f"\n触发原因：{'、'.join(reasons)}；当前正文 {before_len} 字，本次补约 {remaining} 字。"
        "\n严格禁止新增概要外的新事件 / 新人物 / 新设定。"
        "\n优先补充：最后事件的后续细节、现场反应、人物身体感受、环境氛围、"
        "未解决的已有疑问。写完剩余字数即停，不得额外收尾、不得升华。"
    )
    if thin_reasons:
        fill_prompt += (
            "\n\n🟠【增厚约束】正文叙述过薄（" + "、".join(thin_reasons) + "），续写部分必须："
            "\n1. 以人物对话推进情节，对白字数占比不低于 50%，用对话交代信息、制造张力，"
            "避免用叙述句复述已发生的事件。"
            "\n2. 每句控制在 25 字以内，长短句交替，杜绝一句到底的长叙述。"
            "\n3. 对白要短促、带情绪、有潜台词，人物语气需与角色卡一致。"
            "\n4. 不堆形容词、不用排比铺陈，靠动作与台词撑起画面。"
        )

    fill_msgs = [
        {"role": "system", "content": build_generate_system_prompt(
            summary, state.get("genre", ""),
            use_anti_ai=state.get("use_anti_ai", True))},
        {"role": "user",
         "content": fill_prompt + (
             "\n\n" + SELF_CHECK_LIST if state.get("use_anti_ai", True) else "")},
    ]

    cw_params = cfg("ai.api_params.continue_writing", {})
    max_tokens = min(max(int(remaining * 2), 1200), 5000)
    params = {
        "messages": fill_msgs,
        "model": deepseek_writer_model(),
        "max_tokens": max_tokens,
        "timeout": cw_params.get("timeout", gen_api_timeout()),
        "thinking": {"type": "disabled"},
        "temperature": cw_params.get("temperature", 0.85),
        "top_p": cw_params.get("top_p", 0.92),
        "frequency_penalty": cfg("ai.generation.frequency_penalty", 0.5),
        "presence_penalty": cfg("ai.generation.presence_penalty", 0.5),
    }
    _wk = deepseek_writer_api_key()
    _wu = deepseek_writer_base_url()
    if _wk:
        params["base_url"] = _wu
        params["api_key"] = _wk

    try:
        filled, err, usage = await chat_completion(**params)
        log_ai_call("字数补齐", fill_msgs, filled, err, usage,
                    model=deepseek_writer_model())
        if err:
            system_logger.warning(
                f"[补齐] AI 失败（保留原 {before_len} 字）: {err}")
            state["generated_text"] = cleaned
            state["clean_stats"] = stats
            state["actual_word_count"] = before_len
            return
        if not filled:
            system_logger.warning("[补齐] AI 返回空（保留原文本）")
            state["generated_text"] = cleaned
            state["clean_stats"] = stats
            state["actual_word_count"] = before_len
            return
        fill_clean, fill_stats = (
            clean_generated_text(filled)
            if state.get("use_anti_ai", True) else (filled, {}))
        merged = cleaned.rstrip() + "\n\n" + fill_clean
        merged_len = len(merged)
        after = _measure_richness(merged, target)
        system_logger.info(
            f"[补齐-{'+'.join(reasons)}] 原目标{target} 下限{lower_bound} "
            f"补前{before_len} → 补后{merged_len} (+{merged_len - before_len}) | "
            f"句数{after['sent_count']} 对白{after['dialog_ratio']:.0%}"
        )
        stats_copy = dict(stats)
        stats_copy.setdefault("append_fill", {})
        stats_copy["append_fill"].update(fill_stats)
        state["generated_text"] = merged
        state["clean_stats"] = stats_copy
        state["actual_word_count"] = merged_len
    except Exception as e:
        system_logger.warning(
            f"[补齐] 异常（保留原 {before_len} 字）: {e}")
        state["generated_text"] = cleaned
        state["clean_stats"] = stats
        state["actual_word_count"] = before_len


async def node_postprocess(state: dict) -> dict:
    """后处理：无损概要诊断 → 超长上限截断 → 程序化清洗。"""
    from app.config import gen_hard_cap_ratio, gen_hard_cap_min_extra
    from app.service.chapter_service import ChapterService
    from app.service.text_cleaner import clean_generated_text
    text = state["generated_text"]
    summary = state.get("summary") or ""
    word_count = state.get("word_count", 2000)
    if summary:
        text = ChapterService._trim_to_summary_boundary(text, summary)
    hard_cap = max(int(word_count * gen_hard_cap_ratio()), word_count + gen_hard_cap_min_extra())
    if len(text) > hard_cap:
        cut = text[:hard_cap]
        for sep in ("\n\n", "\n", "。", "！", "？"):
            idx = cut.rfind(sep)
            if idx > int(hard_cap * 0.8):
                cut = cut[:idx + len(sep)]
                break
        text = cut
    cleaned, stats = clean_generated_text(text) if state.get("use_anti_ai", True) else (text, {})
    _diagnose_repetition(cleaned, stats, state.get("dup_text") or "")
    repeated_dialogue = _find_repeated_dialogue(cleaned)
    if repeated_dialogue:
        examples = "；".join(item[:40] for item in repeated_dialogue[:3])
        return {"error": f"正文存在逐字重复对白，需重新生成：{examples}", "generated_text": cleaned,
                "clean_stats": stats, "actual_word_count": len(cleaned)}

    # 生成后 AI 味评分（纯代码，只记录不改写；与 novel-anti-ai skill 口径一致）
    ai_quality = {}
    try:
        from app.service.ai_detector import score_ai_taste
        ai_quality = score_ai_taste(cleaned)
        if ai_quality.get("score", 0) > 40:
            names = [i.get("name", "") for i in ai_quality.get("items", [])[:6]]
            system_logger.warning(
                f"[AI味检测] score={ai_quality.get('score')}（{ai_quality.get('level')}）"
                f" 命中项: {names}"
            )
        else:
            system_logger.info(
                f"[AI味检测] score={ai_quality.get('score')}（{ai_quality.get('level')}）"
                f" burstiness={ai_quality.get('burstiness')}"
            )
    except Exception as e:
        system_logger.warning(f"[AI味检测] 评分失败（不影响生成）: {e}")

    # ===== 字数硬校验 + 内容丰富度校验：不达标自动补齐（仅补 1 次，防死循环） =====
    target = state.get("word_count", 2000)
    current_len = len(cleaned)
    lower_bound = int(target * 0.8)  # 允许 20% 浮动，与提示词"上下浮动"对齐
    richness = _measure_richness(cleaned, target)
    reasons = []
    if current_len < lower_bound:
        reasons.append("字数不足")
    reasons.extend(richness["thin_reasons"])
    if reasons:
        system_logger.info(
            f"[丰富度] 句数{richness['sent_count']} 对白{richness['dialog_ratio']:.0%} "
            f"→ 触发补齐：{'、'.join(reasons)}")
        await _fill_to_min_word_count(
            state, cleaned, stats, current_len, target, lower_bound, reasons)
        cleaned = state["generated_text"]
        stats = state["clean_stats"]
        current_len = state["actual_word_count"]
        richness = _measure_richness(cleaned, target)
        system_logger.info(
            f"[丰富度] 补齐后 句数{richness['sent_count']} 对白{richness['dialog_ratio']:.0%} "
            f"字数{current_len} 仍薄={richness['thin_reasons'] or '否'}")

    return {
        "generated_text": cleaned,
        "clean_stats": stats,
        "actual_word_count": len(cleaned),
        "richness": richness,
        "ai_quality_score": ai_quality,
    }


def _strict_fact_object(pairs):
    from app.service.chapter_review_service import _strict_object
    return _strict_object(pairs)


def _normalize_fact_items(items, content: str) -> list:
    from app.service.chapter_review_service import _normalize_items
    return _normalize_items(items, content)


async def node_content_check(state: dict) -> dict:
    from app.config import get as cfg
    from app.service.chapter_review_service import ChapterReviewService

    try:
        if not cfg("ai.fact_check.enabled", True) or cfg("ai.mock_generate", False):
            return {"hallucinations": [], "fact_check_result": "SKIP", "fact_check_warnings": []}
        continuing = state.get("mode") == "continue"
        result = await ChapterReviewService.check(
            content=state.get("continued_text" if continuing else "generated_text") or "",
            memory_body=state.get("memory_body") or "",
            summary=state.get("summary") or "",
            existing_content=state.get("existing_content", "") if continuing else "",
            mode=state.get("mode", "new"),
            settings_text=(state.get("settings") or {}).get("content", ""),
            character_cards=state.get("character_cards") or [],
        )
        if result.get("状态码") != 200:
            raise ValueError(result.get("消息", "核查失败"))
        data = result["数据"]
        items = data["hallucinations"]
        return {
            "hallucinations": items,
            "fact_check_result": (json.dumps(items, ensure_ascii=False)
                                  if data["review_result"] == "FOUND" else data["review_result"]),
            "fact_check_warnings": data["review_warnings"],
            "review_skill": data.get("skill"),
        }
    except Exception as exc:
        # 复检失败（改写后第二轮核查挂了）不推翻已改写的正文：降级为 UNKNOWN 继续走保存
        if state.get("rewrite_count", 0) > 0:
            warning = f"改写后复检未完成：{exc}；沿用改写后正文，请人工核对"
            system_logger.warning(warning)
            return {"hallucinations": [], "fact_check_result": "UNKNOWN",
                    "fact_check_warnings": [warning]}
        warning = f"章节核查未完成：{exc}；结果未知，请人工核对"
        system_logger.warning(warning)
        return {"error": f"章节核查失败：{exc}", "hallucinations": [],
                "fact_check_result": "UNKNOWN", "fact_check_warnings": [warning]}


# ===== 幻觉定向改写回环 =====

# 触发阈值：medium+high 幻觉 ≥3 条，或总数 ≥8 条 → 认定"幻觉超标"，定向改写一轮
_REWRITE_MIN_SEVERE = 3
_REWRITE_MIN_TOTAL = 8
_REWRITE_MAX_ROUNDS = 1


def _needs_rewrite(state: dict) -> bool:
    """幻觉是否超标且还有改写轮次可用（最多 N 轮，防死循环）"""
    if state.get("error"):
        return False
    if state.get("mode") == "continue":
        return False  # 续写模式正文是追加的，改写会破坏已发布内容的连续性
    if state.get("rewrite_count", 0) >= _REWRITE_MAX_ROUNDS:
        return False
    items = state.get("hallucinations") or []
    if not items:
        return False
    severe = sum(1 for i in items if isinstance(i, dict)
                 and i.get("severity") in ("medium", "high"))
    hit = severe >= _REWRITE_MIN_SEVERE or len(items) >= _REWRITE_MIN_TOTAL
    if hit:
        system_logger.warning(
            f"[幻觉改写] 幻觉超标：共{len(items)}条（medium+high={severe}）"
            f" → 触发第{state.get('rewrite_count', 0) + 1}轮定向改写")
    return hit


async def node_rewrite(state: dict) -> dict:
    """幻觉定向改写：按核查建议修复正文，复检在 content_check 节点完成。"""
    from app.service.chapter_review_service import ChapterReviewService
    from app.service.text_cleaner import clean_generated_text

    try:
        items = state.get("hallucinations") or []
        text = state.get("continued_text") if state.get("mode") == "continue" \
            else state.get("generated_text") or ""
        result = await ChapterReviewService.calibrate(
            content=text,
            hallucinations=items,
            settings_text=(state.get("settings") or {}).get("content", ""),
            character_cards=state.get("character_cards") or [],
            memory_body=state.get("memory_body") or "",
            summary=state.get("summary") or "",
        )
        if result.get("状态码") != 200:
            raise ValueError(result.get("消息", "改写失败"))
        new_text = (result["数据"].get("content") or "").strip()
        if not new_text:
            raise ValueError("改写返回空正文")

        # 改写后仍走同一套程序化清洗；字数跌破下限则放弃改写（保字数优先）
        target = state.get("word_count", 2000)
        lower_bound = int(target * 0.8)
        if state.get("use_anti_ai", True):
            new_text, new_stats = clean_generated_text(new_text)
        else:
            new_text, new_stats = new_text, {}
        if len(new_text) < lower_bound:
            system_logger.warning(
                f"[幻觉改写] 改写后字数{len(new_text)}<{lower_bound}，放弃本轮改写保留原文")
            return {"rewrite_count": state.get("rewrite_count", 0) + 1}

        # 改写不得删掉过多内容（防模型只回片段）
        origin_len = len(text)
        if len(new_text) < origin_len * 0.6:
            system_logger.warning(
                f"[幻觉改写] 改写后字数骤降 {origin_len}→{len(new_text)}，放弃本轮")
            return {"rewrite_count": state.get("rewrite_count", 0) + 1}

        merged_stats = dict(state.get("clean_stats") or {})
        merged_stats.setdefault("rewrite", {})
        merged_stats["rewrite"].update(new_stats)
        n = state.get("rewrite_count", 0) + 1
        system_logger.info(
            f"[幻觉改写] 第{n}轮完成：{origin_len} → {len(new_text)}字，"
            f"修复{len(items)}条幻觉，待复检")
        upd = {"generated_text": new_text, "clean_stats": merged_stats,
               "actual_word_count": len(new_text), "rewrite_count": n}
        if state.get("mode") == "continue":
            upd["continued_text"] = new_text
            upd["total_word_count"] = len(state.get("existing_content", "")) + len(new_text)
        return upd
    except Exception as exc:
        # 改写失败不阻断：记轮次并保留原文，直接进入复检/保存
        system_logger.warning(f"[幻觉改写] 失败（保留原文）: {exc}")
        return {"rewrite_count": state.get("rewrite_count", 0) + 1}


async def _save_chapter_content(
        state: dict, chapter, content: str,
        is_regenerate: bool = False,
        skip_memory_extract: bool = False) -> None:
    from sqlalchemy import text
    from app.service.chapter_service import ChapterService

    db = state["db"]
    novel_id = chapter.novel_unique_id
    uid = chapter.chapter_unique_id
    fields = ("word_count", "chapter_summary", "is_published")
    old_values = {field: getattr(chapter, field) for field in fields}
    chapter_file = ChapterService._get_chapter_txt_path(novel_id, chapter.chapter_name, uid)
    temp_file = f"{chapter_file}.{uuid.uuid4().hex}.tmp"
    old_content = None
    file_replaced = False
    snapshot = None
    try:
        if not content.strip():
            raise RuntimeError("章节正文为空")
        if os.path.exists(chapter_file):
            with open(chapter_file, "rb") as handle:
                old_content = handle.read()
        if not skip_memory_extract:
            snapshot = ChapterService._memory_snapshot(novel_id)
        os.makedirs(os.path.dirname(chapter_file), exist_ok=True)
        with open(temp_file, "wb") as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_file, chapter_file)
        file_replaced = True
        with open(chapter_file, "rb") as handle:
            if handle.read() != content.encode("utf-8"):
                raise RuntimeError("TXT正文读回不一致")
        chapter.word_count = len(content)
        if state.get("summary"):
            chapter.chapter_summary = state["summary"]
        if state.get("publish"):
            chapter.is_published = 1
        db.flush()
        row = db.execute(text(
            "SELECT word_count, chapter_summary, is_published FROM chapters WHERE chapter_unique_id = :uid"
        ), {"uid": uid}).fetchone()
        expected = (len(content), chapter.chapter_summary, chapter.is_published)
        if row is None or tuple(row) != expected:
            raise RuntimeError("MySQL字段读回不一致")
        if not skip_memory_extract:
            if not state.get("publish") or not ChapterService._memory_matches_content(
                    novel_id, chapter.chapter_name, content):
                written = await ChapterService._refresh_memory_after_generate(
                    novel_id, db, content, chapter.chapter_name, chapter.chapter_summary,
                    is_regenerate=True)
                if not written:
                    raise RuntimeError("Redis未完成本章记忆提取")
            if not ChapterService._memory_matches_content(novel_id, chapter.chapter_name, content):
                raise RuntimeError("Redis正文来源校验失败")
        db.commit()
    except BaseException as exc:
        failures = []
        try:
            db.rollback()
            for field, value in old_values.items():
                setattr(chapter, field, value)
        except Exception as restore_error:
            failures.append(f"MySQL: {restore_error}")
        try:
            if file_replaced:
                if old_content is None:
                    os.remove(chapter_file)
                else:
                    with open(chapter_file, "wb") as handle:
                        handle.write(old_content)
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception as restore_error:
            failures.append(f"TXT: {restore_error}")
        try:
            if snapshot is not None:
                ChapterService._restore_memory_snapshot(novel_id, snapshot)
        except Exception as restore_error:
            failures.append(f"Redis: {restore_error}")
        if failures:
            raise RuntimeError(f"{exc}；回滚失败：{'；'.join(failures)}") from exc
        raise

    try:
        from app.service.chapter_service import _redis
        r = _redis()
        r.delete(f"chapter:content:{uid}")
        r.delete_pattern(f"chapters:novel:{novel_id}:*")
        r.delete(f"chapters:drafts:user:{chapter.user_id}")
    except Exception as exc:
        system_logger.warning(f"章节缓存清理失败: {exc}")


async def node_save(state: dict) -> dict:
    from app.utils.task_queue import acquire_novel_lock, release_novel_lock

    mode = state.get("mode")
    novel_unique_id = state["novel_unique_id"]
    generated_text = state["generated_text"]
    actual_word_count = len(generated_text)

    lock_token = acquire_novel_lock(novel_unique_id)
    if lock_token is None:
        return {"error": "章节保存失败：未取得作品互斥锁，请稍后重试"}
    try:
        from app.dao.chapter_dao import ChapterDAO
        from app.models.chapter import Chapter as ChapterModel
        from app.service.chapter_service import ChapterService
        if mode == "regenerate":
            chapter = state["chapter"]
            await _save_chapter_content(state, chapter, generated_text, is_regenerate=True)
            return {"chapter_unique_id": chapter.chapter_unique_id, "actual_word_count": actual_word_count}

        fill_row = state.get("fill_row")
        created_new = False
        old_name = None
        if fill_row is not None:
            chapter = fill_row
            old_name = chapter.chapter_name
            old_summary = chapter.chapter_summary
            chapter.chapter_name = state["title"]
            if state.get("summary"):
                chapter.chapter_summary = state["summary"]
            old_file = ChapterService._get_chapter_txt_path(novel_unique_id, old_name, chapter.chapter_unique_id)
            new_file = ChapterService._get_chapter_txt_path(
                novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id)
            chapter_unique_id = chapter.chapter_unique_id
        else:
            created_new = True
            chapter_unique_id = uuid.uuid4().hex
            chapter = ChapterModel(
                novel_unique_id=novel_unique_id,
                user_id=state.get("user_id"),
                chapter_unique_id=chapter_unique_id,
                chapter_name=state["title"],
                chapter_number=state["next_num"],
                chapter_summary=(state.get("summary") or "").strip(),
                word_count=actual_word_count,
                is_published=0,
                created_by=state.get("created_by", ""),
            )
            state["db"].add(chapter)

        try:
            await _save_chapter_content(
                state, chapter, generated_text, skip_memory_extract=True)
        except BaseException:
            if created_new:
                try:
                    state["db"].rollback()
                except Exception as delete_error:
                    system_logger.error(f"[章节保存回滚] 新章MySQL记录删除失败: {delete_error}")
            else:
                try:
                    chapter.chapter_name = old_name
                    chapter.chapter_summary = old_summary
                    state["db"].rollback()
                except Exception as restore_error:
                    system_logger.error(f"[章节保存回滚] 草稿章节名恢复失败: {restore_error}")
            raise

        if old_name and old_file != new_file and os.path.exists(old_file):
            try:
                os.remove(old_file)
            except OSError as remove_error:
                system_logger.error(f"[章节保存] 旧TXT清理失败: {remove_error}")

        if state.get("publish"):
            try:
                cached = ChapterService._get_outline_cache(novel_unique_id)
                used_num = state.get("next_num") or (state.get("cur_num") if state.get("mode") == "regenerate" else None)
                if used_num and any((o.get("chapter_number") or 0) == used_num for o in cached):
                    kept = [o for o in cached if (o.get("chapter_number") or 0) != used_num]
                    ChapterService._write_outline_cache(novel_unique_id, kept)
                    system_logger.info(f"[概要缓存] 已删除第{used_num}章概要（正文已生成）")
            except Exception as exc:
                system_logger.warning(f"概要缓存清理失败: {exc}")
        return {"chapter_unique_id": chapter_unique_id, "actual_word_count": actual_word_count}
    finally:
        release_novel_lock(novel_unique_id, lock_token)


# ============================================================
# continue 子图节点（mode=continue）
# ============================================================

async def node_load_existing(state: dict) -> dict:
    """续写准备：读当前章已有内容（末尾 2000 字作上下文）+ 只读记忆 + 角色卡 + 疯批规则 + 组装续写 Prompt"""
    import re as _re
    from app.dao.chapter_dao import ChapterDAO
    from app.prompts.chapter_prompts import CONTINUE_CHAOT_RULES, CONTINUE_PROMPT
    from app.service.chapter_service import ChapterService

    chapter = ChapterDAO.get_by_unique_id(state["db"], state["chapter_unique_id"])
    if not chapter:
        return {"error": "章节不存在"}
    from app.service.chapter_gen_service import ChapterGenService

    cur_num = ChapterGenService.chapter_no(chapter)
    summary = (chapter.chapter_summary or "").strip()
    if not summary:
        try:
            cached = ChapterService._get_outline_cache(chapter.novel_unique_id)
            match = next((item for item in cached if item.get("chapter_number") == cur_num), None)
            if match:
                summary = (match.get("chapter_summary") or "").strip()
        except Exception:
            pass
    if not summary:
        return {"error": "章节缺少概要，无法续写正文"}
    existing_content = ChapterService._read_chapter_content_from_file(
        chapter.novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id)
    from app.config import get as cfg
    tail_chars = cfg("ai.api_params.continue_writing.tail_chars", 2000)
    context_content = existing_content[-tail_chars:] if len(existing_content) > tail_chars else existing_content

    # 记忆体：一次加载（只读优先，Redis 缓存命中不触发全量 AI 提取）
    memory_body = await ChapterService._ensure_memory(chapter.novel_unique_id, state["db"])
    memory_body = ChapterService._retrieve_relevant_memory(
        memory_body, summary, current_chapter_num=cur_num)

    # 角色卡 → 主角人设硬约束块
    character_cards = ChapterService._load_character_cards(state["db"], chapter.novel_unique_id)
    settings = ChapterService._get_novel_settings(chapter.novel_unique_id)
    skill_result = _select_and_merge_skills(
        state, chapter.novel_unique_id, character_cards,
        summary,
        settings.get("content", ""))
    protagonist_block = ""
    if isinstance(character_cards, list) and character_cards:
        try:
            main = character_cards[0]
            name = (main.get("name") or "").strip()
            pers = (main.get("personality") or "").strip()
            pos = (main.get("position") or "").strip()
            intro = (main.get("intro") or "").strip()[:800]
            if name:
                parts = [f"【🔴 主角人设硬约束（续写必须遵循，违反即作废）】主角：{name}"]
                if pers:
                    parts.append(f"性格关键词（所有言行必须符合，禁止写相反的人）：{pers}")
                if pos:
                    parts.append(f"角色定位：{pos}")
                if intro:
                    parts.append(f"人物卡（关键信息）：{intro}")
                parts.append("硬约束：续写主角的台词/选择/情绪都必须符合上述性格，禁止写与性格相反的反应"
                             "（如嘴贱型忽然恭敬、疯批型忽然乖巧、清醒疯型忽然无脑）。")
                protagonist_block = "\n".join(parts)
        except Exception:
            pass

    # 按主角性格关键词注入疯批/怼神/嘴贱专属规则（与 build_prompt 保持同一套规则）
    chaot_rules = ""
    if isinstance(character_cards, list) and character_cards:
        try:
            pers_all = (character_cards[0].get("personality") or "") + " " + (character_cards[0].get("intro") or "")
            if _re.search(r'疯|疯批|疯癫|癫|偏执|病娇|嘴贱|反骨|狂', pers_all):
                chaot_rules = CONTINUE_CHAOT_RULES
        except Exception:
            pass

    prompt = CONTINUE_PROMPT.format(
        protagonist_block=protagonist_block,
        chaot_rules=chaot_rules,
        memory_body=memory_body,
        chapter_name=chapter.chapter_name,
        chapter_summary=summary,
        context_content=context_content,
        word_count=state.get("word_count", 2500),
        min_words=max(state.get("word_count", 2500) - 500, 800),
    )
    if skill_result.prompt:
        prompt += "\n\n【本次章节 Skill 规则】\n" + skill_result.prompt
    return {
        "chapter": chapter,
        "summary": summary,
        "existing_content": existing_content,
        "memory_body": memory_body,
        "context_content": context_content,
        "settings": settings,
        "character_cards": character_cards,
        "prompt": prompt,
        "cur_num": cur_num,
        "skill_prompt": skill_result.prompt,
        "selected_skills": list(skill_result.skill_ids),
        "effective_skills": list(skill_result.effective_ids),
        "skill_versions": skill_result.versions,
    }


async def node_call_continue_api(state: dict) -> dict:
    """调用续写（system=恒定核心+场景指南，user=续写 prompt+自查清单）→ 程序化清洗"""
    from app.config import get as cfg
    from app.config import deepseek_writer_model, deepseek_writer_api_key, deepseek_writer_base_url, gen_api_timeout
    from app.service.ai_chat_service import chat_completion, chat_completion_stream, log_ai_call
    from app.prompts.chapter_prompts import SELF_CHECK_LIST, build_generate_system_prompt
    from app.service.chapter_service import ChapterService
    from app.service.text_cleaner import clean_generated_text

    chapter = state["chapter"]
    summary = state.get("summary") or chapter.chapter_summary or ""
    word_count = state.get("word_count", 2500)
    if cfg("ai.mock_generate", False):
        return {"continued_text": "压测用模拟续写内容，仅用于接口压力测试，不包含真实剧情。" * 200,
                "clean_stats": {}}
    try:
        cw_params = cfg("ai.api_params.continue_writing", {})
        cw_max = min(max(int(word_count * cw_params.get("max_tokens_multiplier", 2)),
                         cw_params.get("max_tokens_min", 1200)),
                     cw_params.get("max_tokens_max", 5000))
        cw_msgs = [
            {"role": "system", "content": build_generate_system_prompt(
                summary,
                ChapterService._get_novel_genre(chapter.novel_unique_id),
                use_anti_ai=state.get("use_anti_ai", True))},
            {"role": "user", "content": state["prompt"] + ("\n\n" + SELF_CHECK_LIST if state.get("use_anti_ai", True) else "")},
        ]

        # 调用前详细日志 + token 预估
        existing_content = state.get("existing_content", "")
        from app.service.ai_chat_service import estimate_generation_tokens, log_token_estimate
        token_est = estimate_generation_tokens(
            system_prompt=cw_msgs[0]["content"], memory_body="",
            prompt=state["prompt"], summary=summary,
            last_ending=existing_content, max_tokens=cw_max, word_count=word_count)
        log_token_estimate("续写", token_est)

        completion = chat_completion_stream if state.get("on_chunk") else chat_completion
        _wk = deepseek_writer_api_key()
        _wu = deepseek_writer_base_url()
        completion_params = {
            "messages": cw_msgs,
            "model": deepseek_writer_model(),
            "max_tokens": cw_max,
            "timeout": cw_params.get("timeout", gen_api_timeout()),
            "thinking": {"type": "disabled"},
            "temperature": cw_params.get("temperature", 0.85),
            "top_p": cw_params.get("top_p", 0.92),
            "frequency_penalty": cfg("ai.generation.frequency_penalty", 0.5),
            "presence_penalty": cfg("ai.generation.presence_penalty", 0.5),
        }
        if _wk:
            completion_params["base_url"] = _wu
            completion_params["api_key"] = _wk
        if state.get("on_chunk"):
            completion_params["on_chunk"] = state["on_chunk"]
        generated_text, err, usage = await completion(**completion_params)
        log_ai_call("续写", cw_msgs, generated_text, err, usage,
                    model=deepseek_writer_model(),
                    extra_info={"概要字数": len(summary), "max_tokens": cw_max,
                                "章节末尾字数": len(state.get("existing_content", ""))})
        is_length_truncation = "finish_reason=length" in str(err) if err else False
        if is_length_truncation:
            system_logger.warning(
                f"[续写] 输出达到长度上限（{cw_max} token），保留已生成内容继续处理")
        if err and not is_length_truncation:
            return {"error": "AI续写失败: " + (err or "未知错误")}
        cleaned_text, clean_stats = (clean_generated_text(generated_text)
                                     if state.get("use_anti_ai", True) else (generated_text, {}))
        _diagnose_repetition(cleaned_text, clean_stats, existing_content)
        repeated_dialogue = _find_repeated_dialogue(cleaned_text)
        if repeated_dialogue:
            examples = "；".join(item[:40] for item in repeated_dialogue[:3])
            return {"error": f"续写存在逐字重复对白，需重新生成：{examples}",
                    "clean_stats": clean_stats}
        return {"continued_text": cleaned_text, "clean_stats": clean_stats}
    except Exception as e:
        return {"error": f"AI续写失败: {str(e)}"}


async def node_append_save(state: dict) -> dict:
    from app.utils.task_queue import acquire_novel_lock, release_novel_lock

    chapter = state["chapter"]
    novel_unique_id = chapter.novel_unique_id
    lock_token = acquire_novel_lock(novel_unique_id)
    if lock_token is None:
        return {"error": "续写保存失败：未取得作品互斥锁，请稍后重试"}
    try:
        new_content = state["existing_content"] + "\n\n" + state["continued_text"]
        await _save_chapter_content(state, chapter, new_content, is_regenerate=True)
        return {"total_word_count": len(new_content)}
    finally:
        release_novel_lock(novel_unique_id, lock_token)


async def node_refresh_memory(state: dict) -> dict:
    return {}


# ============================================================
# 条件路由
# ============================================================

def _route_on_error(state: dict) -> str:
    """通用条件路由：节点写入 error → 直接结束（失败出口显式化）"""
    return "error" if state.get("error") else "ok"


def _route_after_content_check(state: dict) -> str:
    if state.get("error"):
        return "error"
    # 幻觉超标 → 定向改写一轮 → 回到 content_check 复检（最多 1 轮）
    if _needs_rewrite(state):
        return "rewrite"
    return "preview" if state.get("mode") == "regenerate" else "save"


# ============================================================
# 图构建
# ============================================================

def build_chapter_gen_graph():
    """构建 generate / regenerate 共用子图"""
    builder = StateGraph(ChapterGenState)
    builder.add_node("repair_load", node_repair_load)
    builder.add_node("assign", node_assign)
    builder.add_node("retrieve_memory", node_retrieve_memory)
    builder.add_node("prev_ending", node_prev_ending)
    builder.add_node("build_prompt", node_build_prompt)
    builder.add_node("call_llm", node_call_llm)
    builder.add_node("postprocess", node_postprocess)
    builder.add_node("content_check", node_content_check)
    builder.add_node("rewrite", node_rewrite)
    builder.add_node("save", node_save)

    builder.add_edge(START, "repair_load")
    builder.add_conditional_edges("repair_load", _route_on_error, {"ok": "assign", "error": END})
    # assign 可能返回 error（章节不存在/章号解析失败）→ 直接结束
    builder.add_conditional_edges("assign", _route_on_error, {"ok": "retrieve_memory", "error": END})
    builder.add_edge("retrieve_memory", "prev_ending")
    builder.add_conditional_edges("prev_ending", _route_on_error, {"ok": "build_prompt", "error": END})
    builder.add_edge("build_prompt", "call_llm")
    builder.add_conditional_edges("call_llm", _route_on_error, {"ok": "postprocess", "error": END})
    builder.add_conditional_edges("postprocess", _route_on_error, {"ok": "content_check", "error": END})
    builder.add_conditional_edges(
        "content_check", _route_after_content_check,
        {"save": "save", "preview": END, "error": END, "rewrite": "rewrite"})
    # 改写后回到 content_check 复检（rewrite_count 上限保证回环终止）
    builder.add_edge("rewrite", "content_check")
    builder.add_edge("save", END)
    return builder.compile()


def build_continue_graph():
    """构建 continue 专用子图"""
    builder = StateGraph(ChapterGenState)
    builder.add_node("load_existing", node_load_existing)
    builder.add_node("call_continue_api", node_call_continue_api)
    builder.add_node("content_check", node_content_check)
    builder.add_node("append_save", node_append_save)
    builder.add_node("refresh_memory", node_refresh_memory)

    builder.add_edge(START, "load_existing")
    # load_existing 可能返回 error（章节不存在）→ 直接结束
    builder.add_conditional_edges("load_existing", _route_on_error, {"ok": "call_continue_api", "error": END})
    builder.add_conditional_edges("call_continue_api", _route_on_error, {"ok": "content_check", "error": END})
    builder.add_conditional_edges("content_check", _route_on_error, {"ok": "append_save", "error": END})
    builder.add_conditional_edges("append_save", _route_on_error, {"ok": "refresh_memory", "error": END})
    builder.add_edge("refresh_memory", END)
    return builder.compile()


_chapter_graph = None
_continue_graph = None


def get_chapter_graph():
    """复用已编译图（幂等构建）"""
    global _chapter_graph
    if _chapter_graph is None:
        _chapter_graph = build_chapter_gen_graph()
    return _chapter_graph


def get_continue_graph():
    """复用已编译图（幂等构建）"""
    global _continue_graph
    if _continue_graph is None:
        _continue_graph = build_continue_graph()
    return _continue_graph


async def run_chapter_gen(state: dict) -> dict:
    """统一入口：按 mode 选择子图执行，返回 success/fail 结构（与现有 service 方法一致）"""
    from app.utils.response import success, fail
    import time

    mode = state.get("mode", "new")
    t_start = time.time()
    try:
        graph = get_continue_graph() if mode == "continue" else get_chapter_graph()
        result = await graph.ainvoke(state)
    except Exception as e:
        import logging
        logging.getLogger("chapter_gen_graph").exception("章节生成图执行异常")
        return fail(f"章节生成失败: {str(e)}", code=500)

    elapsed = time.time() - t_start
    from app.utils.logger import system_logger
    system_logger.info(
        f"[章节生成耗时] mode={mode} | 耗时={elapsed:.1f}秒 | "
        f"字数={result.get('actual_word_count', 0)} | "
        f"成功={not result.get('error')}"
    )

    check_result = {
        "fact_check_result": result.get("fact_check_result", "UNKNOWN"),
        "hallucinations": result.get("hallucinations", []),
        "fact_check_warnings": result.get("fact_check_warnings", []),
        "review_skill": result.get("review_skill"),
        "richness": result.get("richness", {}),
        "rewrite_count": result.get("rewrite_count", 0),
    }
    if result.get("error"):
        response = fail(result["error"], code=500)
        response["数据"] = {
            **check_result,
            "preview_text": result.get("continued_text" if mode == "continue" else "generated_text", ""),
            "summary_scope_result": result.get("summary_scope_result", {}),
            "saved": False,
        }
        return response

    if mode == "continue":
        continued = result.get("continued_text", "")
        total = result.get("total_word_count", 0)
        return success({
            **check_result,
            "chapter_unique_id": state.get("chapter_unique_id"),
            "chapter_name": getattr(result.get("chapter"), "chapter_name", "") or "",
            "continued_text": continued,
            "word_count": total,
            "total_word_count": total,
        }, f"续写成功，新增 {len(continued)} 字")

    return success({
        **check_result,
        "chapter_unique_id": result.get("chapter_unique_id", ""),
        "chapter_name": result.get("title", ""),
        "word_count": result.get("actual_word_count", 0),
        "content": result.get("generated_text", ""),
        "skills": result.get("selected_skills", []),
        "effective_skills": result.get("effective_skills", []),
        "skill_versions": result.get("skill_versions", {}),
    }, f"{result.get('title', '')} 章节内容生成成功")
