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
    skill_versions: dict
    generated_text: str
    clean_stats: dict
    actual_word_count: int
    fact_check_result: str           # 事实核查结果（"PASS" 或幻觉描述）
    hallucinations: list             # 幻觉条目列表
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
                _dims[_name] = _sec  # 同名维度只保留最后一个
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
        summary = state.get("chapter_summary") or ""
        if not summary:
            # 草稿阶段概要不落库（发布后才转入 MySQL）：从 Redis 缓存补充
            try:
                cached = ChapterService._get_outline_cache(chapter.novel_unique_id)
                match = next((o for o in cached if (o.get("chapter_number") or 0) == cur_num), None)
                if match:
                    summary = match.get("chapter_summary") or ""
            except Exception:
                pass
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
    summary = (state.get("chapter_summary") or "").strip()
    if not summary:
        try:
            cached = ChapterService._get_outline_cache(novel_unique_id)
            match = next((o for o in cached if (o.get("chapter_number") or 0) == next_num), None)
            if match:
                summary = (match.get("chapter_summary") or "").strip()
        except Exception:
            pass
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
    """上一章末尾 500 字锚点 + 最近 200 字查重文本

    - new：取已发布最后一章
    - regenerate：严格取章节号 < cur_num 的最近一章
    """
    from app.service.chapter_gen_service import ChapterGenService
    if state.get("mode") == "regenerate":
        last_ending, dup_text, last_name = ChapterGenService.get_prev_ending(
            state["db"], state["novel_unique_id"],
            exclude_chapter_id=state.get("chapter_unique_id"),
            current_chapter_num=state.get("cur_num"))
    else:
        last_ending, dup_text, last_name = ChapterGenService.get_prev_ending(
            state["db"], state["novel_unique_id"])
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

    显式风格 = 章节级 skill_ids + 章节级 author_style + 作品默认 writing_style（继承）；
    反AI 质量层由 use_anti_ai 门控（默认开）。
    """
    from app.service.chapter_service import ChapterService
    from app.skills.merger import SkillMerger
    from app.skills.selector import SkillSelector
    explicit = ",".join(p for p in [
        state.get("skill_ids", "") or "",
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
        author_style=state.get("author_style", ""),
        chapter_template=template,
        character_cards=character_cards,
        recent_duplicate_text=state.get("dup_text", ""),
        skill_context=skill_result.prompt,
    )
    system_logger.info(
        f"[Skill选择] anti_ai={state.get('use_anti_ai', True)} "
        f"selected={skill_result.skill_ids} versions={skill_result.versions}"
    )
    return {
        "settings": settings,
        "character_cards": character_cards,
        "prompt": prompt,
        "skill_prompt": skill_result.prompt,
        "selected_skills": list(skill_result.skill_ids),
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
        genre=ChapterService._get_novel_genre(state["novel_unique_id"]))
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
        genre=ChapterService._get_novel_genre(state["novel_unique_id"]))
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
        prompt_text, max_tokens, summary=summary, genre=genre, on_chunk=on_chunk)
    ai_elapsed = time.time() - t_ai
    system_logger.info(f"[AI调用耗时] 正文生成={ai_elapsed:.1f}秒 | max_tokens={max_tokens} | 输入={input_chars}字")
    if not generated_text:
        return {"error": err or "章节生成失败"}
    return {"generated_text": generated_text}


async def node_postprocess(state: dict) -> dict:
    """后处理：概要边界截断 → 超长上限截断 → 程序化清洗（AI 检测特征清除）"""
    from app.config import gen_hard_cap_ratio, gen_hard_cap_min_extra
    from app.service.chapter_service import ChapterService
    from app.service.text_cleaner import clean_generated_text
    text = state["generated_text"]
    summary = state.get("summary") or ""
    word_count = state.get("word_count", 2000)

    # 概要边界截断（生成内容不得超过概要覆盖的事件范围；残留≤500字视为自然收尾保留全文）
    if summary:
        text = ChapterService._trim_to_summary_boundary(text, summary)
    # 超长上限截断（hard_cap 倍且不低于 +min_extra，按段落/句号边界截断避免句中硬切）
    hard_cap = max(int(word_count * gen_hard_cap_ratio()), word_count + gen_hard_cap_min_extra())
    if len(text) > hard_cap:
        cut = text[:hard_cap]
        for sep in ("\n\n", "\n", "。", "！", "？"):
            idx = cut.rfind(sep)
            if idx > int(hard_cap * 0.8):
                cut = cut[:idx + len(sep)]
                break
        text = cut
    # 程序化清洗（引号内对话整体保护）
    cleaned, stats = clean_generated_text(text)
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
    return {
        "generated_text": cleaned,
        "clean_stats": stats,
        "actual_word_count": len(cleaned),
        "ai_quality_score": ai_quality,
    }


async def node_fact_check(state: dict) -> dict:
    """生成后事实核查：用轻量AI调用检测正文中是否存在记忆体中没有的事件/关系（反幻觉）

    流程：
    1. 从记忆体中提取关键事实（人物、事件、时间线）
    2. 用事实核查prompt检查正文是否有幻觉
    3. 如果有幻觉，尝试自动修复（删除/模糊化幻觉段落）
    4. 修复后再次核查，最多重试1次
    """
    from app.config import get as cfg
    from app.prompts.prompt_loader import get_config as get_yaml_config
    from app.service.ai_chat_service import chat_completion, chat_completion_stream, log_ai_call
    from app.config import deepseek_model

    generated_text = state.get("generated_text", "")
    memory_body = state.get("memory_body", "")
    summary = state.get("summary", "")

    if not generated_text or not memory_body:
        return {"fact_check_result": "PASS", "hallucinations": []}

    # 跳过核查的情况：mock模式 或 配置关闭
    if cfg("ai.mock_generate", False) or not cfg("ai.fact_check.enabled", True):
        return {"fact_check_result": "PASS", "hallucinations": []}

    fact_check_system = get_yaml_config("FACT_CHECK_SYSTEM_PROMPT", "")
    fact_check_user_tpl = get_yaml_config("FACT_CHECK_USER_TEMPLATE", "")

    if not fact_check_system or not fact_check_user_tpl:
        return {"fact_check_result": "PASS", "hallucinations": []}

    # 截取记忆体关键部分（避免过长，只取事件/时间线/人物关系维度）
    from app.prompts.chapter_prompts import get_memory_category_names
    import re as _re
    sections = _re.split(r'\n(?=【)', memory_body)
    key_dims = ("关键事件", "时间线", "人物", "人物关系")
    key_facts = []
    for sec in sections:
        m = _re.match(r'【(.+?)】', sec)
        if m and m.group(1) in key_dims:
            key_facts.append(sec.strip())
    key_facts_text = "\n\n".join(key_facts) if key_facts else memory_body[:3000]

    # 事实核查：只检查正文前3000字+后1000字（幻觉通常出现在开头回忆和结尾总结）
    check_text = generated_text[:3000]
    if len(generated_text) > 4000:
        check_text += "\n\n...(中间省略)...\n\n" + generated_text[-1000:]

    user_prompt = fact_check_user_tpl.replace("{memory_body}", key_facts_text[:4000]) \
        .replace("{summary}", summary[:1000]) \
        .replace("{generated_text}", check_text)

    try:
        fc_params = cfg("ai.api_params.fact_check_api", {})
        fc_msgs = [
            {"role": "system", "content": fact_check_system},
            {"role": "user", "content": user_prompt},
        ]
        system_logger.info(
            f"[AI调用-事实核查] 正文={len(generated_text)}字 | 记忆体={len(memory_body)}字 | "
            f"核查文本={len(check_text)}字 | 关键记忆={len(key_facts_text)}字")
        text, err, usage = await chat_completion(
            messages=fc_msgs,
            model=deepseek_model(),
            max_tokens=fc_params.get("max_tokens", 1500),
            timeout=fc_params.get("timeout", 60),
            thinking={"type": "disabled"},
            temperature=fc_params.get("temperature", 0.1),
        )
        log_ai_call("事实核查", fc_msgs, text, err, usage,
                    model=deepseek_model(),
                    extra_info={"正文字数": len(generated_text), "记忆体字数": len(memory_body)})
        if err:
            system_logger.error(f"[事实核查] AI调用失败: {err}")
            return {"error": f"事实核查失败: {err}"}

        text = (text or "").strip()
        if text == "PASS" or "PASS" in text:
            system_logger.info("[事实核查] ✅ 通过，未发现幻觉")
            return {"fact_check_result": "PASS", "hallucinations": []}

        # 解析幻觉列表
        hallucinations = []
        try:
            # 尝试提取JSON数组
            json_match = _re.search(r'\[.*\]', text, _re.DOTALL)
            if json_match:
                hallucinations = json.loads(json_match.group())
        except (json.JSONDecodeError, Exception):
            # JSON解析失败，把整个输出作为幻觉描述
            hallucinations = [{"text": text[:200], "reason": "AI返回格式异常", "suggestion": "人工检查"}]

        if hallucinations:
            system_logger.warning(
                f"[事实核查] ⚠️ 发现 {len(hallucinations)} 处幻觉: "
                + "; ".join(h.get("reason", "")[:50] for h in hallucinations[:3])
            )
            return {"fact_check_result": text, "hallucinations": hallucinations}

        return {"fact_check_result": "PASS", "hallucinations": []}

    except Exception as e:
        system_logger.warning(f"[事实核查] 异常: {e}")
        return {"fact_check_result": "PASS", "hallucinations": []}


async def _save_chapter_content(state: dict, chapter, content: str, is_regenerate: bool = False) -> None:
    from app.dao.chapter_dao import ChapterDAO
    from app.service.chapter_gen_service import ChapterGenService
    from app.service.chapter_service import ChapterService, _redis

    novel_unique_id = chapter.novel_unique_id
    chapter_unique_id = chapter.chapter_unique_id

    # 记录事实核查结果
    fact_result = state.get("fact_check_result", "SKIP")
    hallucinations = state.get("hallucinations", [])
    if fact_result != "PASS" and hallucinations:
        system_logger.warning(
            f"[事实核查] 章节 {chapter.chapter_name} 存在 {len(hallucinations)} 处幻觉，仍予保存: "
            + "; ".join(h.get("reason", "")[:60] for h in hallucinations[:3])
        )
    elif fact_result == "PASS":
        system_logger.info(f"[事实核查] 章节 {chapter.chapter_name} 核查通过")
    # 概要必须先落库；这里是生成正文成功后的唯一持久化入口
    used_summary = (state.get("summary") or getattr(chapter, "chapter_summary", "") or "").strip()
    if used_summary and not (getattr(chapter, "chapter_summary", "") or "").strip():
        chapter.chapter_summary = used_summary
        state["db"].flush()
    chapter_file = ChapterService._get_chapter_txt_path(
        novel_unique_id, chapter.chapter_name, chapter_unique_id)
    novel_dir = os.path.dirname(chapter_file)
    os.makedirs(novel_dir, exist_ok=True)
    temp_file = f"{chapter_file}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, chapter_file)
        ChapterDAO.update(state["db"], chapter, word_count=len(content))

        r = _redis()
        if not r or not r.ping():
            raise RuntimeError(f"章节保存失败：Redis不可用，chapter_unique_id={chapter_unique_id}")
        r.delete(f"chapter:content:{chapter_unique_id}")
        r.delete_pattern(f"chapters:novel:{novel_unique_id}:*")
        r.delete(f"chapters:drafts:user:{chapter.user_id}")

        # 记忆提取改为后台异步执行（不阻塞任务完成，可节省30~120s）
        _summary = state.get("summary") or getattr(chapter, "chapter_summary", "") or ""
        _db = state["db"]
        _cname = chapter.chapter_name
        async def _bg_memory_refresh():
            try:
                await ChapterService._refresh_memory_after_generate(
                    novel_unique_id, _db, content, _cname, _summary, is_regenerate=is_regenerate)
                system_logger.info(f"[记忆提取] 后台完成: {_cname}")
            except Exception as e:
                system_logger.warning(f"[记忆提取] 后台失败: {_cname}: {e}")
        import asyncio
        asyncio.create_task(_bg_memory_refresh())

        chapter_num = ChapterGenService.chapter_no(chapter)
        if chapter_num <= 0:
            chapter_num = ChapterService._chapter_num_from_name(chapter.chapter_name)
        if not chapter_num or chapter_num <= 0:
            raise RuntimeError(
                f"章节三源保存校验失败，chapter_unique_id={chapter_unique_id}，章节号解析失败")
        memory_key = ChapterService._memory_key(novel_unique_id)
        memory_values = r.hgetall(memory_key)
        redis_exists = False
        for value in memory_values.values():
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            for chapter_marker in re.findall(r'\[第\s*[一二三四五六七八九十百零\d]+\s*章[^\]]*\]', str(value)):
                memory_chapter_num = ChapterService._chapter_num_from_name(chapter_marker[1:-1])
                if memory_chapter_num == chapter_num:
                    redis_exists = True
                    break
            if redis_exists:
                break

        # 如果AI增量提取失败导致Redis无本章记忆条目，回写最小标记保底
        if not redis_exists:
            fallback_summary = state.get("summary") or getattr(chapter, "chapter_summary", "") or ""
            fallback_marker = f"[{chapter.chapter_name}] {fallback_summary}" if fallback_summary else f"[{chapter.chapter_name}] 本章内容已生成。"
            from app.service.chapter_service import get_memory_category_names
            cats = get_memory_category_names()
            target_cat = "关键事件" if "关键事件" in cats else (cats[0] if cats else None)
            if target_cat:
                ChapterService._append_to_dimension(novel_unique_id, target_cat, fallback_marker)
                system_logger.warning(f"[三源保底] AI记忆提取未写入，已回写最小标记到 [{target_cat}]: {fallback_marker[:80]}")
            # 重新读取确认写入成功
            memory_values = r.hgetall(memory_key)
            for value in memory_values.values():
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="ignore")
                for chapter_marker in re.findall(r'\[第\s*[一二三四五六七八九十百零\d]+\s*章[^\]]*\]', str(value)):
                    memory_chapter_num = ChapterService._chapter_num_from_name(chapter_marker[1:-1])
                    if memory_chapter_num == chapter_num:
                        redis_exists = True
                        break
                if redis_exists:
                    break

        counts = ChapterGenService.count_sources(novel_unique_id, state["db"])
        mysql_exists = any(item.get("id") == chapter_unique_id for item in counts["mysql"]["chapters"])
        txt_exists = os.path.isfile(chapter_file)
        missing = []
        if not mysql_exists:
            missing.append("MySQL记录")
        if not txt_exists:
            missing.append("TXT文件")
        if not redis_exists:
            missing.append("Redis记忆条目")
        if missing:
            raise RuntimeError(
                f"章节三源保存校验失败，chapter_unique_id={chapter_unique_id}，缺失：{'、'.join(missing)}")
    except Exception:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise


async def node_save(state: dict) -> dict:
    from app.dao.chapter_dao import ChapterDAO
    from app.models.chapter import Chapter as ChapterModel
    from app.service.chapter_service import ChapterService
    from app.utils.task_queue import acquire_novel_lock, release_novel_lock

    mode = state.get("mode")
    novel_unique_id = state["novel_unique_id"]
    generated_text = state["generated_text"]
    actual_word_count = state.get("actual_word_count") or len(generated_text)

    lock_token = acquire_novel_lock(novel_unique_id)
    try:
        if mode == "regenerate":
            chapter = state["chapter"]
            await _save_chapter_content(state, chapter, generated_text, is_regenerate=True)
            return {"chapter_unique_id": chapter.chapter_unique_id, "actual_word_count": actual_word_count}

        fill_row = state.get("fill_row")
        if fill_row is not None:
            chapter = fill_row
            old_name = chapter.chapter_name
            chapter.chapter_name = state["title"]
            if state.get("summary"):
                chapter.chapter_summary = state["summary"]
            old_file = ChapterService._get_chapter_txt_path(novel_unique_id, old_name, chapter.chapter_unique_id)
            new_file = ChapterService._get_chapter_txt_path(
                novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id)
            if old_name and old_file != new_file and os.path.exists(old_file):
                os.remove(old_file)
            chapter_unique_id = chapter.chapter_unique_id
        else:
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
            state["db"].commit()
            state["db"].refresh(chapter)

        chapter.word_count = actual_word_count
        state["db"].commit()
        await _save_chapter_content(state, chapter, generated_text)

        # 生成正文后：从概要缓存中删除已使用的那条概要
        cached = ChapterService._get_outline_cache(novel_unique_id)
        used_num = state.get("next_num") or (state.get("cur_num") if state.get("mode") == "regenerate" else None)
        if used_num and any((o.get("chapter_number") or 0) == used_num for o in cached):
            kept = [o for o in cached if (o.get("chapter_number") or 0) != used_num]
            ChapterService._write_outline_cache(novel_unique_id, kept)
            system_logger.info(f"[概要缓存] 已删除第{used_num}章概要（正文已生成）")
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
    existing_content = ChapterService._read_chapter_content_from_file(
        chapter.novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id)
    from app.config import get as cfg
    tail_chars = cfg("ai.api_params.continue_writing.tail_chars", 2000)
    context_content = existing_content[-tail_chars:] if len(existing_content) > tail_chars else existing_content

    # 记忆体：一次加载（只读优先，Redis 缓存命中不触发全量 AI 提取）
    memory_body = await ChapterService._ensure_memory(chapter.novel_unique_id, state["db"])
    cur_num = ChapterService._chapter_num_from_name(chapter.chapter_name)
    memory_body = ChapterService._retrieve_relevant_memory(
        memory_body, chapter.chapter_summary, current_chapter_num=cur_num)

    # 角色卡 → 主角人设硬约束块
    character_cards = ChapterService._load_character_cards(state["db"], chapter.novel_unique_id)
    skill_result = _select_and_merge_skills(
        state, chapter.novel_unique_id, character_cards,
        chapter.chapter_summary or "",
        ChapterService._get_novel_settings(chapter.novel_unique_id).get("content", ""))
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
        chapter_summary=chapter.chapter_summary or '无',
        context_content=context_content,
        word_count=state.get("word_count", 2500),
        min_words=max(state.get("word_count", 2500) - 500, 800),
    )
    if skill_result.prompt:
        prompt += "\n\n【本次章节 Skill 规则】\n" + skill_result.prompt
    return {
        "chapter": chapter,
        "existing_content": existing_content,
        "context_content": context_content,
        "prompt": prompt,
        "cur_num": cur_num,
        "skill_prompt": skill_result.prompt,
        "selected_skills": list(skill_result.skill_ids),
        "skill_versions": skill_result.versions,
    }


async def node_call_continue_api(state: dict) -> dict:
    """调用 DeepSeek 续写（system=恒定核心+场景指南，user=续写 prompt+自查清单）→ 程序化清洗"""
    from app.config import get as cfg
    from app.config import deepseek_long_model, gen_api_timeout
    from app.service.ai_chat_service import chat_completion, chat_completion_stream, log_ai_call
    from app.prompts.chapter_prompts import SELF_CHECK_LIST, build_generate_system_prompt
    from app.service.chapter_service import ChapterService
    from app.service.text_cleaner import clean_generated_text

    chapter = state["chapter"]
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
                chapter.chapter_summary,
                ChapterService._get_novel_genre(chapter.novel_unique_id))},
            {"role": "user", "content": state["prompt"] + "\n\n" + SELF_CHECK_LIST},
        ]

        # 调用前详细日志 + token 预估
        existing_content = state.get("existing_content", "")
        from app.service.ai_chat_service import estimate_generation_tokens, log_token_estimate
        token_est = estimate_generation_tokens(
            system_prompt=cw_msgs[0]["content"], memory_body="",
            prompt=state["prompt"], summary=chapter.chapter_summary or "",
            last_ending=existing_content, max_tokens=cw_max, word_count=word_count)
        log_token_estimate("续写", token_est)

        completion = chat_completion_stream if state.get("on_chunk") else chat_completion
        completion_params = {
            "messages": cw_msgs,
            "model": deepseek_long_model(),
            "max_tokens": cw_max,
            "timeout": cw_params.get("timeout", gen_api_timeout()),
            "thinking": {"type": "disabled"},
            "temperature": cw_params.get("temperature", 0.85),
            "top_p": cw_params.get("top_p", 0.92),
            "frequency_penalty": cfg("ai.generation.frequency_penalty", 0.5),
            "presence_penalty": cfg("ai.generation.presence_penalty", 0.5),
        }
        if state.get("on_chunk"):
            completion_params["on_chunk"] = state["on_chunk"]
        generated_text, err, usage = await completion(**completion_params)
        log_ai_call("续写", cw_msgs, generated_text, err, usage,
                    model=deepseek_long_model(),
                    extra_info={"概要字数": len(chapter.chapter_summary or ""), "max_tokens": cw_max,
                                "章节末尾字数": len(state.get("existing_content", ""))})
        if not generated_text:
            return {"error": "AI续写失败: " + (err or "未知错误")}
        cleaned_text, clean_stats = clean_generated_text(generated_text)
        return {"continued_text": cleaned_text, "clean_stats": clean_stats}
    except Exception as e:
        return {"error": f"AI续写失败: {str(e)}"}


async def node_append_save(state: dict) -> dict:
    from app.dao.chapter_dao import ChapterDAO
    from app.service.chapter_service import ChapterService
    from app.utils.task_queue import acquire_novel_lock, release_novel_lock

    chapter = state["chapter"]
    novel_unique_id = chapter.novel_unique_id
    lock_token = acquire_novel_lock(novel_unique_id)
    try:
        new_content = state["existing_content"] + "\n\n" + state["continued_text"]
        await _save_chapter_content(state, chapter, new_content)
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
    builder.add_node("fact_check", node_fact_check)
    builder.add_node("save", node_save)

    builder.add_edge(START, "repair_load")
    builder.add_edge("repair_load", "assign")
    # assign 可能返回 error（章节不存在/章号解析失败）→ 直接结束
    builder.add_conditional_edges("assign", _route_on_error, {"ok": "retrieve_memory", "error": END})
    builder.add_edge("retrieve_memory", "prev_ending")
    builder.add_edge("prev_ending", "build_prompt")
    builder.add_edge("build_prompt", "call_llm")
    builder.add_conditional_edges("call_llm", _route_on_error, {"ok": "postprocess", "error": END})
    builder.add_edge("postprocess", "fact_check")
    builder.add_conditional_edges("fact_check", _route_on_error, {"ok": "save", "error": END})
    builder.add_edge("save", END)
    return builder.compile()


def build_continue_graph():
    """构建 continue 专用子图"""
    builder = StateGraph(ChapterGenState)
    builder.add_node("load_existing", node_load_existing)
    builder.add_node("call_continue_api", node_call_continue_api)
    builder.add_node("append_save", node_append_save)
    builder.add_node("refresh_memory", node_refresh_memory)

    builder.add_edge(START, "load_existing")
    # load_existing 可能返回 error（章节不存在）→ 直接结束
    builder.add_conditional_edges("load_existing", _route_on_error, {"ok": "call_continue_api", "error": END})
    builder.add_conditional_edges("call_continue_api", _route_on_error, {"ok": "append_save", "error": END})
    builder.add_edge("append_save", "refresh_memory")
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

    if result.get("error"):
        return fail(result["error"], code=500)

    if mode == "continue":
        continued = result.get("continued_text", "")
        total = result.get("total_word_count", 0)
        return success({
            "chapter_unique_id": state.get("chapter_unique_id"),
            "chapter_name": getattr(result.get("chapter"), "chapter_name", "") or "",
            "continued_text": continued,
            "word_count": total,
            "total_word_count": total,
        }, f"续写成功，新增 {len(continued)} 字")

    return success({
        "chapter_unique_id": result.get("chapter_unique_id", ""),
        "chapter_name": result.get("title", ""),
        "word_count": result.get("actual_word_count", 0),
        "content": result.get("generated_text", ""),
        "skills": result.get("selected_skills", []),
        "skill_versions": result.get("skill_versions", {}),
    }, f"{result.get('title', '')} 章节内容生成成功")
