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

import os
import uuid
from typing import TypedDict, Any

from langgraph.graph import StateGraph, START, END

__all__ = ["ChapterGenState", "run_chapter_gen", "get_chapter_graph", "get_continue_graph"]


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
    generated_text: str
    clean_stats: dict
    actual_word_count: int
    error: str                       # 失败出口
    # continue 专属
    existing_content: str
    continued_text: str
    total_word_count: int


# ============================================================
# chapter 子图节点（mode=new / regenerate 共用）
# ============================================================

async def node_repair_load(state: dict) -> dict:
    """三源修复 + 加载记忆体（以 txt 为准补 mysql/redis 缺失；Redis 缓存命中则快速返回）

    regenerate 模式先查章获得 novel_unique_id（原方法在查章后加载记忆），
    并把 chapter 写入 state 供 node_assign 复用（避免二次查询）。
    """
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
    return {
        "counts": counts, "next_num": next_num, "fill_mode": fill_mode,
        "fill_row": fill_row, "title": title,
        "summary": state.get("chapter_summary") or "",
    }


async def node_retrieve_memory(state: dict) -> dict:
    """按需检索对应章节的记忆（≤15000 字符注入上限）"""
    from app.service.chapter_gen_service import ChapterGenService
    cur = state.get("cur_num") or state.get("next_num")
    memory_body = ChapterGenService.retrieve_memory(
        state.get("memory_body") or "", state.get("summary") or "",
        current_chapter_num=cur, max_chars=15000)
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


async def node_build_prompt(state: dict) -> dict:
    """作品设定 + 角色卡 + 自动模板适配 + 提示词组装（提示词工程内容不变）"""
    from app.service.chapter_service import ChapterService
    from app.service.chapter_gen_service import ChapterGenService
    settings = ChapterService._get_novel_settings(state["novel_unique_id"])
    character_cards = ChapterService._load_character_cards(state["db"], state["novel_unique_id"])
    template = state.get("chapter_template") or ""
    if not template:
        template = ChapterService._resolve_default_template(state["db"], state["novel_unique_id"])
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
    )
    return {"settings": settings, "character_cards": character_cards, "prompt": prompt}


async def node_call_llm(state: dict) -> dict:
    """调用 DeepSeek 生成正文（只调用一次，不重试不扩写）

    统一传 summary/genre：场景指南按本章概要命中注入（生成路径原为漏传，图化时对齐 regenerate）
    """
    from app.config import gen_max_tokens_multiplier, gen_max_tokens_min
    from app.service.chapter_service import ChapterService
    word_count = state.get("word_count", 2000)
    max_tokens = max(int(word_count * gen_max_tokens_multiplier()), gen_max_tokens_min())
    genre = ChapterService._get_novel_genre(state["novel_unique_id"])
    generated_text, err = await ChapterService._call_generation_api(
        state["prompt"], max_tokens, summary=state.get("summary", ""), genre=genre)
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
    return {"generated_text": cleaned, "clean_stats": stats, "actual_word_count": len(cleaned)}


async def node_save(state: dict) -> dict:
    """保存落盘

    - new：填充概要草稿 / 覆盖旧正文草稿 / 新建草稿 + 写 TXT + 概要写缓存 + 清草稿缓存
    - regenerate：覆盖 TXT + 更新 MySQL 字数（不执行生成后增量记忆提取）
    """
    from app.dao.chapter_dao import ChapterDAO
    from app.models.chapter import Chapter as ChapterModel
    from app.service.chapter_service import NOVEL_DATA_PATH, ChapterService

    mode = state.get("mode")
    novel_unique_id = state["novel_unique_id"]
    generated_text = state["generated_text"]
    actual_word_count = state.get("actual_word_count") or len(generated_text)
    novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
    os.makedirs(novel_dir, exist_ok=True)

    if mode == "regenerate":
        chapter = state["chapter"]
        chapter_file = ChapterService._get_chapter_txt_path(
            novel_unique_id, chapter.chapter_name, state["chapter_unique_id"])
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(generated_text)
        ChapterDAO.update(state["db"], chapter, word_count=actual_word_count)
        return {"chapter_unique_id": state["chapter_unique_id"], "actual_word_count": actual_word_count}

    # ---- mode == "new" ----
    fill_row = state.get("fill_row")
    if fill_row is not None:
        # 填充概要草稿 / 覆盖旧正文草稿：沿用原 chapter_unique_id（TXT 文件名随之稳定）
        chapter_unique_id = fill_row.chapter_unique_id
        old_name = fill_row.chapter_name
        title = state["title"]
        fill_row.chapter_name = title
        fill_row.word_count = actual_word_count
        state["db"].commit()
        old_file = ChapterService._get_chapter_txt_path(novel_unique_id, old_name, chapter_unique_id)
        new_file = ChapterService._get_chapter_txt_path(novel_unique_id, title, chapter_unique_id)
        if old_name and old_file != new_file and os.path.exists(old_file):
            try:
                os.remove(old_file)
            except Exception:
                pass
    else:
        chapter_unique_id = uuid.uuid4().hex
        new_chapter = ChapterModel(
            novel_unique_id=novel_unique_id,
            user_id=state.get("user_id"),
            chapter_unique_id=chapter_unique_id,
            chapter_name=state["title"],
            chapter_number=state["next_num"],
            chapter_summary="",  # 概要不落库：留在 Redis 缓存，发布成功后自动转入 MySQL
            word_count=actual_word_count,
            is_published=0,
            created_by=state.get("created_by", ""),
        )
        state["db"].add(new_chapter)
        state["db"].commit()
        state["db"].refresh(new_chapter)

    chapter_file = ChapterService._get_chapter_txt_path(
        novel_unique_id, state["title"], chapter_unique_id)
    with open(chapter_file, "w", encoding="utf-8") as f:
        f.write(generated_text)

    # 概要统一写入 Redis 缓存（发布成功后才落库 MySQL）
    if state.get("summary"):
        try:
            cached = ChapterService._get_outline_cache(novel_unique_id)
            if not any((o.get("chapter_number") or 0) == state["next_num"] for o in cached):
                cached.append({
                    "chapter_name": state["title"],
                    "chapter_number": state["next_num"],
                    "chapter_summary": state["summary"],
                })
                ChapterService._write_outline_cache(novel_unique_id, cached)
        except Exception:
            pass
    # 清除草稿缓存（保持原行为）
    try:
        from app.service.chapter_service import _redis
        r = _redis()
        if r:
            r.delete_pattern(f"chapters:drafts:user:{state.get('user_id')}")
    except Exception:
        pass
    return {"chapter_unique_id": chapter_unique_id, "actual_word_count": actual_word_count}


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
    context_content = existing_content[-2000:] if len(existing_content) > 2000 else existing_content

    # 记忆体：一次加载（只读优先，Redis 缓存命中不触发全量 AI 提取）
    memory_body = await ChapterService._ensure_memory(chapter.novel_unique_id, state["db"])
    cur_num = ChapterService._chapter_num_from_name(chapter.chapter_name)
    memory_body = ChapterService._retrieve_relevant_memory(
        memory_body, chapter.chapter_summary, current_chapter_num=cur_num, max_chars=15000)

    # 角色卡 → 主角人设硬约束块
    character_cards = ChapterService._load_character_cards(state["db"], chapter.novel_unique_id)
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
    return {
        "chapter": chapter,
        "existing_content": existing_content,
        "context_content": context_content,
        "prompt": prompt,
        "cur_num": cur_num,
    }


async def node_call_continue_api(state: dict) -> dict:
    """调用 DeepSeek 续写（system=恒定核心+场景指南，user=续写 prompt+自查清单）→ 程序化清洗"""
    import httpx
    from app.config import deepseek_base_url, deepseek_api_key, deepseek_long_model
    from app.config import gen_max_tokens_multiplier, gen_max_tokens_min
    from app.config import get as cfg
    from app.prompts.chapter_prompts import SELF_CHECK_LIST, build_generate_system_prompt
    from app.service.chapter_service import ChapterService
    from app.service.text_cleaner import clean_generated_text

    chapter = state["chapter"]
    word_count = state.get("word_count", 2500)
    # Mock 模式（压测用，config.yaml ai.mock_generate=true）：不调用真实 DeepSeek
    from app.config import get as cfg
    if cfg("ai.mock_generate", False):
        return {"continued_text": "压测用模拟续写内容，仅用于接口压力测试，不包含真实剧情。" * 200,
                "clean_stats": {}}
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{deepseek_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {deepseek_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": deepseek_long_model(),
                    "messages": [
                        # system 前缀 = 恒定核心 + 按需场景指南（按本章概要推荐）
                        {"role": "system", "content": build_generate_system_prompt(
                            chapter.chapter_summary,
                            ChapterService._get_novel_genre(chapter.novel_unique_id))},
                        # 自查清单保留 user 末尾（近因效应）
                        {"role": "user", "content": state["prompt"] + "\n\n" + SELF_CHECK_LIST},
                    ],
                    "thinking": {"type": "disabled"},
                    "max_tokens": max(int(word_count * gen_max_tokens_multiplier()), gen_max_tokens_min()),
                    "temperature": 0.85,
                    "top_p": 0.92,
                    "frequency_penalty": cfg("ai.generation.frequency_penalty", 0.5),
                    "presence_penalty": cfg("ai.generation.presence_penalty", 0.5),
                },
            )
        data = response.json()
        if "choices" not in data or not data["choices"]:
            err_msg = str(data.get("error", {}).get("message", "未知错误"))
            return {"error": "AI续写失败: " + err_msg}
        generated_text = data["choices"][0]["message"]["content"]
        if not generated_text or not generated_text.strip():
            return {"error": "AI续写失败: 模型返回空内容，请重试"}
        # 程序化清洗续写片段（去 AI 检测统计特征，引号内对话保护不改写）
        cleaned_text, clean_stats = clean_generated_text(generated_text)
        return {"continued_text": cleaned_text, "clean_stats": clean_stats}
    except httpx.TimeoutException:
        return {"error": "AI接口调用超时，请重试"}
    except Exception as e:
        return {"error": f"AI续写失败: {str(e)}"}


async def node_append_save(state: dict) -> dict:
    """续写结果追加到 TXT + 更新 DB 字数 + 清理单章正文缓存"""
    from app.dao.chapter_dao import ChapterDAO
    from app.service.chapter_service import NOVEL_DATA_PATH, ChapterService
    import app.utils.redis_cache as redis_mod

    chapter = state["chapter"]
    new_content = state["existing_content"] + "\n\n" + state["continued_text"]
    novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
    os.makedirs(novel_dir, exist_ok=True)
    chapter_file = ChapterService._get_chapter_txt_path(
        chapter.novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id)
    with open(chapter_file, "w", encoding="utf-8") as f:
        f.write(new_content)
    ChapterDAO.update(state["db"], chapter, word_count=len(new_content))

    rr = redis_mod.redis_client
    if rr:
        try:
            rr.delete(f"chapter:content:{chapter.chapter_unique_id}")
            rr.delete_pattern(f"chapters:novel:{chapter.novel_unique_id}:*")
        except Exception:
            pass
    return {"total_word_count": len(new_content)}


async def node_refresh_memory(state: dict) -> dict:
    """续写后记忆增量更新（唯一执行生成后记忆更新的路径）"""
    from app.service.chapter_service import ChapterService
    chapter = state["chapter"]
    new_content = state["existing_content"] + "\n\n" + state["continued_text"]
    await ChapterService._refresh_memory_after_generate(
        chapter.novel_unique_id, state["db"], new_content,
        chapter.chapter_name, chapter.chapter_summary or "")
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
    builder.add_node("save", node_save)

    builder.add_edge(START, "repair_load")
    builder.add_edge("repair_load", "assign")
    # assign 可能返回 error（章节不存在/章号解析失败）→ 直接结束
    builder.add_conditional_edges("assign", _route_on_error, {"ok": "retrieve_memory", "error": END})
    builder.add_edge("retrieve_memory", "prev_ending")
    builder.add_edge("prev_ending", "build_prompt")
    builder.add_edge("build_prompt", "call_llm")
    builder.add_conditional_edges("call_llm", _route_on_error, {"ok": "postprocess", "error": END})
    builder.add_edge("postprocess", "save")
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

    mode = state.get("mode", "new")
    try:
        graph = get_continue_graph() if mode == "continue" else get_chapter_graph()
        result = await graph.ainvoke(state)
    except Exception as e:
        import logging
        logging.getLogger("chapter_gen_graph").exception("章节生成图执行异常")
        return fail(f"章节生成失败: {str(e)}", code=500)

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
    }, f"{result.get('title', '')} 章节内容生成成功")
