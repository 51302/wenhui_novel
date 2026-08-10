import json
import re
import uuid
import os
import httpx
from sqlalchemy.orm import Session
from app.dao.novel_dao import NovelDAO
from app.dao.chapter_dao import ChapterDAO
from app.utils.response import success, fail
import app.utils.redis_cache as redis_mod
from app.service.es_service import es_service
from app.config import deepseek_api_key, deepseek_base_url, deepseek_model, deepseek_long_model
from app.config import gen_max_tokens_multiplier, gen_max_tokens_min, gen_hard_cap_ratio, gen_hard_cap_min_extra
from app.utils.logger import system_logger
from app.utils.task_queue import run_async
from app.service.chapter_gen_service import ChapterGenService
from app.service.text_cleaner import clean_generated_text, check_ai_features, collect_feature_sentences
from app.prompts.chapter_prompts import (
    LIGHT_EXTRACT_PROMPT, FULL_EXTRACT_PROMPT,
    MEMORY_DIMENSION_DEFS, MEMORY_EXTRACT_PROMPT, MEMORY_INCREMENTAL_PROMPT,
    get_memory_category_names, get_frontend_to_dimension_map,
    match_ai_label_to_dimension, get_dimension_dedup_map,
    HUMAN_EMOTION_GUIDE, COMBAT_WRITING_GUIDE,
    COGNITION_BOUNDARY_GUIDE,
    GENERATE_SYSTEM_PROMPT, EXPANDED_SYSTEM_PROMPT, GENERATE_CREATIVE_DIRECTION,
    GENERATION_FRAMEWORK, SELF_CHECK_LIST,
    OUTLINE_SYSTEM_PROMPT, OUTLINE_USER_PROMPT_TEMPLATE,
)
from app.prompts.screenplay_prompts import (
    SCREENPLAY_SYSTEM_PROMPT, GENERATE_SCREENPLAY_DIRECTION,
)

NOVEL_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "novel_structure_data")
os.makedirs(NOVEL_DATA_PATH, exist_ok=True)


def _redis():
    """获取Redis客户端实例"""
    return redis_mod.redis_client


class ChapterService:

    @staticmethod
    def _get_chapter_txt_path(novel_unique_id: str, chapter_name: str, chapter_unique_id: str) -> str:
        """获取章节 TXT 文件路径"""
        return os.path.join(NOVEL_DATA_PATH, novel_unique_id, f"{chapter_name}_{chapter_unique_id}.txt")

    @staticmethod
    def _read_chapter_content_from_file(novel_unique_id: str, chapter_name: str, chapter_unique_id: str) -> str:
        """从 TXT 文件读取章节正文内容，文件不存在返回空字符串"""
        txt_path = ChapterService._get_chapter_txt_path(novel_unique_id, chapter_name, chapter_unique_id)
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    @staticmethod
    def _get_novel_settings(novel_unique_id: str) -> dict:
        """读取作品设定文件内容 + 数据库中的简介/世界观，合并为完整设定文本

        :param novel_unique_id: 作品唯一ID
        :return: 设定内容字典（含content和path）
        """
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        settings_file = os.path.join(novel_dir, "作品设定.txt")
        file_content = ""
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                file_content = f.read()

        # 从数据库补充简介（description）和世界观（world_setting）——
        # 简介含关键场景承诺（如"暗金色光炸出、灾厄化灰"），必须注入 prompt 让 AI 兑现
        extra_parts = []
        try:
            from app.dao.novel_dao import NovelDAO
            from app.models.base import SessionLocal
            db = SessionLocal()
            try:
                novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
                if novel:
                    desc = (novel.description or "").strip()
                    if desc:
                        extra_parts.append(f"【作品简介 —— 关键场景/台词承诺，正文对应场景必须按此呈现】\n{desc}")
                    ws = (novel.world_setting or "").strip()
                    if ws and ws not in file_content:
                        extra_parts.append(f"【世界观设定】\n{ws}")
            finally:
                db.close()
        except Exception as e:
            system_logger.warning(f"[设定读取] 补充简介/世界观失败: {e}")

        combined = ""
        if extra_parts:
            combined = "\n\n".join(extra_parts) + "\n\n" + file_content
        else:
            combined = file_content

        return {"content": combined, "path": settings_file if file_content else ""}

    @staticmethod
    def _get_novel_genre(novel_unique_id: str) -> str:
        """读取作品题材标签（novel.genre），用于提取 prompt 的 {novel_genre} 占位符。

        :return: 题材字符串（如"仙侠""都市""玄幻"），读取失败返回通用默认值"小说"
        """
        try:
            from app.dao.novel_dao import NovelDAO
            from app.models.base import SessionLocal
            db = SessionLocal()
            try:
                novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
                if novel:
                    genre = (novel.genre or novel.target_reader or "").strip()
                    if genre:
                        return genre
            finally:
                db.close()
        except Exception as e:
            system_logger.warning(f"[题材读取] 获取作品题材失败: {e}")
        return "小说"

    @staticmethod
    def _load_character_cards(db: Session, novel_unique_id: str) -> list:
        """读取作品角色卡（novels.characters JSON），解析失败返回 []

        用于：章节生成 prompt 注入主角人设/配角设定，避免 AI 忘了主角「疯批/怼神」等性格写崩
        """
        try:
            novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
            chars_text = (novel.characters or "") if novel else ""
            if not chars_text:
                return []
            chars = json.loads(chars_text)
            return chars if isinstance(chars, list) else []
        except Exception as e:
            system_logger.warning(f"[角色卡注入] 读取失败: {e}")
            return []

    @staticmethod
    def _resolve_default_template(db: Session, novel_unique_id: str) -> str:
        """生成时未手动选章节模板 → 按作品主角性格自动适配默认模板

        取 novels.characters JSON 中第一个角色（约定为作品主角）的 personality，
        关键词匹配 PERSONALITY_TEMPLATE_MAP（见 chapter_prompts.py）返回模板ID；
        无角色 / 无性格 / 无匹配时返回空字符串（不强制套模板）。
        """
        try:
            chars = ChapterService._load_character_cards(db, novel_unique_id)
            if not chars:
                return ""
            personality = (chars[0].get("personality") or "").strip()
            if not personality:
                return ""
            from app.prompts.chapter_prompts import resolve_personality_template
            return resolve_personality_template(personality)
        except Exception as e:
            system_logger.warning(f"[模板适配] 读取主角性格失败: {e}")
            return ""

    # ==================== 记忆体系统（AI提取关键信息 → Redis Hash 存储） ====================

    @staticmethod
    def _memory_key(novel_unique_id: str) -> str:
        """Redis Hash key: memory:{novel_id}"""
        return f"memory:{novel_unique_id}"

    @staticmethod
    def clear_memory(novel_unique_id: str) -> dict:
        """清空指定作品的全部 Redis 记忆体"""
        r = _redis()
        if not r or not r.ping():
            return fail("Redis 不可用", code=500)
        key = ChapterService._memory_key(novel_unique_id)
        try:
            existed = r.exists(key)
            r.delete(key)
            system_logger.info(f"[记忆体] 已清空 {novel_unique_id} 的记忆体（之前{'存在' if existed else '不存在'}）")
            return success(None, "Redis 记忆体已清除")
        except Exception as e:
            system_logger.error(f"[记忆体] 清空失败: {e}")
            return fail(f"清空失败: {str(e)}", code=500)

    @staticmethod
    @staticmethod
    @staticmethod
    def _ensure_memory_store():
        """检查 Redis 是否可用"""
        r = _redis()
        return r is not None and r.ping()

    # ----------------------------------------------------------------
    #  记忆体存储：按维度拆分存入 Redis记忆体，维度定义统一来自 chapter_prompts
    # ----------------------------------------------------------------

    @staticmethod
    def _load_memory(novel_unique_id: str) -> str:
        """从 Redis Hash 加载所有维度记忆体并合并"""
        r = _redis()
        if not r or not r.ping():
            return ""
        key = ChapterService._memory_key(novel_unique_id)
        all_data = r.hgetall(key)
        if not all_data:
            return ""
        parts = []
        for cat in get_memory_category_names():
            if cat in all_data and all_data[cat]:
                parts.append(f"【{cat}】\n{all_data[cat]}")
        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _trim_memory_body(memory_body: str, max_chars: int = 30000) -> str:
        """记忆体裁剪注入：按维度优先级保留核心设定，压缩历史事件，防止输入超长拖慢生成。
        优先级：作品设定 > 人物 > 组织 > 功法 > 伏笔 > 地点 > 时间线 > 实力 > 物品 > 事件(只留最新部分)
        """
        if not memory_body or len(memory_body) <= max_chars:
            return memory_body
        # 按【维度】切分
        sections = re.split(r'\n(?=【)', memory_body)
        prio = {
            "作品设定": 0, "人物": 1, "组织势力": 2, "组织": 2,
            "功法技能法宝": 3, "功法技能": 3, "伏笔悬念": 4, "伏笔": 4,
            "地点": 5, "时间线": 6, "时间": 6, "实力变化": 7, "关键物品": 8,
        }
        event_text = ""   # 关键事件（章节多时极大，单独压缩保留最新）
        ordered = []
        for sec in sections:
            m = re.match(r'【(.+?)】', sec)
            name = m.group(1) if m else "其他"
            if name in ("关键事件", "章节数"):
                event_text += sec + "\n"
            else:
                ordered.append((prio.get(name, 10), sec))
        ordered.sort(key=lambda x: x[0])
        kept, used = [], 0
        for _, sec in ordered:
            if used + len(sec) <= max_chars:
                kept.append(sec)
                used += len(sec)
            else:
                break
        # 剩余空间补给关键事件的最新部分（最新章节在末尾，事件按章节顺序追加）
        remain = max_chars - used
        if remain > 1500 and event_text:
            kept.append("【关键事件】（仅保留最近部分）\n" + event_text[-remain:])
        result = "\n".join(kept)
        system_logger.info(
            f"[记忆体裁剪] {len(memory_body)} 字符 → {len(result)} 字符"
        )
        return result

    @staticmethod
    def _event_chapter_num(line: str) -> int:
        """从关键事件条目解析所属章节号：
        - [第31章] 1. xxx → 31
        - [第三十一章 名称] 1. xxx → 31（兼容 _pipe_to_natural 增量格式）
        - 无前缀/无法解析 → -1（未知章节，不参与章节筛选）
        """
        m = re.match(r'\[第\s*([\d零一二三四五六七八九十百]+)\s*章', line)
        if not m:
            return -1
        num_str = m.group(1)
        if num_str.isdigit():
            return int(num_str)
        return ChapterService._cn_num_to_int(num_str)

    @staticmethod
    def _chapter_num_from_name(chapter_name: str):
        """从章节名解析章节号（支持阿拉伯/中文数字），失败返回 None"""
        if not chapter_name:
            return None
        m = re.match(r'第\s*([\d零一二三四五六七八九十百]+)\s*章', chapter_name)
        if not m:
            return None
        num_str = m.group(1)
        if num_str.isdigit():
            return int(num_str)
        return ChapterService._cn_num_to_int(num_str)

    @staticmethod
    def _retrieve_relevant_memory(memory_body: str, summary: str, max_chars: int = None,
                                  current_chapter_num: int = None) -> str:
        """按需检索注入：从全量记忆体中检索与本章概要相关的条目注入。
        - 实体命中：从人物/组织/功法维度提取实体名，在概要中命中的实体
          → 章节级整章抽取：定位实体出现过的章节（限当前章节前 10 章窗口，防主角
          高频扩散），该章所有维度条目整章取来；更早章节的关键事件由行级补全兜底
        - 最近连续：关键事件固定带当前章节前 3 章的事件（按章节号筛选，避免重新生成中段
          章节时取到全书末尾；条目无章节号时回退全量末尾 3 行）
        - 核心兜底：命中失败时注入主要人物 top-15 状态 + 时间线
        - 设定常驻：作品设定全量保留
        注：max_chars 默认 None —— 不截断。按需检索已限定为相关实体/最近章节条目，
            注入量可控（远小于历史全量注入）。此前默认 10000 是为避免 prompt > 24k
            字符时空回复概率上升；若实体命中多导致注入超长、空正文回升，可重新收紧。
        """
        if not memory_body:
            return ""
        # 无概要 → 全量；max_chars 非空且记忆体小 → 全量；否则走按需筛选
        # （max_chars=None 表示按需筛选后不截断，绝不是全量注入）
        if not summary or (max_chars is not None and len(memory_body) <= max_chars):
            return memory_body
        sections = re.split(r'\n(?=【)', memory_body)
        dims = {}
        for sec in sections:
            m = re.match(r'【(.+?)】', sec)
            name = m.group(1) if m else "其他"
            lines = [ln.strip() for ln in sec.split("\n")[1:] if ln.strip()]
            dims[name] = lines

        # 1. 实体名提取（行首字段，去掉 [第X章] 前缀）
        entity_names = set()
        for dim in ("人物", "组织势力", "功法技能法宝"):
            for line in dims.get(dim, []):
                name = re.sub(r'^\[第\d+章\]\s*', '', line)
                name = re.split(r'[，,|:：\s]', name, 1)[0].strip()
                name = name.strip('"“”《》')
                if name and 1 < len(name) <= 20:
                    entity_names.add(name)

        # 2. 概要命中实体
        hit = {n for n in entity_names if n and n in (summary or "")}

        # 3. 组装注入
        out, used = [], 0

        def _add(title, lines, truncate=False):
            nonlocal used
            if not lines:
                return
            block = f"【{title}】\n" + "\n".join(lines)
            if max_chars is None or used + len(block) <= max_chars:
                out.append(block)
                used += len(block)
            elif truncate and len(lines) > 1:
                # 放不下且允许截断：从最旧行淘汰，保留最新，直到能放下
                lines = list(lines)
                while lines and (max_chars is None or used + len(f"【{title}】\n" + "\n".join(lines)) > max_chars):
                    lines.pop(0)
                if lines:
                    out.append(f"【{title}】\n" + "\n".join(lines))
                    used += len(f"【{title}】\n" + "\n".join(lines))

        # 3.1 作品设定常驻（体积小、优先级最高）
        _add("作品设定", dims.get("作品设定", []))

        # 3.2 最近3章事件（剧情连续性，强制注入；按当前章节号取前3章）
        events = dims.get("关键事件", [])
        recent_events = []
        if events:
            if current_chapter_num:
                recent_events = [ln for ln in events
                                 if (num := ChapterService._event_chapter_num(ln)) != -1
                                 and current_chapter_num - 3 < num <= current_chapter_num]
            if not recent_events:
                recent_events = events[-3:]
            _add("关键事件(最近3章)", recent_events, truncate=True)

        # 3.3 命中实体：章节级整章抽取（实体所在章节，该章所有维度条目整章取来）
        #     窗口限制：仅取当前章节前 10 章内出现的命中章节——主角/高频实体几乎全书
        #     出现，若不加窗口会扩散成全量注入；更早章节的重要事件由 3.4 行级补全兜底
        #     无章节号前缀的条目（增量提取"本章新增"格式）全量保留，防止漏掉
        if hit:
            hit_chapters = set()
            for ln_list in dims.values():
                for ln in ln_list:
                    if any(n in ln for n in hit):
                        num = ChapterService._event_chapter_num(ln)
                        if num != -1:
                            hit_chapters.add(num)
            if current_chapter_num:
                hit_chapters = {n for n in hit_chapters
                                if current_chapter_num - 10 < n <= current_chapter_num}
            for dim in ("人物", "组织势力", "功法技能法宝", "关键物品", "伏笔悬念", "实力变化", "地点"):
                lines = [ln for ln in dims.get(dim, [])
                         if ChapterService._event_chapter_num(ln) in hit_chapters
                         or ChapterService._event_chapter_num(ln) == -1]
                _add(dim, lines, truncate=True)
        else:
            # 命中失败兜底：主要人物 top-15（按条目长度，保留状态信息多的）
            _add("人物", sorted(dims.get("人物", []), key=len, reverse=True)[:15])

        # 3.4 命中实体的历史事件（补充上下文；排除最近3章已注入的）
        if events and hit:
            recent_set = set(recent_events)
            rel = [ln for ln in events if any(n in ln for n in hit) and ln not in recent_set]
            _add("关键事件(相关章节)", rel, truncate=True)

        # 3.5 兜底：时间线（全局脉络）
        if not hit:
            _add("时间线", dims.get("时间线", []))

        result = "\n".join(out)
        system_logger.info(
            f"[按需检索] 输入{len(memory_body)}字符 → 注入{len(result)}字符，命中{len(hit)}个实体"
        )
        return result

    @staticmethod
    def _save_memory(novel_unique_id: str, memory_text: str):
        """按维度拆分保存记忆体到 Redis Hash（使用统一维度映射）"""
        r = _redis()
        if not r or not r.ping():
            return
        sections = re.split(r'\n(?=【)', memory_text)
        cat_map = {}
        current_cat = "概览"
        for sec in sections:
            m = re.match(r'【(.+?)】\s*\n?(.*)', sec, re.DOTALL)
            if m:
                current_cat = m.group(1).strip()
                content = m.group(2).strip()
                if content and content not in ("无新增", "无"):
                    cat_map[current_cat] = content
            else:
                if current_cat not in cat_map:
                    cat_map[current_cat] = ""
                cat_map[current_cat] += "\n" + sec.strip()

        key = ChapterService._memory_key(novel_unique_id)
        for std_cat in get_memory_category_names():
            content = ""
            for ai_cat, val in cat_map.items():
                if match_ai_label_to_dimension(ai_cat) == std_cat:
                    content = val
                    break
            r.hset(key, std_cat, content or "")

    # ----------------------------------------------------------------
    #  AI 提取记忆：用 DeepSeek 从章节文本中提取结构化信息
    # ----------------------------------------------------------------
    #  AI 提取记忆：Prompt 统一在 chapter_prompts.py 中定义
    # ----------------------------------------------------------------
    @staticmethod
    async def _extract_memory_with_ai(novel_settings: str, chapters_text: str) -> str:
        """调用 DeepSeek 从所有章节文本中提取结构化记忆体"""
        prompt = MEMORY_EXTRACT_PROMPT.format(chapter_texts=chapters_text)
        full_prompt = f"以下小说的作品设定：\n{novel_settings}\n\n{prompt}"

        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{deepseek_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {deepseek_api_key()}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": deepseek_model(),
                    "messages": [
                        {"role": "system", "content": "你是一位资深小说编辑，擅长从文本中提取结构化信息。"},
                        {"role": "user", "content": full_prompt}
                    ],
                    "thinking": {"type": "disabled"},
                    "max_tokens": 4096,
                    "temperature": 0.3
                }
            )
            data = response.json()
            if "choices" not in data or not data["choices"]:
                system_logger.error(f"[记忆体] AI提取失败: {data.get('error', {})}")

                return ""
            result = data["choices"][0]["message"]["content"]
            system_logger.info(f"[记忆体] AI提取完成，{len(result)} 字符")

            return result

    # ----------------------------------------------------------------
    #  增量记忆体：发布/更新章节时从单个新章节提取并追加
    # ----------------------------------------------------------------
    # 记忆体维度容量上限（保险丝级：防止极端异常场景内存失控，正常写作永远不触发）
    # 注：生成采用"按需检索注入"（每章只注入约15k字符），记忆体总量不进入 prompt、
    #     不影响生成速度，因此不再按行数/字符淘汰最旧条目——
    #     保证"写到多少章，早期章节记忆都全量保留、按需可查"。
    #     10万行/500万字符 ≈ 覆盖上万章小说，若未来确有需要可在此收紧。
    MEMORY_DIMENSION_LIMITS = {
        "人物": {"max_lines": 100000, "max_chars": 5000000},
        "组织势力": {"max_lines": 100000, "max_chars": 5000000},
        "功法技能法宝": {"max_lines": 100000, "max_chars": 5000000},
        "伏笔悬念": {"max_lines": 100000, "max_chars": 5000000},
        "实力变化": {"max_lines": 100000, "max_chars": 5000000},
        "关键物品": {"max_lines": 100000, "max_chars": 5000000},
        "地点": {"max_lines": 100000, "max_chars": 5000000},
        "时间线": {"max_lines": 100000, "max_chars": 5000000},
        "关键事件": {"max_lines": 100000, "max_chars": 5000000},
    }

    @staticmethod
    def _enforce_dimension_cap(category: str, text: str) -> str:
        """记忆体容量治理：超上限时淘汰最旧条目（保留最新）。
        先按行数上限淘汰，仍超字符上限则继续从最旧行淘汰。
        """
        limit = ChapterService.MEMORY_DIMENSION_LIMITS.get(category)
        if not limit or not text:
            return text
        lines = [ln for ln in text.split("\n") if ln.strip()]
        if len(lines) > limit["max_lines"]:
            lines = lines[-limit["max_lines"]:]
        while len("\n".join(lines)) > limit["max_chars"] and len(lines) > 1:
            lines.pop(0)  # 淘汰最旧（首行）
        return "\n".join(lines)

    @staticmethod
    def _cap_existing_memory(novel_unique_id: str) -> None:
        """存量记忆体治理：遍历所有维度，超限的压缩到上限（幂等，不超限不动）"""
        r = _redis()
        if not r or not r.ping():
            return
        key = ChapterService._memory_key(novel_unique_id)
        for cat in get_memory_category_names():
            old = r.hget(key, cat)
            if not old:
                continue
            capped = ChapterService._enforce_dimension_cap(cat, old)
            if capped != old:
                r.hset(key, cat, capped)
                system_logger.info(f"[记忆体治理] {cat}: {len(old)} → {len(capped)} 字符")

    @staticmethod
    def _append_to_dimension(novel_unique_id: str, category: str, new_text: str):
        """向 Redis Hash 中某个维度写入新内容（去重维度按首字段替换旧条目）"""
        if category not in get_memory_category_names():
            system_logger.warning(f"[记忆体] 非标准维度 '{category}'，跳过追加（允许: {get_memory_category_names()}）")
            return
        r = _redis()
        if not r or not r.ping():
            return
        key = ChapterService._memory_key(novel_unique_id)
        try:
            dedup_map = get_dimension_dedup_map()
            should_dedup = dedup_map.get(category, False)

            old_text = r.hget(key, category) or ""

            if should_dedup and old_text:
                # 按首字段（实体名）去重：新条目的实体名命中旧条目 → 替换；否则追加
                old_lines = [l.strip() for l in old_text.split("\n") if l.strip()]
                new_lines = [l.strip() for l in new_text.split("\n") if l.strip()]
                # 提取旧条目实体名（格式: [第X章] 实体名，后续）
                old_names = {}
                for i, line in enumerate(old_lines):
                    m = re.match(r'\[第\d+章\]\s*([^，,]+)', line)
                    if m:
                        old_names[m.group(1)] = i

                replaced = set()
                appended = []
                for line in new_lines:
                    m = re.match(r'\[第\d+章\]\s*([^，,]+)', line)
                    if m:
                        name = m.group(1)
                        if name in old_names and name not in replaced:
                            old_lines[old_names[name]] = line
                            replaced.add(name)
                            system_logger.info(f"[记忆体] 去重替换: {category}/{name}")
                        elif name not in replaced:
                            appended.append(line)
                            # 同名但已替换过的，也跳过（同一次追加中同一个实体只保留一条）
                        elif name in replaced:
                            # 同一次追加中同名实体多条 → 用最新一条覆盖
                            old_lines[old_names[name]] = line
                            system_logger.info(f"[记忆体] 同批覆盖: {category}/{name}")
                    else:
                        appended.append(line)

                merged_lines = old_lines + appended
                merged = "\n".join(merged_lines).strip()
            else:
                # 非去重维度，直接追加
                merged = (old_text + "\n" + new_text).strip() if old_text else new_text.strip()

            # 写入时治理：超上限淘汰最旧条目，保证记忆体总量有界
            merged = ChapterService._enforce_dimension_cap(category, merged)
            r.hset(key, category, merged)
            return {
                "success": True,
                "message": "记忆追加成功",
                "category": category,
                "old_length": len(old_text),
                "new_length": len(merged),
                "append_length": len(new_text),
                "deduped": should_dedup and bool(old_text)
            }
        except Exception as e:
            system_logger.error(f"[记忆体] 追加维度 {category} 失败: {e}")

    @staticmethod
    def _remove_from_dimension(novel_unique_id: str, category: str, chapter_name: str, chapter_num: int = None):
        """从 Redis Hash 某个维度中移除指定章节的条目
        :param category: 维度名
        :param chapter_name: 章节名称（如 "第五章 六年后"，匹配 [章节名] 和 [第X章] 标注）
        :param chapter_num: 章节序号（如 5，匹配 [第5章] 标注）
        """
        if category not in get_memory_category_names():
            return
        r = _redis()
        if not r or not r.ping():
            return
        key = ChapterService._memory_key(novel_unique_id)
        try:
            old_text = r.hget(key, category)
            if not old_text:
                return
            old_lines = old_text.split("\n")
            keep_lines = []
            removed = 0
            # 实际格式: [第五章 六年后] 内容... 或 [第5章] 内容...
            bracket_full = f"[{chapter_name}]"
            bracket_num = f"[第{chapter_num}章" if chapter_num else None
            for line in old_lines:
                if bracket_full in line:
                    removed += 1
                    continue
                if bracket_num and bracket_num in line:
                    removed += 1
                    continue
                keep_lines.append(line)
            if removed == 0:
                return
            new_text = "\n".join(keep_lines).strip()
            r.hset(key, category, new_text)
            system_logger.info(f"[记忆体] 删除 {category} 中 {chapter_name} 的 {removed} 条，{len(old_lines)}→{len(keep_lines)} 行")
        except Exception as e:
            system_logger.error(f"[记忆体] 删除维度 {category} 失败: {e}")


    @staticmethod
    def save_extracted_to_memory(novel_unique_id: str, info_data: dict, chapter_name: str):
        """
        extract-info 提取成功后，将管道符数据转为自然语言，追加到 Redis 记忆体
        info_data 格式: {"人物": "张三|散修|阴险多疑|第3章加入青云宗", "组织": "...", ...}
        转换后: "张三，散修，性格阴险多疑，在第3章加入了青云宗。"
        """
        field_map = get_frontend_to_dimension_map()
        r = _redis()
        key = ChapterService._memory_key(novel_unique_id)
        for front_field, dim_cat in field_map.items():
            raw_val = info_data.get(front_field, "")
            if not raw_val or raw_val == "无":
                continue
            # 幂等：该维度已含本章条目（[章节名] 前缀）则跳过，
            # 防止 修复补写/增量更新 对同一章重复追加导致记忆体膨胀
            if r:
                try:
                    old_dim = r.hget(key, dim_cat) or ""
                    if chapter_name and f"[{chapter_name}]" in old_dim:
                        continue
                except Exception:
                    pass
            natural = ChapterService._pipe_to_natural(front_field, raw_val, chapter_name)
            if not natural:
                continue
            ChapterService._append_to_dimension(novel_unique_id, dim_cat, natural)
            system_logger.info(f"[记忆体] extract后追加 {dim_cat}: +{len(natural)}字符")

        system_logger.info(f"[记忆体] {chapter_name} 提取信息已追加到记忆体")

    @staticmethod
    def _pipe_to_natural(field: str, raw_text: str, chapter_name: str) -> str:
        """管道符格式 → AI 可理解的自然语言。
        各维度根据前端 LIGHT_EXTRACT_PROMPT 约定的字段顺序转换。
        """
        lines = [l.strip() for l in raw_text.strip().split("\n") if l.strip()]
        # 过滤掉表头行（如 "姓名|身份|性格特点|当前状态|修为"）、占位噪声
        header_patterns = [
            "姓名|身份", "名称|性质", "地名|特征", "物品名|功能",
            "角色名|变化", "时间节点|发生", "名称|效果",
        ]
        noise_patterns = ["本章未提及", "本章未出现", "本章为背景", "本章无角色",
                          "故填写", "故仅列出", "暂无"]

        def is_noise(line: str) -> bool:
            for p in header_patterns:
                if line.startswith(p):
                    return True
            for p in noise_patterns:
                if p in line:
                    return True
            return False

        lines = [l for l in lines if not is_noise(l)]
        result = []

        if field == "人物":
            # 姓名|身份|性格特点|当前状态|修为
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                name = parts[0] if len(parts) > 0 else ""
                if not name or name == "无" or name == "（无）":
                    continue
                identity = parts[1] if len(parts) > 1 else ""
                character = parts[2] if len(parts) > 2 else ""
                status = parts[3] if len(parts) > 3 else ""
                level = parts[4] if len(parts) > 4 else ""
                pieces = []
                if name: pieces.append(name)
                if identity: pieces.append(f"是{identity}")
                if character: pieces.append(f"性格{character}")
                if level: pieces.append(f"修为{level}")
                if status and status not in ("无",): pieces.append(status)
                if pieces:
                    result.append("，".join(pieces) + "。")

        elif field == "组织":
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                name = parts[0] if len(parts) > 0 else ""
                if not name or name == "无" or name == "（无）":
                    continue
                nature = parts[1] if len(parts) > 1 else ""
                scale = parts[2] if len(parts) > 2 else ""
                trend = parts[3] if len(parts) > 3 else ""
                pieces = [name] if name else []
                if nature and nature not in ("无",): pieces.append(f"是一个{nature}")
                if scale and scale not in ("无",): pieces.append(f"约有{scale}")
                if trend and trend not in ("无",): pieces.append(f"目前{trend}")
                if pieces:
                    result.append("，".join(pieces) + "。")

        elif field == "功法技能":
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                name = parts[0] if len(parts) > 0 else ""
                if not name or name == "无" or name == "（无）":
                    continue
                effect = parts[1] if len(parts) > 1 else ""
                owner = parts[2] if len(parts) > 2 else ""
                source = parts[3] if len(parts) > 3 else ""
                pieces = [name] if name else []
                if effect: pieces.append(f"效果是{effect}")
                if owner: pieces.append(f"使用者为{owner}")
                if source: pieces.append(f"来源于{source}")
                if pieces:
                    result.append("，".join(pieces) + "。")

        elif field == "地点":
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                name = parts[0] if len(parts) > 0 else ""
                if not name or name == "无" or name == "（无）":
                    continue
                feature = parts[1] if len(parts) > 1 else ""
                event = parts[2] if len(parts) > 2 else ""
                pieces = [name] if name else []
                if feature: pieces.append(f"特征是{feature}")
                if event: pieces.append(f"在此发生了：{event}")
                if pieces:
                    result.append("，".join(pieces) + "。")

        elif field == "时间":
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                time = parts[0] if len(parts) > 0 else ""
                event = parts[1] if len(parts) > 1 else ""
                if not time or time == "无":
                    continue
                if time and event:
                    result.append(f"{time}，{event}。")
                elif time:
                    result.append(f"时间节点：{time}。")

        elif field == "关键物品":
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                name = parts[0] if len(parts) > 0 else ""
                if not name or name == "无" or name == "（无）":
                    continue
                effect = parts[1] if len(parts) > 1 else ""
                owner = parts[2] if len(parts) > 2 else ""
                pieces = [name] if name else []
                if effect: pieces.append(f"功能是{effect}")
                if owner: pieces.append(f"归属{owner}")
                if pieces:
                    result.append("，".join(pieces) + "。")

        elif field == "实力变化":
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                name = parts[0] if len(parts) > 0 else ""
                if not name or name == "无" or name == "（无）":
                    continue
                change = parts[1] if len(parts) > 1 else ""
                reason = parts[2] if len(parts) > 2 else ""
                pieces = [name] if name else []
                if change: pieces.append(f"实力从{change}")
                if reason: pieces.append(f"原因是{reason}")
                if pieces:
                    result.append("，".join(pieces) + "。")

        elif field in ("关键事件", "伏笔"):
            for line in lines:
                clean = line.lstrip("0123456789.、- ")
                if clean and clean not in ("无", "无。", "（无）"):
                    result.append(clean + "。")

        if result:
            return f"[{chapter_name}] " + " ".join(result)
        return ""

    @staticmethod
    def _trim_to_summary_boundary(generated_text: str, chapter_summary: str,
                                  tail_reserve: int = 500) -> str:
        """概要边界截断：防止模型把概要事件写完后仍超纲续写。

        只处理「明显超纲」的情况（截断点后残留 > tail_reserve 字）：
        - 模型写完概要最后事件后若只是自然收尾（钩子/余韵，≤ tail_reserve 字），
          保留全文——硬删会把章节结尾砍掉，造成"凤头马尾/狗尾续貂"；
        - 残留很多说明模型在续写概要之外的新剧情，此时截断，并保留截断点后
          最多 3 行短句作为收尾缓冲，避免戛然而止。
        """
        if not chapter_summary or not generated_text:
            return generated_text

        sentences = re.split(r'[，,。.！!？?；;]', chapter_summary)
        sentences = [s.strip() for s in sentences if len(s.strip()) >= 3]
        if len(sentences) < 2:
            return generated_text

        last_event = sentences[-1]
        # 提取 3-5 字符的关键子串（跳过连接词）
        clean = re.sub(r'(然后|接着|最后|后来|之后|随后|于是|突然|这一日|此时)', '', last_event).strip()
        if len(clean) < 4:
            return generated_text

        # 生成 3-5 字符的子串列表，用于精确匹配
        chunks = []
        for win_size in (5, 4, 3):
            for i in range(len(clean) - win_size + 1):
                chunk = clean[i:i + win_size]
                # 跳过纯标点/空白/连接词子串
                if re.match(r'^[的了着呢吗啊吧嗄]+$', chunk):
                    continue
                chunks.append(chunk)

        lines = generated_text.split('\n')
        target_line_idx = -1
        best_score = 0

        # 从后往前找，匹配子串最多的行
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if not line or len(line) < 10:
                continue
            score = sum(1 for chunk in chunks if chunk in line)
            if score > best_score:
                best_score = score
                target_line_idx = i

        # 需要至少匹配到 2 个子串才认为找到了
        if target_line_idx < 0 or best_score < 2:
            return generated_text

        # 截断点后的残留量：≤ tail_reserve 视为模型自然收尾（钩子/余韵），
        # 保留全文不截断，避免把章节结尾硬删掉
        tail_len = sum(len(l) for l in lines[target_line_idx + 1:])
        if tail_len <= tail_reserve:
            return generated_text

        keep_lines = lines[:target_line_idx + 1]
        # 截断后保留量过少（<50%）→ 落点匹配失败/误切，保留全文
        if len("\n".join(keep_lines)) < len(generated_text) * 0.5:
            return generated_text
        # 保留截断点后最多 3 行短句作为收尾缓冲，避免戛然而止
        for offset in (1, 2, 3):
            idx = target_line_idx + offset
            if idx < len(lines):
                next_line = lines[idx].strip()
                if next_line and len(next_line) <= 60:
                    keep_lines.append(lines[idx])
                else:
                    break

        return '\n'.join(keep_lines).strip()


    @staticmethod
    async def _rebuild_memory_for_chapter(novel_unique_id: str, old_chapter_name: str,
                                            content: str, chapter_name: str, chapter_summary: str):
        """章节内容修改后重建记忆体：先清旧→AI提取→写入新"""
        # 1. 清除该章节的所有旧记忆条目
        for cat in get_memory_category_names():
            if cat == "作品设定":
                continue
            ChapterService._remove_from_dimension(novel_unique_id, cat, old_chapter_name)
        system_logger.info(f"[记忆体重建] 已清除 {old_chapter_name} 旧条目")

        # 2. 用 AI 重新提取
        info_data = {}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                _genre = ChapterService._get_novel_genre(novel_unique_id)
                prompt = FULL_EXTRACT_PROMPT.replace("{content}", content[-15000:]).replace("{novel_genre}", _genre)
                response = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {deepseek_api_key()}", "Content-Type": "application/json"},
                    json={"model": deepseek_model(), "messages": [
                        {"role": "system", "content": "你是一位资深小说编辑，擅长从文本中提取结构化信息，输出详尽完整的章节分析报告。"},
                        {"role": "user", "content": prompt}
                    ], "thinking": {"type": "disabled"}, "max_tokens": 8000, "temperature": 0.2},
                )
                if response.status_code == 200:
                    data = response.json()
                    content_resp = data["choices"][0]["message"]["content"]
                    info_data = ChapterService._parse_extract_result(content_resp)
                    system_logger.info(f"[记忆体重建] AI 提取完成: {len(info_data)} 个维度")
        except Exception as e:
            system_logger.error(f"[记忆体重建] AI 提取失败: {e}")
            if chapter_summary:
                info_data["关键事件"] = chapter_summary

        # 3. 写入新条目
        if info_data:
            ChapterService.save_extracted_to_memory(novel_unique_id, info_data, chapter_name)
        system_logger.info(f"[记忆体重建] {chapter_name} 记忆体重建完成")

    @staticmethod
    async def _extract_and_append_to_memory(novel_unique_id: str, content: str,
                                             chapter_name: str, chapter_summary: str):
        """发布章节时后台 AI 提取维度信息并写入 Redis 记忆体"""
        info_data = {}
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                # 使用 FULL_EXTRACT_PROMPT 提取更详细的信息，内容不截断
                extract_content = content if len(content) <= 15000 else content[:7500] + "\n...\n" + content[-7500:]
                _genre = ChapterService._get_novel_genre(novel_unique_id)
                prompt = FULL_EXTRACT_PROMPT.replace("{content}", extract_content).replace("{novel_genre}", _genre)
                response = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {deepseek_api_key()}", "Content-Type": "application/json"},
                    json={"model": deepseek_model(), "messages": [
                        {"role": "system", "content": "你是一位资深小说编辑，擅长从文本中提取结构化信息，输出详尽完整的章节分析报告。关键事件必须逐件列出，不要遗漏。"},
                        {"role": "user", "content": prompt}
                    ], "thinking": {"type": "disabled"}, "max_tokens": 8000, "temperature": 0.2},
                )
                if response.status_code == 200:
                    data = response.json()
                    content_resp = data["choices"][0]["message"]["content"]
                    info_data = ChapterService._parse_extract_result(content_resp)
                    system_logger.info(f"[发布-提取] AI 提取完成: {len(info_data)} 个维度")
                else:
                    system_logger.error(f"[发布-提取] AI 请求失败: {response.status_code}")
        except Exception as e:
            system_logger.error(f"[发布-提取] AI 提取异常: {e}")
            if chapter_summary:
                info_data["关键事件"] = chapter_summary

        if info_data:
            ChapterService.save_extracted_to_memory(novel_unique_id, info_data, chapter_name)
            system_logger.info(f"[发布-提取] {chapter_name} 维度信息已写入 Redis 记忆体")
        else:
            system_logger.warning(f"[发布-提取] {chapter_name} 无提取数据，记忆体未更新")

    @staticmethod
    def _parse_extract_result(raw_text: str) -> dict:
        """解析 AI 提取结果 → frontend 管道符格式（供 save_extracted_to_memory 使用）
        
        AI 输出格式:
        ---人物---
        姓名|身份|性格|状态|修为
        ---组织---
        名称|性质|规模|动向
        ---功法技能---
        名称|效果|归属者|来源
        ---关键事件---
        事件描述...
        ---地点---
        地名|特征|事件
        ---时间---
        时间节点|事件
        ---关键物品---
        物品名|功能|归属
        ---实力变化---
        角色名|变化前→变化后|原因
        ---伏笔---
        描述...
        """
        result = {}
        # 维度映射: AI header → frontend field name
        # 支持 LIGHT_EXTRACT_PROMPT 和 FULL_EXTRACT_PROMPT 两种格式
        section_map = {
            "人物": "人物",
            "组织": "组织", "组织/势力": "组织",
            "功法技能": "功法技能", "功法/技能/法宝": "功法技能",
            "关键事件": "关键事件",
            "地点": "地点",
            "时间": "时间", "时间线": "时间",
            "关键物品": "关键物品",
            "实力变化": "实力变化",
            "伏笔": "伏笔", "伏笔/悬念": "伏笔",
        }

        # 按 ---xxx--- 切分
        sections = re.split(r'^---\s*(.+?)\s*---\s*$', raw_text, flags=re.MULTILINE)
        # sections[0]=前缀, sections[1]=header1, sections[2]=body1, ...

        for i in range(1, len(sections), 2):
            header = sections[i].strip()
            body = sections[i + 1].strip() if i + 1 < len(sections) else ""
            front_field = section_map.get(header, header)

            lines = [l.strip() for l in body.split("\n") if l.strip()]
            # 过滤掉分隔线、提示语、空行
            lines = [l for l in lines
                     if not l.startswith("（") and not l.startswith("---") and l != "无" and l != "无。"]
            if lines:
                result[front_field] = "\n".join(lines)

        return result

    @staticmethod
    async def _incremental_memory_update(novel_unique_id: str, db: Session,
                                          chapter_content: str, chapter_name: str,
                                          chapter_summary: str = ""):
        """
        增量更新记忆体：
        1. 加载现有全量记忆体
        2. 仅对本章节内容调用 AI 提取新信息
        3. 按维度追加到现有记忆中
        保持已有记忆不变，只累加新章节的信息。
        """
        novel_settings = ChapterService._get_novel_settings(novel_unique_id)
        settings_text = novel_settings.get('content', '无')

        # 加载现有记忆体
        existing = ChapterService._load_memory(novel_unique_id)
        if not existing:
            # 记忆体不存在 → 全量构建
            system_logger.info("[记忆体] 首次构建，走全量模式")

            await ChapterService._rebuild_memory_from_files(novel_unique_id, db)
            return

        # 截取章节内容（尽量完整，超长取前7500+后7500=15000字）
        text_len = len(chapter_content)
        if text_len <= 15000:
            snippet = chapter_content
        else:
            snippet = chapter_content[:7500] + "\n...\n" + chapter_content[-7500:]

        chapter_text = f"=== {chapter_name} ==="
        if chapter_summary:
            chapter_text += f"\n概要：{chapter_summary}"
        chapter_text += f"\n内容：{snippet}"

        # 构建增量提取 prompt
        # 按维度截取，每个维度保留最新 1500 字，避免只看到末尾一个维度
        existing_for_ai = existing
        if len(existing) > 8000:
            sections = re.split(r'\n(?=【)', existing)
            trimmed_sections = []
            for sec in sections:
                if len(sec) > 1500:
                    trimmed_sections.append(sec[-1500:])
                else:
                    trimmed_sections.append(sec)
            existing_for_ai = "\n".join(trimmed_sections)

        prompt = MEMORY_INCREMENTAL_PROMPT.format(
            chapter_content=chapter_text,
            existing_memory=existing_for_ai
        )

        full_prompt = f"以下小说的作品设定：\n{settings_text}\n\n 只参考设定不重复输出，只提取本章新增内容。\n\n{prompt}"

        # Mock 模式（压测用）：跳过 AI 增量提取，避免消耗真实 DeepSeek
        from app.config import get as cfg_get
        if cfg_get("ai.mock_generate", False):
            system_logger.info("[记忆体] Mock模式，跳过增量提取")
            return

        # 调 AI 提取本章新增信息
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                response = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {deepseek_api_key()}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": deepseek_model(),
                        "messages": [
                            {"role": "system", "content": "你是一位资深小说编辑，只提取文本中的新增关键信息。"},
                            {"role": "user", "content": full_prompt}
                        ],
                        "thinking": {"type": "disabled"},
                        "max_tokens": 8000,
                        "temperature": 0.3
                    }
                )
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    system_logger.error(f"[记忆体] 增量提取失败: {data.get('error', {})}")

                    return
                result = data["choices"][0]["message"]["content"]
                system_logger.info(f"[记忆体] 增量提取完成，{len(result)} 字符")

                system_logger.info(f"[记忆体] 提取内容预览：\n{result[:300]}...")

            except Exception as e:
                system_logger.error(f"[记忆体] 增量提取异常: {e}")

                return

        # 解析并按维度追加
        sections = re.split(r'\n(?=【)', result)
        for sec in sections:
            m = re.match(r'【(.+?)】\s*\n?(.*)', sec, re.DOTALL)
            if not m:
                continue
            ai_cat = m.group(1)
            new_content = m.group(2).strip()
            if not new_content or new_content == "无新增":
                continue

            # 用统一维度映射匹配
            matched = match_ai_label_to_dimension(ai_cat)
            if matched:
                ChapterService._append_to_dimension(novel_unique_id, matched, new_content)
                system_logger.info(f"[记忆体] 增量追加 {matched}: +{len(new_content)} 字符")
            else:
                system_logger.warning(f"[记忆体] 未识别的AI维度标签: {ai_cat}")

        system_logger.info(f"[记忆体] 章节 {chapter_name} 增量更新完成")


    # ----------------------------------------------------------------
    #  全量记忆体：逐章提取 → 本地代码合并去重 → 存Redis记忆体
    # ----------------------------------------------------------------

    @staticmethod
    def _aggregate_memory_by_code(settings_text: str, chapter_summaries: list) -> str:
        """本地代码合并记忆体（不调 AI）：逐章提取结果按维度去重合并"""
        # 从统一配置构建 (name, [aliases], title, dedup)
        DIMENSIONS = []
        for dim_key, frontend_key, _, dedup in MEMORY_DIMENSION_DEFS:
            if dim_key == "作品设定":
                continue
            aliases = [frontend_key]
            # 补充常用别名（代码解析用）
            if dim_key == "功法技能法宝":
                aliases.append("功法技能")
            elif dim_key == "组织势力":
                aliases.append("组织")
            elif dim_key == "时间线":
                aliases.append("时间")
            elif dim_key == "伏笔悬念":
                aliases.append("伏笔")
            DIMENSIONS.append((dim_key, aliases, f"【{dim_key}】", dedup))
        # 旧版 prompt 可能有的额外维度
        DIMENSIONS.extend([
            ("境界",   ["境界"],   "【境界】",   True),
            ("章节数", ["章节数"], "【章节数】", False),
        ])
        raw = {d[0]: [] for d in DIMENSIONS}
        chapter_count = 0
        for summary in chapter_summaries:
            lines = summary.split("\n")
            chapter_name = ""
            chapter_num = 0
            current_field = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                header_m = re.match(r'^===\s*第?\s*([\d零一二三四五六七八九十百]+)\s*章\s*(.+?)\s*===$', line)
                if header_m:
                    num_str = header_m.group(1)
                    chapter_num = int(num_str) if num_str.isdigit() else ChapterService._cn_num_to_int(num_str)
                    chapter_name = header_m.group(2).strip()
                    chapter_count += 1
                    continue
                field_m = re.match(r'^\s*(\S+?)\s*[:：]\s*(.*)', line)
                if field_m:
                    fname = field_m.group(1).strip()
                    fval = field_m.group(2).strip()
                    for dim_name, aliases, _, _ in DIMENSIONS:
                        if fname in aliases:
                            if fval and fval not in ("无", "无新增", "无新", "—"):
                                raw[dim_name].append((chapter_num, chapter_name, fval))
                            current_field = dim_name
                            break
                elif current_field and line and not line.startswith("==="):
                    for dim_name, _, _, _ in DIMENSIONS:
                        if dim_name == current_field:
                            raw[dim_name].append((chapter_num, chapter_name, line))
                            break
        sections = [f"【作品设定】\n{settings_text}\n"]
        sections.append(f"当前已写{chapter_count}章\n")
        for dim_name, _aliases, title, dedup in DIMENSIONS:
            entries = raw[dim_name]
            if not entries:
                continue
            if dedup:
                merged = {}
                for num, ch, val in entries:
                    key = val.split("|")[0].strip() if "|" in val else val[:20]
                    if key not in merged:
                        merged[key] = val
                    elif val != merged[key]:
                        merged[key] = val
                deduped = list(merged.values())
                if deduped:
                    sections.append(title)
                    sections.extend(deduped)
                    sections.append("")
            else:
                sections.append(title)
                for num, ch, val in entries:
                    # 关键事件带 [第X章] 前缀，供按需检索按当前章节号筛选"最近3章"
                    prefix = f"[第{num}章] " if num and dim_name == "关键事件" else ""
                    sections.append(prefix + val)
                sections.append("")
        return "\n".join(sections)

    @staticmethod
    async def _rebuild_memory_from_files(novel_unique_id: str, db: Session = None) -> str:
        """
        全量重建记忆体（逐章提取版）：
        1. 扫描本地所有章节 txt 文件（按修改时间排序）
        2. 每章调用轻量 extract_chapter_info 提取 人物/组织/功法/事件/地点/时间/物品/实力/伏笔
        3. 汇总所有章节的提取信息，拼接为摘要文本
        4. 发给 AI 合成最终的 10 维度记忆体
        5. 存入 Redis记忆体
        """
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        os.makedirs(novel_dir, exist_ok=True)

        novel_settings = ChapterService._get_novel_settings(novel_unique_id)
        settings_text = novel_settings.get('content', '无')

        # 扫描章节 txt
        txt_files = [f for f in os.listdir(novel_dir) if f.endswith(".txt") and f != "作品设定.txt"]

        # 按章节号排序（支持中文数字，如"第三十一章"→31；修复按修改时间排序导致记忆体错乱的问题）
        def _extract_chapter_num(fname):
            match = re.search(r'第([\d零一二三四五六七八九十百]+)章', fname)
            if not match:
                return 9999
            num_str = match.group(1)
            if num_str.isdigit():
                return int(num_str)
            return ChapterService._cn_num_to_int(num_str)
        txt_files.sort(key=_extract_chapter_num)

        if not txt_files:
            memory = f"""【作品设定】\n{settings_text}"""
            ChapterService._save_memory(novel_unique_id, memory)
            return memory

        # 逐章提取关键信息（asyncio 并发，线程数从 config.yaml 读取）
        import asyncio
        from app.config import get as cfg
        concurrency = cfg("redis.memory_extract_threads", 10)
        _novel_genre = ChapterService._get_novel_genre(novel_unique_id)

        async def extract_one(idx: int, fname: str, sem: asyncio.Semaphore):
            """并发提取单个章节的关键信息，返回 (idx, summary_str)"""
            async with sem:
                fpath = os.path.join(novel_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        full_text = f.read()
                except Exception:
                    return (idx, None)

                if full_text.strip().startswith("{"):
                    return (idx, None)

                chapter_name = fname.rsplit("_", 1)[0] if "_" in fname else fname.replace(".txt", "")

                info = await ChapterService._extract_with_light_prompt(full_text, _novel_genre)

                if info.get("success") and info.get("data"):
                    data = info["data"]
                    lines = [f"=== 第{idx+1}章 {chapter_name} ==="]
                    for field in ["人物", "组织", "功法技能", "关键事件", "地点", "时间", "关键物品", "实力变化", "伏笔"]:
                        val = data.get(field, "")
                        if val and val != "无":
                            lines.append(f"  {field}: {val}")
                    result_text = "\n".join(lines)
                    system_logger.info(f"[记忆体] 第{idx+1}章 {chapter_name} 提取完成 ({len(result_text)}字)")

                    return (idx, result_text)
                else:
                    snippet = full_text[:300].replace("\n", " ")
                    system_logger.error(f"[记忆体] 第{idx+1}章 {chapter_name} 提取失败，兜底: {snippet[:80]}...")

                    return (idx, f"=== 第{idx+1}章 {chapter_name} ===\n  (提取失败，概要): {snippet}")

        import asyncio
        total = len(txt_files)
        sem = asyncio.Semaphore(concurrency)
        system_logger.info(f"[记忆体] 开始并发提取，共{total}章，并发数={concurrency}")


        tasks = [extract_one(i, fname, sem) for i, fname in enumerate(txt_files)]
        results_list = await asyncio.gather(*tasks)

        # 按原始顺序整理结果
        results_sorted = sorted([r for r in results_list if r[1] is not None], key=lambda x: x[0])
        chapter_summaries = [r[1] for r in results_sorted]
        chapter_num = len(chapter_summaries)

        chapters_text = "\n\n".join(chapter_summaries)
        system_logger.info(f"[记忆体] 逐章提取完成，共{chapter_num}章")

        # === 本地代码合并记忆体（不调 AI，按维度去重合并逐章提取结果）===
        memory = ChapterService._aggregate_memory_by_code(settings_text, chapter_summaries)
        system_logger.info(f"[记忆体] 聚合结果 ({len(memory)}字):\n{memory}")

        ChapterService._save_memory(novel_unique_id, memory)
        return memory

    @staticmethod
    def _cn_num_to_int(s: str) -> int:
        """中文数字转阿拉伯数字（支持 一~九十九，含 百），如 三十一 → 31"""
        total, num = 0, 0
        for ch in s:
            if ch in "零〇":
                continue
            elif ch in "一二三四五六七八九":
                num = "一二三四五六七八九".index(ch) + 1
            elif ch == "十":
                total += (num or 1) * 10
                num = 0
            elif ch == "百":
                total += (num or 1) * 100
                num = 0
            else:
                return 9999
        return total + num

    @staticmethod
    async def _rebuild_memory_from_files_with_progress(novel_unique_id: str, db, task_id: str, total_chapters: int) -> str:
        """并发提取+逐章入库：20并发同时提取，每完成一章立即增量保存到 Redis 并上报进度"""
        from app.utils.task_queue import TaskQueue
        import os
        import asyncio

        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        if not os.path.isdir(novel_dir):
            system_logger.warning(f"[记忆体] 目录不存在: {novel_dir}")
            return ""

        # 按章节号排序（支持中文数字，保证关键事件按剧情顺序）
        def _extract_chapter_num(fname):
            match = re.search(r'第([\d零一二三四五六七八九十百]+)章', fname)
            if not match:
                return 9999
            num_str = match.group(1)
            if num_str.isdigit():
                return int(num_str)
            return ChapterService._cn_num_to_int(num_str)
        txt_files = sorted(
            [f for f in os.listdir(novel_dir) if f.endswith(".txt") and not f.startswith("settings") and "作品设定" not in f],
            key=_extract_chapter_num,
        )
        if not txt_files:
            system_logger.warning(f"[记忆体] {novel_dir} 下无 txt 文件")
            return ""

        settings_text = ""
        settings_path = os.path.join(novel_dir, "settings.txt")
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                settings_text = f.read()

        effective_total = len(txt_files)
        from app.config import get as cfg
        concurrency = int(cfg("redis.memory_extract_threads", 10))
        system_logger.info(f"[记忆体] 开始并发提取，共 {effective_total} 章，并发数={concurrency}")

        chapter_results = {}  # idx → (chapter_name, result_text)
        completed_count = 0
        lock = asyncio.Lock()

        async def extract_one(idx: int, fname: str, sem: asyncio.Semaphore):
            nonlocal completed_count
            async with sem:
                fpath = os.path.join(novel_dir, fname)
                chapter_name = fname.rsplit("_", 1)[0] if "_" in fname else fname.replace(".txt", "")

                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        full_text = f.read()
                except Exception:
                    async with lock:
                        completed_count += 1
                        if task_id:
                            TaskQueue.set_progress(task_id, completed_count, effective_total, f"第 {completed_count}/{effective_total} 章（跳过）")
                    return

                if full_text.strip().startswith("{"):
                    async with lock:
                        completed_count += 1
                        if task_id:
                            TaskQueue.set_progress(task_id, completed_count, effective_total, f"第 {completed_count}/{effective_total} 章（跳过）")
                    return

                info = await ChapterService.extract_chapter_info_local(full_text, chapter_name)

                if info.get("success") and info.get("data"):
                    data = info["data"]
                    lines = [f"=== 第{idx+1}章 {chapter_name} ==="]
                    # 日志输出每一章的提取结果明细
                    log_lines = [f"[记忆体] >> 第{idx+1}章 {chapter_name} 提取明细:"]
                    for field in ["人物", "组织", "功法技能", "关键事件", "地点", "时间", "关键物品", "实力变化", "伏笔"]:
                        val = data.get(field, "")
                        if val and val != "无":
                            lines.append(f"  {field}: {val}")
                            log_lines.append(f"[记忆体] >>   {field}: {val}")
                    for l in log_lines:
                        system_logger.info(l)
                    result_text = "\n".join(lines)
                    system_logger.info(f"[记忆体] 第{idx+1}章 {chapter_name} 本地提取完成 ({len(result_text)}字)")
                else:
                    snippet = full_text[:300].replace("\n", " ")
                    system_logger.error(f"[记忆体] 第{idx+1}章 {chapter_name} 本地提取失败，兜底")
                    result_text = f"=== 第{idx+1}章 {chapter_name} ===\n  (提取失败，概要): {snippet}"

                async with lock:
                    chapter_results[idx] = chapter_name, result_text
                    completed_count += 1

                    # 按索引排序，用已完成的章节增量聚合后保存到 Redis
                    sorted_indices = sorted(chapter_results.keys())
                    current_summaries = [chapter_results[i][1] for i in sorted_indices]
                    incremental_memory = ChapterService._aggregate_memory_by_code(settings_text, current_summaries)
                    ChapterService._save_memory(novel_unique_id, incremental_memory)

                    if task_id:
                        TaskQueue.set_progress(task_id, completed_count, effective_total, f"第 {completed_count}/{effective_total} 章：{chapter_name} 已记录")

        sem = asyncio.Semaphore(concurrency)
        tasks = [extract_one(i, fname, sem) for i, fname in enumerate(txt_files)]
        await asyncio.gather(*tasks)

        sorted_indices = sorted(chapter_results.keys())
        chapter_summaries = [chapter_results[i][1] for i in sorted_indices]
        system_logger.info(f"[记忆体] 逐章提取完成，共{len(chapter_summaries)}章")

        final_memory = ChapterService._aggregate_memory_by_code(settings_text, chapter_summaries)
        ChapterService._save_memory(novel_unique_id, final_memory)
        return final_memory

    @staticmethod
    async def _ensure_memory_chain(novel_unique_id: str, db: Session = None, current_chapter_num: int = 1) -> str:
        """三数据源完整性校验 + 修复 + 记忆体加载（以本地 TXT 为准）

        以本地 TXT 章节文件为基准（txt 必须存在）：
        1. mysql 缺失（txt 有、mysql 无）→ 补插 MySQL 章节记录
        2. redis 缺失（txt 有、redis 无）→ 读取 txt 内容 → DeepSeek AI 提取
           → 写入 Redis 补全（并发数 = config.yaml redis.memory_extract_threads）

        最终返回完整的记忆体文本。
        """
        import asyncio
        from app.config import get as cfg
        from app.models.chapter import Chapter as ChapterModel
        from app.models.novel import Novel as NovelModel

        # ============================================================
        # 1. 以本地 TXT 为准，扫描全部章节文件（章节号 / 章节名 / 文件ID / 内容）
        # ============================================================
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        txt_chapters = {}  # num -> {"num","name","cid","content"}
        if os.path.isdir(novel_dir):
            for f in sorted(os.listdir(novel_dir)):
                if not f.endswith(".txt") or "设定" in f:
                    continue
                n = ChapterGenService._extract_chapter_num(f)
                if n <= 0:
                    continue
                m = re.match(r'^(.*)_([0-9a-f]{32})\.txt$', f)
                if m:
                    name, cid = m.group(1), m.group(2)
                else:
                    name, cid = f[:-4], ""
                try:
                    with open(os.path.join(novel_dir, f), "r", encoding="utf-8") as fp:
                        content = fp.read()
                except Exception as e:
                    system_logger.error(f"[三源校验] 读取TXT失败 {f}: {e}")
                    content = ""
                txt_chapters.setdefault(n, {"num": n, "name": name, "cid": cid, "content": content})

        if not txt_chapters:
            system_logger.warning(f"[三源校验] novel={novel_unique_id} 无任何 TXT 章节文件，跳过修复")
            return await ChapterService._ensure_memory(novel_unique_id, db)

        # ============================================================
        # 2. mysql 比对：txt 有、mysql 无 → 补插 MySQL 章节记录
        # ============================================================
        mysql_nums = {}
        existing_cids = set()
        if db:
            try:
                all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id) or []
                for c in all_chapters:
                    existing_cids.add(c.chapter_unique_id)
                    n = ChapterGenService.chapter_no(c)
                    if n > 0:
                        mysql_nums.setdefault(n, c.chapter_unique_id)
            except Exception as e:
                system_logger.error(f"[三源校验] MySQL 读取失败: {e}")

        missing_mysql = [tc for tc in txt_chapters.values() if tc["num"] not in mysql_nums]
        if missing_mysql and db:
            novel = db.query(NovelModel).filter(
                NovelModel.novel_unique_id == novel_unique_id
            ).first()
            user_id = novel.author_user_id if novel else 0
            created_by = novel.author_name if novel else ""
            inserted = 0
            for tc in missing_mysql:
                # cid 已存在（草稿/已发布任一状态）→ 跳过，避免唯一键冲突
                if tc["cid"] and tc["cid"] in existing_cids:
                    system_logger.warning(
                        f"[三源校验] 第{tc['num']}章 txt cid={tc['cid']} 在 MySQL 已存在（草稿或已发布），跳过补插"
                    )
                    continue
                db.add(ChapterModel(
                    novel_unique_id=novel_unique_id,
                    user_id=user_id,
                    chapter_unique_id=tc["cid"],
                    chapter_name=tc["name"],
                    chapter_number=tc["num"],
                    chapter_summary="",
                    word_count=len(tc["content"]),
                    is_published=1,
                    created_by=created_by,
                ))
                inserted += 1
                system_logger.warning(
                    f"[三源校验] 以txt为准补插MySQL: 第{tc['num']}章 {tc['name']}"
                )
            db.commit()
            system_logger.info(f"[三源校验] MySQL 修复完成: 补插 {inserted} 章")

        # ============================================================
        # 3. redis 比对：txt 有、redis 无 → DeepSeek AI 提取写回（并发）
        # ============================================================
        r = _redis()
        redis_nums = ChapterGenService._redis_chapter_nums(novel_unique_id) if r else set()
        missing_redis = [tc for tc in txt_chapters.values() if tc["num"] not in redis_nums]

        if missing_redis:
            max_concurrency = cfg("redis.memory_extract_threads", 10)
            sem = asyncio.Semaphore(max_concurrency)
            _novel_genre = ChapterService._get_novel_genre(novel_unique_id)

            async def _extract_only(name: str, content: str) -> tuple:
                """仅做 AI 提取，不写 Redis"""
                async with sem:
                    # Mock 模式（压测用）：不调用真实 DeepSeek
                    from app.config import get as cfg_get
                    if cfg_get("ai.mock_generate", False):
                        from app.prompts.chapter_prompts import get_memory_category_names
                        return name, {d: [] for d in get_memory_category_names()}
                    info_data = {}
                    try:
                        async with httpx.AsyncClient(timeout=120) as client:
                            prompt = LIGHT_EXTRACT_PROMPT.replace("{content}", content[-8000:]).replace("{novel_genre}", _novel_genre)
                            resp = await client.post(
                                f"{deepseek_base_url()}/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {deepseek_api_key()}",
                                    "Content-Type": "application/json"
                                },
                                json={
                                    "model": deepseek_model(),
                                    "messages": [
                                        {"role": "system", "content": "你是一位资深小说编辑，擅长从文本中提取结构化信息。"},
                                        {"role": "user", "content": prompt}
                                    ],
                                    "thinking": {"type": "disabled"},
                                    "max_tokens": 4000, "temperature": 0.2
                                },
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                text = data["choices"][0]["message"]["content"]
                                info_data = ChapterService._parse_extract_result(text)
                    except Exception as e:
                        system_logger.error(f"[并发修复] AI提取异常 {name}: {e}")
                    return name, info_data

            system_logger.info(
                f"[三源校验] 以txt为准并发修复 {len(missing_redis)} 章记忆体"
                f"（DeepSeek 提取，并发数={max_concurrency}）"
            )
            results = await asyncio.gather(*[
                _extract_only(tc["name"], tc["content"])
                for tc in missing_redis
            ])

            # 串行写入 Redis（避免并发 HSET 覆盖；save_extracted_to_memory 幂等防重复追加）
            written = 0
            for name, info_data in results:
                if info_data:
                    ChapterService.save_extracted_to_memory(novel_unique_id, info_data, name)
                    written += 1
            system_logger.info(
                f"[三源校验] 修复完成: 共提取 {len(results)} 章，写入 Redis {written} 章"
            )

        # 存量记忆体治理（幂等：超上限才裁剪，防止全量累加膨胀）
        ChapterService._cap_existing_memory(novel_unique_id)

        # 最终加载记忆体（治理后）
        return await ChapterService._ensure_memory(novel_unique_id, db)

    @staticmethod
    async def _ensure_memory(novel_unique_id: str, db: Session = None) -> str:
        """获取记忆体：Redis 记忆体有则直接用，没有则从本地txt全量构建"""
        memory = ChapterService._load_memory(novel_unique_id)
        if memory:
            return memory
        return await ChapterService._rebuild_memory_from_files(novel_unique_id, db)

    @staticmethod
    async def _refresh_memory_after_generate(novel_unique_id: str, db: Session = None,
                                              chapter_content: str = "", chapter_name: str = "",
                                              chapter_summary: str = ""):
        """AI生成章节后，增量更新记忆体（提取本章关键信息追加到已有记忆体）"""
        if chapter_content:
            await ChapterService._incremental_memory_update(
                novel_unique_id, db, chapter_content, chapter_name, chapter_summary
            )
        else:
            # 无内容时走全量重建（兜底）
            await ChapterService._rebuild_memory_from_files(novel_unique_id, db)

    @staticmethod
    async def _extract_with_light_prompt(content: str, novel_genre: str = "") -> dict:
        """AI 轻量提取章节关键信息（LIGHT_EXTRACT_PROMPT），返回 {"success": True, "data": {...}}"""
        # Mock 模式（压测用）：返回空维度结构，不调用真实 DeepSeek
        from app.config import get as cfg
        if cfg("ai.mock_generate", False):
            from app.prompts.chapter_prompts import get_memory_category_names
            return {"success": True, "data": {d: [] for d in get_memory_category_names()}}
        _genre = novel_genre or "小说"
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                prompt = LIGHT_EXTRACT_PROMPT.replace("{content}", content[-8000:]).replace("{novel_genre}", _genre)
                resp = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {deepseek_api_key()}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": deepseek_model(),
                        "messages": [
                            {"role": "system", "content": "你是一位资深小说编辑，擅长从文本中提取结构化信息。"},
                            {"role": "user", "content": prompt}
                        ],
                        "thinking": {"type": "disabled"},
                        "max_tokens": 4000, "temperature": 0.2
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    parsed = ChapterService._parse_extract_result(text)
                    if not parsed:
                        system_logger.warning(f"[AI提取] 解析结果为空，原始响应前500字: {text[:500]}")
                    return {"success": True, "data": parsed}
                else:
                    system_logger.error(f"[AI提取] DeepSeek返回非200: status={resp.status_code}, body={resp.text[:500]}")
                    return {"success": False, "data": {}}
        except Exception as e:
            system_logger.error(f"[AI提取] 异常: {e}")
            return {"success": False, "data": {}}

    @staticmethod
    async def extract_chapter_info_local(content: str, chapter_name: str = "") -> dict:
        """
        HanLP NER + Jieba + 规则增强 提取章节关键信息（不调AI），速度极快
        返回与 extract_chapter_info 相同格式: {"success": True, "data": {...}}
        """
        if not content or len(content) < 50:
            return {"success": True, "data": {f: "" for f in ("人物","组织","功法技能","关键事件","地点","时间","关键物品","实力变化","伏笔")}}

        import asyncio
        import re

        # ==================== 通用停用词（任何分类提取到这些词都应被过滤） ====================
        COMMON_STOP_WORDS = {
            # 时间/方位
            "后面","前面","上面","下面","里面","外面","旁边","之上","之下","之中","之间","之后","之前",
            "身上","眼前","脚下","手里","怀中","背后","面前","身边","头顶",
            # 数量/程度
            "一声","一下","一人","一丝","一眼","一步","一道","一股","一身","一把","一片",
            "一个","两个","三个","几个","多个","每次","每天",
            "一点","一些","一点","一刻","一瞬",
            # 状态
            "浑身","全身","整个","片刻","瞬间",
            "突然","忽然","猛然","顿时","刹那",
            "此刻","此时","这时","那时","同时",
            "仿佛","好像","似乎","犹如","如同",
            "正好","正是","就是","只是","可是","但是",
            "因为","所以","如果","虽然","然而","不过",
            "于是","然后","还是","或者","不然",
            "可以","能够","应该","必须","需要","值得",
            "可能","也许","大概","恐怕","难道",
            "已经","刚刚","正在","将要","就要",
            # 动作/心理
            "不知","不见","不分","不敢","不能","不会","不肯",
            "起来","出来","进来","过来","回来","上来","下来",
            "出去","进去","过去","回去","上去","下去",
            "抬头","低头","回头","点头","摇头","转身","开口","闭嘴",
            "伸手","抬手","挥手","摆手","握手","松手","放手",
            "抬脚","迈步","踏步","脚步","步伐","步子",
            "睁眼","闭眼","瞪眼","眨眼","眯眼","抬眼",
            "呼吸","喘气","叹气","吸气","呼气","喘着",
            "咬牙","皱眉","握拳","攥拳","捏拳",
            "心道","暗道","心想","暗想","寻思","思忖",
            "只听","但见","只见","便见","就见","却见",
            "看着","望着","盯着","瞪着","瞅着",
            "听到","听见","闻到","嗅到","感到","觉得",
            "忍住","忍着","忍不住","禁不住","不由得",
            # 感官/性质
            "味道","滋味","气味","气息",
            "脸上","眼中","嘴角","心头","心底","心中","胸中",
            "越来越","渐渐地","慢慢地","缓缓地","轻轻地",
            "狠狠地","猛地",
            "果然","当然","自然","仍然","依然",
            "时间","时候","时辰","时刻",
            "结果","然后","后来","最后","最终",
            # 指代/疑问
            "这个","那个","哪个","这些","那些",
            "什么","怎么","怎样","这么","那么","多么",
            "没有","不是","还是",
            "这里","那里","哪里","这边","那边",
            # 特殊
            "东西","地方","方向",
            "年纪","年龄","年岁","样子","模样","身形",
            "名字","称呼","绰号","外号","字号",
        }

        # 人名过滤：以这些字结尾的大概率不是人名
        NAME_BAD_END = set("的了着过吧吗啊呢呀哦哈嗯哇呗嘛哟呐哩也")

        # 人名过滤：以这些字开头的肯定不是人名（介词/助词/代词/副词/连词）
        NAME_BAD_START = set("的了在从到往向被把让给对与和同随用以由朝顺沿靠经这那哪我你他她它您是都有没不要也还就很再又将正在会可能应该能够可以已经刚刚将要快要须得")

        # 组织地点后缀的通用过滤前缀（匹配前面是"的""了"等介词/助词的，不算组织）
        ORG_LOC_PREFIX_BLACKLIST = {"的", "了", "在", "从", "到", "往", "向", "被", "把", "让", "给", "对", "与", "和", "同", "随", "用", "以", "由", "朝", "顺", "沿", "靠", "经"}

        # ==================== 后缀定义 ====================
        # 组织后缀（去掉了最通用的单字"门""院""山""谷""峰""城""镇""村""洞""林""关""桥"等以避免误匹配，
        # 这些放到地点后缀中更合适。组织后缀保留明确表示组织机构的）
        ORG_SUFFIX = ["宗", "派", "阁", "殿", "教", "盟", "帮", "会", "宫", "楼", "堂", "庄", "轩", "斋", "观", "府", "陵", "窟", "堡", "门"]

        # 功法后缀（去掉过于通用的"法""术""指""腿""拳""掌"等单字，保留多字复合后缀和明确含义的单字）
        SKILL_SUFFIX = ["剑法", "刀法", "枪法", "棍法", "心法", "神通", "奥义", "神功", "秘术", "禁术", "仙术", "阵法", "丹术", "符术", "炼体", "锻体", "天功",
                       "功", "诀", "拳法", "掌法", "腿法", "指法", "剑诀", "刀诀", "拳诀", "掌诀", "法诀"]

        # 地点后缀
        LOC_SUFFIX = ["山", "谷", "峰", "城", "镇", "村", "洞", "穴", "窟", "岛", "河", "湖", "海", "林", "森", "原", "岭", "崖", "渊", "墟", "漠", "泽", "关", "桥", "亭", "殿", "阁", "塔", "台", "宫", "院"]

        # 地点提取中要排除的通用词（看似是地点但实际是日常用语的）
        LOC_STOP_WORDS = {"后面","前面","上面","下面","外面","旁边","里面","里面","之外","之内","之前","之后",
                         "头上","脚下","眼前","身上","背后","面前","手里","怀中","心里","心中",
                         "身上","脸上","眼中","嘴角","心头","胸中","背上","腿上","手上",
                         "河边","海边","路边","门前","窗外","屋外","门外","村口","镇口","洞口",
                         "墙上","地上","树上","床上","桌上","路上","街上","道上","田里","村里"}

        # 实力变化关键词（扩展修为等级体系）
        POWER_KEYWORDS = ["突破", "晋级", "进阶", "渡劫", "悟道", "顿悟", "突破到", "达到", "踏入",
                         "修为提升", "实力大增", "境界突破", "修为突破", "修为达到",
                         "修为跌落", "修为倒退", "实力大减", "境界跌落",
                         "练气", "筑基", "金丹", "元婴", "化神", "炼虚", "合体", "大乘", "渡劫",
                         "真仙", "金仙", "大罗", "圣人", "大帝", "尊者", "王者", "皇者",
                         "仙帝", "仙王", "仙君", "仙尊", "魔神", "剑仙", "大能"]

        # 事件关键词（丰富各类场景模式）
        EVENT_KW = [
            # 战斗/冲突类
            r"与.*(?:一战|交手|对决|激战|厮杀|大战|切磋|比试|争斗|相斗|拼杀|搏杀|死战|血战)",
            r"(?:追杀|追击|围剿|围攻|伏击|偷袭|暗算).*",
            r"(?:被打伤|被重伤|被击杀|被追杀|被围攻|被伏击|被偷袭|被暗算)",
            # 发现/相遇类
            r"(?:发现|找到|遇见|遇到|碰到|结识|认识|重逢|偶遇|撞见).*",
            # 移动/到达类
            r"(?:前往|来到|到达|进入|离开|返回|逃离|潜入|闯入|登上|抵达|降临).*",
            # 获取/失去类
            r"(?:获得|得到|拿到|夺取|抢走|继承|捡到|找到|寻得|夺得|赢得).*",
            r"(?:丢失|遗失|掉落|失去|被夺|被抢|被偷).*",
            # 信息类
            r"(?:得知|获悉|听闻|听说|收到|收到消息|收到传讯|看到|看到).*",
            # 状态变化类
            r"(?:变成|化作|化为|成为|沦为|晋升|突破|觉醒|苏醒|昏迷|醒来).*",
            # 恩怨情感类
            r"(?:报仇|复仇|报恩|感谢|感激|怨恨|仇恨|原谅|宽恕|承诺|发誓|立誓).*",
            # 帮助/救援类
            r"(?:出手|出手相助|出手相救|挺身而出|相助|救援|解救|搭救|营救).*",
            # 信息传递类
            r"(?:说出|告诉|透露|说明|坦言|讲述|交代|坦白|供出|举报).*",
            # 决策/计划类
            r"(?:决定|打算|准备|计划|筹谋|谋划|商议|商量|约定|约好).*",
            # 生死类
            r"(?:被杀|被杀|被杀死|被斩杀|被击杀|被杀|身亡|陨落|战死|牺牲|赴死).*",
        ]

        # 时间模式
        TIME_PATTERNS = [
            r"(?:翌日|次日|第二天|第二日|数日后|几日后|三天后|五天后|七天后|十天后|半月后|一个月后|一年后|多年后)",
            r"(?:片刻后|不多时|不一会儿|很快|马上|立刻|当即|瞬间|转瞬|眨眼间|一炷香后)",
            r"(?:清晨|黎明|拂晓|早上|上午|中午|下午|傍晚|黄昏|入夜|深夜|午夜|子时|午时)",
            r"(?:春|夏|秋|冬)(?:日|季|天)",
            r"(?:三|五|七|九|十|数|百|千)年前",
        ]

        # 物品后缀
        ITEM_SUFFIX = ["剑", "刀", "枪", "戟", "斧", "锤", "弓", "箭", "鞭", "棍", "杖", "铲", "环", "鼎", "炉", "钟", "塔", "珠", "玉", "石", "镜", "盘", "印", "符", "丹", "药", "草", "果", "花", "叶", "绳", "索", "链", "甲", "袍", "衣", "鞋", "冠", "戒", "令", "牌", "册", "卷", "图", "琴", "箫", "笛", "扇"]

        # ==================== 辅助过滤函数 ====================
        def _is_likely_name(word: str) -> bool:
            """判断一个2-4字词是否可能是人名"""
            if word in COMMON_STOP_WORDS:
                return False
            if len(word) < 2 or len(word) > 4:
                return False
            # 不以NAME_BAD_END中的字结尾
            if word[-1] in NAME_BAD_END:
                return False
            # 不以NAME_BAD_START中的字开头
            if word[0] in NAME_BAD_START:
                return False
            # 包含动词性字眼的首字（二字词）
            verb_chars = set("吃喝跑跳走站坐卧躺趴跪爬拉推搬扛挑打抽踢踩踏撞碰摔跌飞翻滚转穿脱戴挂贴插投扔抛甩掷接")
            if len(word) == 2 and word[0] in verb_chars:
                return False
            # 词中所有字都不应全是副词/助词
            bad_all = set("的不了是都在有这人上中大他她它这那和与就也还但而从或以被把对为于向到说没很去出过又给进回拿之下后中里前外间时上内旁东西南北侧面头尾端末处里地边之乎者也可矣焉耳")
            if all(ch in bad_all for ch in word):
                return False
            # 排除所有字都是同一个字
            if len(set(word)) == 1:
                return False
            return True

        def _is_valid_org(org_name: str) -> bool:
            """判断一个组织名是否有效"""
            if len(org_name) < 2:
                return False
            if org_name in COMMON_STOP_WORDS:
                return False
            # 组织名不能太短（如"宗门"是有效的，但"门"本身不算）
            if org_name[1:] in ORG_SUFFIX and len(org_name) == 2:
                # 两个字，第二个是后缀，检查第一个字
                first = org_name[0]
                if first in ORG_LOC_PREFIX_BLACKLIST:
                    return False
                # 排除"宗门"、"门派"这些泛指词
                if org_name in ("宗门", "门派", "门中", "院内", "山中", "谷中", "阵中"):
                    return False
            return True

        def _is_valid_location(loc_name: str) -> bool:
            """判断一个地点名是否有效"""
            if len(loc_name) < 2:
                return False
            if loc_name in LOC_STOP_WORDS:
                return False
            if loc_name in COMMON_STOP_WORDS:
                return False
            # 排除"的X"模式（如"的山"、"的门"）
            if loc_name[0] == "的":
                return False
            # 排除"在X"、"到X"等模式（"在湖边"这类不算专有地名）
            if loc_name[0] in ORG_LOC_PREFIX_BLACKLIST:
                return False
            # 排除泛指词
            if loc_name in ("前面", "后面", "上面", "下面", "外面", "旁边", "里面", "里面", "之前", "之后"):
                return False
            return True

        # ==================== 提取逻辑 ====================
        result = {f: "" for f in ("人物","组织","功法技能","关键事件","地点","时间","关键物品","实力变化","伏笔")}
        sentences = re.split(r'[。！？；\n]', content)

        # ==================== 纯本地规则提取（不调任何外部服务） ====================
        # 注：qwen-service 已从 docker-compose 移除，此处不再调用 HTTP 提取，
        # 全部维度由下方 HanLP/Jieba/正则规则补充生成，速度极快
        qwen_result = {f: "" for f in ("人物","组织","功法技能","关键事件","地点","时间","关键物品","实力变化","伏笔")}

        result = qwen_result.copy()

        # ========== 输出 Qwen 提取结果到日志 ==========
        system_logger.info(f"[记忆体] {chapter_name} Qwen提取明细:")
        for dim_name in ("人物","组织","功法技能","关键事件","地点","时间","关键物品","实力变化","伏笔"):
            dim_val = result.get(dim_name, "")
            system_logger.info(f"[记忆体] >>   {dim_name}: {dim_val}")

        # ========== 补充提取 ==========

        # 1. 人物补充：述宾结构 "XXX说道"
        if not result.get("人物"):
            name_candidates = set()
            speech_verbs = r'(?:说道|问道|答道|喊道|叫道|笑着说|哭着说|怒道|笑道|冷笑道|苦笑道|正色道|低声道|大声道|沉声道|开口道|轻声道|叹道|骂道|惊道|解释道|提醒道|吩咐道|补充道|喝道|断喝道|传音道|喃喃道|自语道|催促道|追问道|呵斥道|训斥道|反驳道|争辩道|嘀咕道|念叨道|感慨道|感叹道|安慰道|安抚道|劝说道|提议道|叮嘱道|嘱咐道|告诫道|警告道|恐吓道)'
            for n in re.findall(rf'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{{2}}){speech_verbs}', content):
                if _is_likely_name(n):
                    name_candidates.add(n)
            for n in re.findall(rf'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{{3}}){speech_verbs}', content):
                if _is_likely_name(n) and n[-1] not in '\u7684\u4e86\u7740\u8fc7\u5427\u5417\u554a\u5462\u54af\u5594\u54c8\u55ef\u545c\u5457\u561b\u54df\u5450\u54a9\u4e5f':
                    name_candidates.add(n)
            if name_candidates:
                result["人物"] = "、".join(sorted(name_candidates, key=lambda x: -len(x))[:10])

        # 2. 组织补充："加入/背叛/脱离+组织" 模式
        if not result.get("组织"):
            orgs = set()
            generic_orgs = {"大殿","前殿","后殿","侧殿","正殿","偏殿","大厅","大堂","正厅","后院","前院","中院","东院","西院","南院","北院","内院","外院"}
            org_action_verbs = r'(?:加入|背叛|脱离|离开|进入|创立|创建|建立|执掌|统领|掌管|管理|坐镇|镇守|守护)'
            for m in re.finditer(rf'{org_action_verbs}([\u4e00-\u9fff]{{2,6}})', content):
                org_name = m.group(1)
                if 2 <= len(org_name) <= 10 and org_name not in COMMON_STOP_WORDS:
                    if org_name not in generic_orgs and _is_valid_org(org_name):
                        orgs.add(org_name)
            orgs = orgs - generic_orgs
            if orgs:
                result["组织"] = "、".join(sorted(orgs)[:10])

        # 3. 功法技能补充：正则规则
        if not result.get("功法技能"):
            skills = set()
            for suffix in SKILL_SUFFIX:
                for m in re.finditer(rf'([\u4e00-\u9fff]{{1,5}}{re.escape(suffix)})', content):
                    skill_name = m.group(1)
                    if skill_name not in COMMON_STOP_WORDS and len(skill_name) >= 2:
                        common_verbs = set("\u4e86\u662f\u628a\u88ab\u8ba9\u5728\u4ece\u5230\u5bf9\u7ed9")
                        if skill_name[-1] not in common_verbs:
                            skills.add(skill_name)
            skill_action_verbs = r'(?:施展|催动|运转|运行|运起|运功|催动|使出|使出|祭出|打出|轰出|斩出|劈出|刺出|拍出|推出)'
            for m in re.finditer(rf'{skill_action_verbs}([\u4e00-\u9fff]{{2,6}})', content):
                skill_name = m.group(1)
                if skill_name not in COMMON_STOP_WORDS and len(skill_name) >= 2:
                    skills.add(skill_name)
            if skills:
                result["功法技能"] = "、".join(sorted(skills)[:10])

        return {"success": True, "data": result}

    @staticmethod
    def refresh_memory_sync(novel_unique_id: str, db: Session = None):
        """同步版：全量刷新（仅在无内容或手动触发时用）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, ChapterService._rebuild_memory_from_files(novel_unique_id, db))
                    future.result(timeout=180)
            else:
                loop.run_until_complete(ChapterService._rebuild_memory_from_files(novel_unique_id, db))
        except RuntimeError:
            asyncio.run(ChapterService._rebuild_memory_from_files(novel_unique_id, db))

    @staticmethod
    def incremental_memory_sync(novel_unique_id: str, db: Session,
                                 chapter_content: str, chapter_name: str,
                                 chapter_summary: str = ""):
        """同步版：增量更新记忆体（发布/编辑章节后调用）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        ChapterService._incremental_memory_update(
                            novel_unique_id, db, chapter_content, chapter_name, chapter_summary
                        )
                    )
                    future.result(timeout=120)
            else:
                loop.run_until_complete(
                    ChapterService._incremental_memory_update(
                        novel_unique_id, db, chapter_content, chapter_name, chapter_summary
                    )
                )
        except RuntimeError:
            asyncio.run(
                ChapterService._incremental_memory_update(
                    novel_unique_id, db, chapter_content, chapter_name, chapter_summary
                )
            )

    @staticmethod
    def create_chapter(db: Session, novel_unique_id: str, user_id: int,
                       chapter_name: str, characters_involved: str = None,
                       organizations: str = None, locations: str = None,
                       skills: str = None, word_count: int = 0,
                       chapter_summary: str = None, created_by: str = None,
                       chapter_number: int = None) -> dict:
        """创建空白章节草稿，保存到数据库和本地文件

        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param user_id: 用户ID
        :param chapter_name: 章节名称
        :param characters_involved: 涉及人物
        :param organizations: 涉及组织
        :param locations: 涉及地点
        :param skills: 涉及技能
        :param word_count: 目标字数
        :param chapter_summary: 章节概要
        :param created_by: 创建者名称
        :param chapter_number: 章节序号，不传则自动计算
        :return: 创建结果（含chapter_unique_id）
        """
        # 同名草稿覆盖：先删旧草稿，避免重复生成导致章节数累加
        existing = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        for ch in existing:
            if not ch.is_published and ch.chapter_name == chapter_name:
                # 删本地文件
                novel_dir_del = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
                for fname in os.listdir(novel_dir_del):
                    if ch.chapter_unique_id in fname:
                        os.remove(os.path.join(novel_dir_del, fname))
                        break
                ChapterDAO.delete(db, ch.chapter_unique_id)
                system_logger.info(f"[创建草稿] 覆盖同名草稿: {chapter_name}")
                break

        chapter_unique_id = uuid.uuid4().hex
        # 自动计算章节序号
        if chapter_number is None:
            existing_count = ChapterDAO.count_by_novel_id(db, novel_unique_id)
            chapter_number = existing_count + 1
        chapter = ChapterDAO.create(
            db,
            novel_unique_id=novel_unique_id,
            user_id=user_id,
            chapter_unique_id=chapter_unique_id,
            chapter_name=chapter_name,
            chapter_number=chapter_number,
            chapter_summary=chapter_summary,
            is_published=0,
            created_by=created_by
        )
        chapter_data = {
            "chapter_unique_id": chapter_unique_id,
            "chapter_name": chapter_name,
            "chapter_number": chapter_number,
            "novel_unique_id": novel_unique_id,
            "chapter_summary": chapter_summary,
            "is_published": 0
        }
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        os.makedirs(novel_dir, exist_ok=True)
        chapter_file = os.path.join(novel_dir, f"{chapter_name}_{chapter_unique_id}.txt")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(chapter_data, ensure_ascii=False, indent=2))
        r = _redis()
        if r:
            r.delete_pattern(f"chapters:novel:{novel_unique_id}:*")
        return success({"chapter_unique_id": chapter_unique_id, "chapter_name": chapter_name},
                       "章节创建成功，已保存到草稿列表")


    # ============================================================
    # 【新增】张力与因果链校验函数
    # ============================================================
    @staticmethod
    def _validate_chapter_tension(content: str, chapter_summary: str = "", 
                                   last_chapter_content: str = "") -> dict:
        """校验章节是否具备足够的叙事张力和因果链条"""
        errors = []
        warnings = []
        
        if not content or len(content) < 100:
            errors.append("章节内容过短，无法校验")
            return {"passed": False, "errors": errors, "warnings": warnings}
        
        # ===== 1. 检查是否有"轻易解决" =====
        easy_words = ["轻松", "轻易", "随手", "一招", "瞬间", "顿时", "马上就", "一下子", "不费吹灰之力"]
        solution_words = ["赢", "胜", "破", "过", "击败", "斩杀", "击退", "化解", "解决", "完成"]
        
        for w in easy_words:
            if w in content:
                idx = content.find(w)
                surrounding = content[max(0, idx-30):min(len(content), idx+30)]
                if any(sw in surrounding for sw in solution_words):
                    warnings.append(f"可能存在'过于轻易'的解决描写: '{w}'，建议检查是否付出了代价")
                    break
        
        # ===== 2. 检查是否有"代价" =====
        cost_words = ["代价", "损失", "受伤", "消耗", "损耗", "欠下", "付出", "牺牲", "裂痕", "暗伤", "吐血", "昏迷", "反噬"]
        has_cost = any(w in content for w in cost_words)
        if not has_cost:
            warnings.append("未检测到明确的'代价'描写，建议检查：问题解决是否让主角付出了代价？")
        
        # ===== 3. 检查是否有"失败/挫折" =====
        fail_words = ["失败", "失手", "落空", "错失", "被击退", "无力", "难以", "艰难", "勉强", "差点", "险些"]
        has_fail = any(w in content for w in fail_words)
        if not has_fail:
            warnings.append("未检测到'失败/挫折'元素，建议检查：主角是否一帆风顺？适当加入挫折可增加张力")
        
        # ===== 4. 检查章节结尾钩子 =====
        last_500 = content[-500:] if len(content) > 500 else content
        hook_words = ["不知", "没发现", "却发现", "殊不知", "却没注意", "然而", "但", "即将", "正在", "暗处", "背后", 
                      "暗中", "异变", "陡变", "变故", "惊变", "不对", "不对劲", "异样", "异常", "未察觉", "尚未", "却不知"]
        has_hook = any(w in last_500 for w in hook_words)
        if not has_hook:
            warnings.append("章节结尾缺乏明显钩子，建议检查：结尾是否留下了让读者想看下一章的悬念？")
        
        # ===== 5. 检查"因果连接词" =====
        cause_words = ["因为", "因此", "所以", "导致", "于是", "便", "从而", "由此", "因而", "以至于", "这才", "总算"]
        has_cause = any(w in content for w in cause_words)
        if not has_cause:
            warnings.append("因果连接词使用较少，建议检查：事件之间是否有明确的因果关系？")
        
        # ===== 6. 检查"升级/变化" =====
        change_words = ["突破", "升级", "提升", "增强", "成长", "变化", "改变", "不同了", "不再是", "已经成为", 
                        "更", "又", "了新的", "全新的"]
        has_change = any(w in content for w in change_words)
        if not has_change:
            warnings.append("未检测到明确的'升级/变化'痕迹，建议检查：本章主角/世界状态是否有实质性变化？")
        
        # ===== 7. 检查与上一章的重复度（简化版） =====
        if last_chapter_content and len(last_chapter_content) > 100:
            # 提取句子进行比较
            sentences1 = re.findall(r'[^。！？]*[。！？]', content[:800])
            sentences2 = re.findall(r'[^。！？]*[。！？]', last_chapter_content[:800])
            
            if sentences1 and sentences2:
                # 计算重复句子比例
                s1_set = set(sentences1[:10])
                s2_set = set(sentences2[:10])
                if s1_set and s2_set:
                    overlap = len(s1_set & s2_set) / len(s1_set)
                    if overlap > 0.5:
                        warnings.append(f"与上一章开篇句子重复度{overlap:.1%}，可能存在重复日常")
        
        # ===== 8. 检查"信息量" =====
        info_words = ["原来", "竟然", "居然", "才发现", "才知道", "终于知道", "揭露", "真相", "秘密", "发现", "原来如此"]
        has_info = any(w in content for w in info_words)
        if not has_info:
            warnings.append("未检测到'新信息揭示'，建议检查：本章是否让读者知道了之前不知道的事？")
        
        # ===== 9. 检查"情感层次" =====
        emotion_words = ["愤怒", "恐惧", "悲伤", "喜悦", "惊喜", "惊讶", "震惊", "震撼", "感动", "羞愧", "愧疚", "挣扎",
                         "心痛", "绝望", "希望", "仇恨", "温柔", "心疼", "不忍", "决绝", "坚定"]
        has_emotion = any(w in content for w in emotion_words)
        if not has_emotion:
            warnings.append("情感词汇较少，建议检查：角色的情感体验是否丰富？")
        
        # ===== 10. 检查是否有"伏笔" =====
        foreshadow_words = ["似乎", "好像", "隐约", "仿佛", "有种感觉", "预感", "直觉", "冥冥", "若有所感"]
        has_foreshadow = any(w in content for w in foreshadow_words)
        if not has_foreshadow:
            warnings.append("未检测到'伏笔'迹象，建议检查：是否埋下了未来可用的线索？")
        
        # ===== 11. 检查主角"主动性" =====
        active_words = ["决定", "主动", "自己", "选择", "迈步", "开口", "出手", "迎上", "反击", "坚持", "固执"]
        has_active = any(w in content for w in active_words)
        if not has_active:
            warnings.append("主角主动性词汇较少，建议检查：主角是否在被动等待？主角要有自己的选择和行为")
        
        # ===== 12. 检查结尾是否"平淡收场" =====
        # 检查结尾最后一句是否以"了"结尾（常表示完成态，缺乏张力）
        last_sentence = content[-100:] if len(content) > 100 else content
        if last_sentence.strip().endswith("了") and len(last_sentence.strip()) > 3:
            warnings.append("结尾以'了'结尾，建议检查：是否太'完整'了？适当留白增加追读感")
        
        # 判断是否通过
        passed = len(errors) == 0
        
        return {
            "passed": passed,
            "errors": errors,
            "warnings": warnings,
            "has_cost": has_cost,
            "has_fail": has_fail,
            "has_hook": has_hook,
            "has_change": has_change,
            "has_info": has_info,
            "has_emotion": has_emotion,
            "has_foreshadow": has_foreshadow,
            "has_active": has_active
        }

    # ============================================================
    # 章节生成（新规格）：三源数量统计 → 一致走生成 / 不一致以txt为准修复
    #   生成输入：章节概要 + 按需检索记忆 + 上一章末尾500字 + 提示词（内容不变）
    # ============================================================

    @staticmethod
    def _int_to_cn(num: int) -> str:
        """阿拉伯数字 → 中文数字（1~999），如 61 → 六十一"""
        cn = "零一二三四五六七八九"
        if num < 10:
            return cn[num]
        if num < 20:
            return "十" + (cn[num % 10] if num % 10 else "")
        if num < 100:
            return cn[num // 10] + "十" + (cn[num % 10] if num % 10 else "")
        return cn[num // 100] + "百" + (ChapterService._int_to_cn(num % 100) if num % 100 else "")

    @staticmethod
    def _normalize_chapter_title(num: int, chapter_name: str) -> str:
        """规范化章节标题：统一为「第{中文数字}章 {标题}」，如 61 + "归墟" → "第六十一章 归墟" """
        base = re.sub(r'^\s*第\s*[\d零一二三四五六七八九十百]+\s*章\s*', '', chapter_name or '')
        base = re.sub(r'^\s*\d+\s*[\.、．\-]\s*', '', base).strip()
        return f"第{ChapterService._int_to_cn(num)}章 {base}" if base else f"第{ChapterService._int_to_cn(num)}章"

    @staticmethod
    async def _call_generation_api(prompt: str, max_tokens: int) -> tuple:
        """调用 DeepSeek 生成正文（只调用一次：不重试、不扩写）。

        生成结果无论字数多少（含低于目标字数）都直接返回，由调用方原样保存。
        接口级错误（认证/余额/参数/网络/超时）直接返回失败信息。
        :param prompt: 生成提示词
        :param max_tokens: 单次调用最大输出 token
        :return: (content, error_message)；content 为空表示调用失败
        """
        # Mock 模式（压测用，config.yaml ai.mock_generate=true）：不调用真实 DeepSeek
        from app.config import get as cfg
        if cfg("ai.mock_generate", False):
            return ("压测用模拟章节内容，仅用于接口压力测试，不包含真实剧情。" * 200), ""
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                # 正文生成用长文本模型（flash 句子过平滑易被 AI 检测标记，改用 v4；其余功能仍用 flash）
                gen_model = deepseek_long_model()
                resp = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {deepseek_api_key()}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": gen_model,
                        "messages": [
                            {"role": "system", "content": EXPANDED_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "thinking": {"type": "disabled"},
                        "max_tokens": max_tokens,
                        "temperature": 0.7,
                        "top_p": 0.92,
                        "frequency_penalty": 0.3,
                        "presence_penalty": 0.4,
                    },
                )
            data = resp.json()
            if resp.status_code != 200:
                err_msg = str(data.get("error", {}).get("message", f"HTTP {resp.status_code}"))
                system_logger.error(f"AI生成 接口错误: HTTP {resp.status_code} {err_msg}")
                return "", f"AI接口错误: {err_msg}"
            if "choices" not in data or not data["choices"]:
                err_msg = str(data.get("error", {}).get("message", "未知错误"))
                system_logger.error(f"AI生成 API错误: {err_msg}")
                return "", err_msg
            text = (data["choices"][0]["message"].get("content") or "").strip()
            finish_reason = data["choices"][0].get("finish_reason", "")
            if not text:
                system_logger.warning(f"AI生成 空正文 finish_reason={finish_reason}")
                return "", "模型返回空内容（可能只输出思考内容）"
            # 只调用一次：无论字数多少都直接返回，不重试、不扩写
            system_logger.info(
                f"AI生成 单次完成 model={gen_model} finish_reason={finish_reason} len={len(text)} "
                f"usage={data.get('usage', {})}")
            return text, ""
        except httpx.TimeoutException:
            system_logger.warning("AI生成 接口调用超时")
            return "", "AI接口调用超时"
        except Exception as e:
            system_logger.warning(f"AI生成 异常: {e}")
            return "", str(e)

    @staticmethod
    async def _rewrite_ai_features(text: str) -> str:
        """内容层 AI 特征超标 → LLM 定向改写（config.yaml ai.text_clean.llm_rewrite=true 启用）。

        程序化清洗管不了比字比较句/台词对仗/"跟X似的"/否定排队（删了伤语义），
        这一步用一次 v4 调用兜底：只改写命中的句子，其余一字不动；
        改写后按行映射回原文 → 复跑程序化清洗 → 复检特征，超标项显著下降。

        :param text: 已过程序化清洗的章节正文
        :return: 改写后的正文（改写失败/无超标时原样返回）
        """
        from app.config import get as cfg
        if not cfg("ai.text_clean.llm_rewrite", False):
            return text
        report = check_ai_features(text)
        if not report:
            return text
        targets = collect_feature_sentences(text)
        if not targets:
            return text
        system_logger.info(f"[章节生成] 内容层特征超标，触发 LLM 定向改写: {report}（{len(targets)}句）")
        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(targets))
        prompt = (
            "你是网文改稿编辑，任务是把句子里的 AI 写作特征改掉，让文字更像人手写的。\n"
            "检测到的特征与改写要求：\n"
            "- 比字比较句（\"比我的大\"\"比我们都旧\"）：改成口语直述（\"大得多，宽一圈\"\"头一个醒的\"），同句避免第二个比较；\n"
            "- \"跟X似的\"比喻：换直述（\"跟砂纸磨过似的\"→\"干得发紧\"）；\n"
            "- 否定排队（\"不知道。不知道。\"）：只留一次，其余删掉或并进叙述；\n"
            "- 台词对仗（相邻两句等长收尾）：拆成错落长度，一句长一句短；\n"
            "- 一问一答剧本式（连续\"问？答。问？\"无停顿）：中间插入动作/反应/环境打断，或把答句并进叙述；\n"
            "- 解释性描写（\"因为A所以B因此C\"式设定解释）：改成人物感受，让读者自己推。\n"
            "- 比喻密度超标（\"像X一样\"\"仿佛X\"\"犹如X\"扎堆）：整段只留 1 处比喻，其余换直述或动作，句式必须错开；\n"
            "- 判断句排比（\"是陈述。\"\"是它在动。\"独立成段）：合并进叙述或改成动作描写，禁止\"是X。\"独立成句；\n"
            "- 推理展开链（\"是陈述。是等了很久很久的语气。\"判断+解释枚举）：只留判断句，删掉后面的解释链，让读者自己推；\n"
            "- 三连否定排比（\"没有恐惧，没有厌恶，只有熟悉感\"）：改单一结论（\"目光压得很平，看过太多遍的那种平\"），删掉前两个否定项；\n"
            "- 半解释骑墙（\"某种更深的东西\"\"说不清的甜腥气\"）：要么说死（\"像铁锈混着烂肉\"），要么不解释留白，禁止\"某种/说不清的\"骑墙；\n"
            "- 书面连词超频（\"不仅X而且Y\"\"既X又Y\"\"与其X不如Y\"）：换成口语承接（\"不但\"→\"不光\"，或直接拆成两句；\"与其…不如\"→\"宁可\"或直述）；\n"
            "- 五感全覆盖（单场景视觉+听觉+嗅觉+触觉+味觉全写）：砍到1主1辅，挑一个主感官详写+一个辅感官一笔带过，其余删掉；\n"
            "- 语义重复强调（\"纹路是一样的。…一样的纹路。\"同一意思拆两句复述）：合并成一句，删掉重复表述；\n"
            "- 句子残缺（\"尖细的、。\"\"湿漉漉的、\"顿号/逗号后直接句号或悬空）：补全残缺内容或删除悬空标点，让句子完整；\n"
            "- 句子粘连（\"涌出来不是渗\"两句无标点直接连）：在两句之间补逗号或句号，让断句清晰；\n"
            "- 顿号形容词链悬空（\"那种没来由的、尖细的、\"以顿号结尾无后续）：删除悬空顿号或补全形容词；\n"
            "- 得字残缺句（\"声音干得。\"\"平得。\"形容词+得+句号）：补全残缺内容（\"干得发紧\"\"平得没有起伏\"），让句子完整；\n"
            "- 单字残缺句（\"又。\"独立成句）：补全动词或并入前后句；\n"
            "- 名词代词粘连（\"心跳他开口了\"两句无标点）：在名词和代词之间补逗号。\n"
            "以下每行是一个需要改写的句子。逐句改写：保持原意、原剧情、原长度（±2字内），"
            "人名地名一律不变。\n"
            "只输出改写后的句子，一行对应一句，不要编号、不要解释、不要原文。\n\n"
            f"{numbered}"
        )
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {deepseek_api_key()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": deepseek_long_model(),
                        "messages": [
                            {"role": "system", "content": "你是一个经验丰富的网文编辑，专门做反 AI 检测改写。"},
                            {"role": "user", "content": prompt},
                        ],
                        "thinking": {"type": "disabled"},
                        "max_tokens": min(int(len("".join(targets)) * 2.5) + 400, 4000),
                        "temperature": 0.7,
                    },
                )
            data = resp.json()
            if resp.status_code != 200 or "choices" not in data or not data["choices"]:
                system_logger.warning(f"[章节生成] 定向改写接口失败: HTTP {resp.status_code}")
                return text
            rewritten = (data["choices"][0]["message"].get("content") or "").strip()
        except Exception as e:
            system_logger.warning(f"[章节生成] 定向改写异常: {e}，保留原文")
            return text
        lines = [ln.strip() for ln in rewritten.splitlines() if ln.strip()]
        new_text = text
        replaced = 0
        for old_s, new_s in zip(targets, lines):
            # 容错：剥掉模型可能带的编号前缀
            new_s = re.sub(r'^\d+[\.、）)]\s*', '', new_s)
            if old_s in new_text and new_s and old_s != new_s:
                new_text = new_text.replace(old_s, new_s, 1)
                replaced += 1
        if replaced == 0:
            system_logger.warning("[章节生成] 定向改写未命中任何句子，保留原文")
            return text
        cleaned, stats = clean_generated_text(new_text)
        if stats:
            system_logger.info(f"[章节生成] 定向改写后复洗: {stats}")
        report2 = check_ai_features(cleaned)
        system_logger.info(f"[章节生成] 定向改写{replaced}句，复检: {'达标' if not report2 else report2}")
        return cleaned

    # ============================================================
    # 章节概要规划：为作品批量生成后续 N 章概要并批量创建草稿
    # ============================================================

    @staticmethod
    async def generate_outline_with_ai(db: Session, novel_unique_id: str, user_id: int,
                                       story_direction: str = "",
                                       chapter_count: int = 5) -> dict:
        """根据作品已有章节概要 + 用户剧情大框，生成后续 N 章概要（不落库）

        生成结果写入 Redis 临时缓存（24小时有效），前端展示缓存概要，
        点击「生成正文」后由生成流程消费，随章节正文一起落库。

        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param user_id: 用户ID
        :param story_direction: 用户输入的后续剧情大框
        :param chapter_count: 要生成的章节数
        :return: success({chapters: [{chapter_name, chapter_summary, chapter_number}], start_chapter_number}, 消息)
        """
        # ---- 1. 校验作品归属 ----
        novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
        if not novel:
            return fail("作品不存在", code=404)
        if novel.author_user_id != user_id:
            return fail("无权操作该作品", code=403)

        # ---- 1.5 剧情大框是唯一剧情边界，必须填写 ----
        if not (story_direction or "").strip():
            return fail("请先填写【后续剧情大框】，概要将以大框为范围生成", code=400)

        # ---- 2. 读取已有章节概要作为前文脉络 ----
        chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        chapters.sort(key=lambda c: c.chapter_number or 0)
        max_num = max((c.chapter_number or 0) for c in chapters) if chapters else 0
        start_num = max_num + 1
        existing_lines = []
        for c in chapters:
            summary = (c.chapter_summary or "").strip()
            if summary:
                existing_lines.append(f"第{c.chapter_number}章《{c.chapter_name}》：{summary}")
        has_existing = bool(existing_lines)
        if has_existing:
            existing_outlines = "\n".join(existing_lines)
            existing_status = "当前作品已有章节概要，任务是在此基础上续写后续章节。"
            consistency_rule = ("严格基于【已有章节概要】和【后续剧情大框】规划，剧情与已有概要因果衔接，"
                                "并沿【故事线】主干推进；【后续剧情大框】是唯一剧情边界，概要不超出大框范围；"
                                "不凭空新增人物、组织、地点、功法、事件，不偏离大纲主线。")
            task_desc = (f"根据作品设定、故事线和已有章节概要，规划接下来从第{start_num}章开始的 {chapter_count} 章概要。"
                         f"每章剧情必须与已有章节概要因果衔接，严格限定在【后续剧情大框】范围内推进，"
                         f"大框未提及的情节一律不写，绝不允许超出大框另起剧情。")
        else:
            existing_outlines = "（暂无已有章节概要，这是新作品的开篇规划）"
            existing_status = "当前作品暂无章节概要，任务是从开篇开始规划章节。"
            consistency_rule = ("严格基于【作品简介】【故事背景】【故事线】设定规划，章节沿故事线关键节点推进，"
                                "不偏离作品设定，不新增与设定冲突的内容。")
            task_desc = (f"根据作品设定和【故事线】，规划从第{start_num}章（开篇）开始的 {chapter_count} 章概要。"
                         f"首章自然引入主角与核心设定，后续章节严格沿故事线关键节点层层推进剧情发展。")

        # ---- 3. 校验章节数量 ----
        if chapter_count < 1:
            chapter_count = 1
        if chapter_count > 15:
            return fail("单次最多生成15章概要", code=400)

        # ---- 4. 组装 prompt 并调用 AI ----
        genres = novel.genre or novel.target_reader or ""
        def _text(v):
            return (v or "").strip() or "（暂无填写）"
        user_prompt = OUTLINE_USER_PROMPT_TEMPLATE.format(
            novel_title=novel.title,
            genres=genres,
            description=_text(novel.description),
            story_background=_text(novel.story_background),
            plot_development=_text(novel.plot_development),
            existing_outlines=existing_outlines,
            story_direction=story_direction.strip() or "（未指定，延续作品设定自然发展）",
            task_desc=task_desc,
            chapter_count=chapter_count,
        )
        system_prompt = OUTLINE_SYSTEM_PROMPT.format(
            existing_status=existing_status,
            consistency_rule=consistency_rule,
            chapter_count=chapter_count,
        )

        outline_text, err = await ChapterService._call_outline_api(system_prompt, user_prompt)
        if not outline_text:
            return fail(f"概要生成失败：{err or 'AI接口无返回'}", code=502)

        # ---- 5. 解析 JSON 数组（不落库，写入 Redis 临时缓存，24小时有效） ----
        outlines = ChapterService._parse_outline_json(outline_text, chapter_count)
        if not outlines:
            system_logger.warning(f"[概要规划] JSON解析失败，原始返回: {outline_text[:500]}")
            return fail("AI返回格式无法解析，请重试", code=502)
        # 截断到需求数量
        outlines = outlines[:chapter_count]

        preview = []
        for i, o in enumerate(outlines):
            name = (o.get("chapter_name") or f"第{start_num + i}章").strip()
            summary = (o.get("chapter_summary") or "").strip()
            preview.append({
                "chapter_name": name,
                "chapter_number": start_num + i,
                "chapter_summary": summary,
            })

        # 合并已有未消费缓存概要（按章节号去重）+ 新生成的概要，写回 Redis（TTL 24h）
        existing = ChapterService._get_outline_cache(novel_unique_id)
        merged = {o.get("chapter_number"): o for o in existing if isinstance(o, dict) and o.get("chapter_number")}
        for o in preview:
            merged[o["chapter_number"]] = o
        cached = [merged[k] for k in sorted(merged.keys())]
        ChapterService._write_outline_cache(novel_unique_id, cached)

        return success({"chapters": cached, "start_chapter_number": start_num},
                       f"已生成{len(preview)}章概要并缓存（24小时内有效，生成正文后自动消耗）")

    # ---- 概要临时缓存（Redis，24h，不落库） ----
    @staticmethod
    def _outline_cache_key(novel_unique_id: str) -> str:
        return f"outline:cache:{novel_unique_id}"

    @staticmethod
    def _get_outline_cache(novel_unique_id: str) -> list:
        """读取作品未消费的概要临时缓存列表"""
        r = _redis()
        if not r:
            return []
        try:
            data = r.get(ChapterService._outline_cache_key(novel_unique_id))
            if isinstance(data, list):
                return [o for o in data if isinstance(o, dict) and o.get("chapter_summary")]
        except Exception:
            pass
        return []

    @staticmethod
    def _write_outline_cache(novel_unique_id: str, outlines: list) -> None:
        """写入概要临时缓存（TTL 24小时）"""
        r = _redis()
        if not r:
            return
        try:
            r.set(ChapterService._outline_cache_key(novel_unique_id),
                  [o for o in outlines if isinstance(o, dict)], ttl=86400)
        except Exception:
            pass

    @staticmethod
    def get_cached_outlines(novel_unique_id: str) -> dict:
        """读取作品未消费的概要临时缓存（供接口/前端展示）"""
        outlines = ChapterService._get_outline_cache(novel_unique_id)
        outlines.sort(key=lambda o: o.get("chapter_number") or 0)
        return success({"chapters": outlines}, f"缓存概要{len(outlines)}条")

    @staticmethod
    def delete_cached_outline(novel_unique_id: str, chapter_number=None) -> dict:
        """删除概要临时缓存：chapter_number 为空则清空整个缓存"""
        r = _redis()
        if not r:
            return fail("缓存服务不可用", code=500)
        key = ChapterService._outline_cache_key(novel_unique_id)
        if chapter_number is None:
            r.delete(key)
            return success({"chapters": []}, "已清空概要缓存")
        outlines = ChapterService._get_outline_cache(novel_unique_id)
        kept = [o for o in outlines if (o.get("chapter_number") or 0) != chapter_number]
        if len(kept) == len(outlines):
            return fail("缓存中不存在该章概要", code=404)
        ChapterService._write_outline_cache(novel_unique_id, kept)
        return success({"chapters": kept}, "已删除该条概要")

    @staticmethod
    def update_cached_outline(novel_unique_id: str, chapter_number: int,
                              chapter_name: str, chapter_summary: str) -> dict:
        """更新概要临时缓存中某章节号的概要内容（章节名/概要）"""
        outlines = ChapterService._get_outline_cache(novel_unique_id)
        target = next((o for o in outlines if (o.get("chapter_number") or 0) == chapter_number), None)
        if target is None:
            return fail("缓存中不存在该章概要", code=404)
        if chapter_name is not None:
            target["chapter_name"] = chapter_name.strip()
        if chapter_summary is not None:
            target["chapter_summary"] = chapter_summary.strip()
        ChapterService._write_outline_cache(novel_unique_id, outlines)
        return success({"chapters": outlines}, "概要已更新")

    @staticmethod
    async def save_outline_chapters(db: Session, novel_unique_id: str, user_id: int,
                                    chapters: list) -> dict:
        """把前端确认的概要批量入库（创建草稿章节）

        :param chapters: [{chapter_name, chapter_summary}]，按顺序入库
        :return: success({chapters: [{chapter_unique_id, chapter_name, chapter_number, chapter_summary}]}, 消息)
        """
        # ---- 1. 校验作品归属 ----
        novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
        if not novel:
            return fail("作品不存在", code=404)
        if novel.author_user_id != user_id:
            return fail("无权操作该作品", code=403)

        if not chapters or not isinstance(chapters, list):
            return fail("缺少要保存的概要数据", code=400)
        chapters = [c for c in chapters if isinstance(c, dict) and (c.get("chapter_name") or c.get("chapter_summary"))]
        if not chapters:
            return fail("没有可保存的概要内容", code=400)

        # ---- 2. 计算起始章节号（从现有最大章号 +1 连续编排） ----
        existing = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        max_num = max((c.chapter_number or 0) for c in existing) if existing else 0
        start_num = max_num + 1

        # ---- 3. 批量创建草稿章节（含概要，正文留空） ----
        created = []
        for i, o in enumerate(chapters):
            name = (o.get("chapter_name") or f"第{start_num + i}章").strip()
            summary = (o.get("chapter_summary") or "").strip()
            chapter_unique_id = uuid.uuid4().hex
            ChapterDAO.create(
                db,
                novel_unique_id=novel_unique_id,
                user_id=user_id,
                chapter_unique_id=chapter_unique_id,
                chapter_name=name,
                chapter_number=start_num + i,
                chapter_summary=summary,
                is_published=0,
                created_by=f"user:{user_id}",
            )
            created.append({
                "chapter_unique_id": chapter_unique_id,
                "chapter_name": name,
                "chapter_number": start_num + i,
                "chapter_summary": summary,
            })

        r = _redis()
        if r:
            r.delete_pattern(f"chapters:novel:{novel_unique_id}:*")
        return success({"chapters": created, "start_chapter_number": start_num},
                       f"已保存{len(created)}章概要并创建为草稿")

    @staticmethod
    async def _call_outline_api(system_prompt: str, user_prompt: str,
                                max_tokens: int = 4000) -> tuple:
        """调用 DeepSeek 生成概要文本；返回 (text, err)。轻量调用，无字数重试逻辑"""
        import asyncio
        last_err = ""
        for attempt in range(1, 3):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        f"{deepseek_base_url()}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {deepseek_api_key()}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": deepseek_model(),
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "thinking": {"type": "disabled"},
                            "max_tokens": max_tokens,
                            "temperature": 0.8,
                            "top_p": 0.9,
                            "frequency_penalty": 0.3,
                            "presence_penalty": 0.2,
                        },
                    )
                data = resp.json()
                if resp.status_code != 200:
                    err_msg = str(data.get("error", {}).get("message", f"HTTP {resp.status_code}"))
                    if resp.status_code in {400, 401, 402, 403, 404}:
                        return "", err_msg
                    last_err = err_msg
                    await asyncio.sleep(1)
                    continue
                text = (data["choices"][0]["message"].get("content") or "").strip()
                if text:
                    return text, ""
                last_err = "模型返回空内容"
            except Exception as e:
                last_err = str(e)
            await asyncio.sleep(1)
        return "", last_err

    @staticmethod
    def _parse_outline_json(text: str, expected_count: int) -> list:
        """从容错文本中解析概要 JSON 数组（多层降级）；失败返回 []"""
        if not text:
            return []

        def _norm_item(d: dict) -> dict | None:
            name = (d.get("chapter_name") or d.get("章节名") or d.get("name") or "").strip()
            summary = (d.get("chapter_summary") or d.get("概要") or d.get("summary") or "").strip()
            return {"chapter_name": name, "chapter_summary": summary} if name and summary else None

        # ===== 1. 基础清洗：去 markdown 代码块 + BOM + 前后空白 =====
        cleaned = text.strip().lstrip("\ufeff")
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        # ===== 2. 提取 JSON 片段 =====
        candidates = []
        # 2a. 截取第一个 [ 到最后一个 ]（数组直接返回）
        s1, e1 = cleaned.find("["), cleaned.rfind("]")
        if s1 != -1 and e1 != -1 and e1 > s1:
            candidates.append(cleaned[s1:e1 + 1])
        # 2b. 如果外层包了 {"chapters": [...]} / {"data": [...]}，挖内层
        for key in ("chapters", "data", "list", "result"):
            m = re.search(rf'"{key}"\s*[:：]\s*(\[.*\])', cleaned, re.S)
            if m:
                candidates.append(m.group(1))
        # 2c. 直接文本本身
        candidates.append(cleaned)

        # ===== 3. 按候选逐次尝试 JSON.parse =====
        last_err = None
        for json_str in candidates:
            if not json_str:
                continue
            # 预处理中文标点：中文引号、中文逗号、中文冒号（仅在 JSON 字符串外层的标点）
            try:
                data = json.loads(json_str)
            except Exception as e1:
                last_err = e1
                # 3a. 修复尾逗号：},]  → }]
                repaired = re.sub(r",\s*([}\]])", r"\1", json_str)
                # 3b. 中文引号 → 英文引号（只处理键值边界的，避免破坏内容）
                repaired = repaired.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
                try:
                    data = json.loads(repaired)
                except Exception as e2:
                    last_err = e2
                    # 3c. 尝试 json.JSONDecoder 的 raw_decode（忽略末尾垃圾）
                    try:
                        decoder = json.JSONDecoder(strict=False)
                        data, _ = decoder.raw_decode(json_str)
                    except Exception as e3:
                        last_err = e3
                        data = None
            if data is None:
                continue
            # 接受 list / dict(含chapters/data/list的包装)
            if isinstance(data, list):
                arr = data
            elif isinstance(data, dict):
                arr = None
                for k in ("chapters", "data", "list", "result"):
                    if isinstance(data.get(k), list):
                        arr = data[k]
                        break
                if arr is None:
                    # 兜底：把 dict 本身当单条
                    arr = [data]
            else:
                continue
            out = []
            for item in arr:
                if isinstance(item, dict):
                    ni = _norm_item(item)
                    if ni:
                        out.append(ni)
            if out:
                return out[:expected_count * 2]

        # ===== 4. 全量正则兜底（逐对象正则抓取，容错 JSON 极度破损）=====
        rows = re.findall(
            r'"(?:chapter_name|章节名|name)"\s*[:：]\s*"([^"]*)"[^}]*"(?:chapter_summary|概要|summary)"\s*[:：]\s*"([^"]*)"',
            text, re.S)
        if not rows:
            rows = re.findall(
                r'"(?:chapter_summary|概要|summary)"\s*[:：]\s*"([^"]*)"[^}]*"(?:chapter_name|章节名|name)"\s*[:：]\s*"([^"]*)"',
                text, re.S)
            rows = [(s, n) for n, s in rows]
        system_logger.warning(
            f"[概要规划] JSON解析降级到正则抓取, 匹配条数={len(rows)}, "
            f"最后一次parse_err={last_err}, 原始返回前300字={text[:300]!r}"
        )
        return [{"chapter_name": n.strip(), "chapter_summary": s.strip()}
                for n, s in rows if n.strip() and s.strip()][:expected_count * 2]

    @staticmethod
    async def generate_with_ai(db, novel_unique_id: str, user_id: int, chapter_name: str,
                               characters_involved: str = "", organizations: str = "",
                               locations: str = "", skills: str = "",
                               word_count: int = 2000, chapter_summary: str = "",
                               created_by: str = "", author_style: str = "",
                               chapter_template: str = "") -> dict:
        """AI 生成新章节（异步任务入口）

        新规格流程：
        1. 三源章节号数量统计（mysql / txt / redis）：
           - 一致 → 走生成路线
           - 不一致 → 以本地 txt 为准自动修复（txt 有 mysql 无 → 补插 mysql；
             txt 有 redis 无 → 读 txt → DeepSeek AI 提取写 redis，并发数=memory_extract_threads）
        2. 生成输入（提示词工程内容不变）：
           - 章节概要
           - 按需检索记忆（ChapterGenService.retrieve_memory 封装方法）
           - 上一章末尾 500 字（ChapterGenService.get_prev_ending 封装方法）
        """
        import uuid
        # ===== 1. 三源数量统计：一致走生成 / 不一致以txt为准自动修复 =====
        counts = ChapterGenService.count_sources(novel_unique_id, db)
        if counts["consistent"]:
            system_logger.info(
                f"[章节生成] 三源一致 MySQL=TXT=Redis={counts['mysql']['count']} → 走生成路线"
            )
        else:
            system_logger.warning(
                f"[章节生成] 三源不一致 MySQL={counts['mysql']['count']} TXT={counts['txt']['count']} "
                f"Redis={counts['redis']['count']} → 以txt为准自动修复后再生成"
            )

        # 修复 + 加载记忆体（内部：以 txt 为准补 mysql 缺失、补 redis 缺失）
        memory_body = await ChapterGenService.repair_and_load_memory(novel_unique_id, db)

        # ===== 2. 章节号分配：优先级 = 填充概要草稿 → 覆盖已有正文草稿(每作品仅一个) → 新建 =====
        mysql_all = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        # 概要草稿：未发布、无正文（word_count=0）、有概要内容 → 生成正文时填充到该章，避免章节号错位
        outline_drafts = [c for c in mysql_all
                          if not c.is_published and not (c.word_count or 0)
                          and (c.chapter_summary or "").strip()]
        # 已有正文草稿：未发布且有正文字数 → 每作品仅保留一个，生成时覆盖最新的那个
        body_drafts = [c for c in mysql_all if not c.is_published and (c.word_count or 0) > 0]
        if outline_drafts:
            next_num = min(c.chapter_number or 0 for c in outline_drafts)
            fill_mode = "outline"
            system_logger.info(f"[章节生成] 存在概要草稿，将填充正文到第{next_num}章")
        elif body_drafts:
            overwrite_target = max(body_drafts, key=lambda c: c.chapter_number or 0)
            next_num = overwrite_target.chapter_number or 0
            fill_mode = "overwrite"
            system_logger.info(f"[章节生成] 每作品仅保留一个草稿，将覆盖旧草稿《{overwrite_target.chapter_name}》(第{next_num}章)")
        else:
            # 修复可能补插了 mysql 缺失章节，因此修复后重新统计再计算，避免与已补插章节号重复
            if not counts["consistent"]:
                counts = ChapterGenService.count_sources(novel_unique_id, db)
            mysql_chapters = counts["mysql"]["chapters"]
            txt_chapters = counts["txt"]["chapters"]
            mysql_max = mysql_chapters[-1]["num"] if mysql_chapters else 0
            txt_max = txt_chapters[-1]["num"] if txt_chapters else 0
            next_num = max(mysql_max, txt_max) + 1
            fill_mode = "new"
        title = ChapterService._normalize_chapter_title(next_num, chapter_name)

        # ===== 3. 按需检索对应章节的记忆（封装方法） =====
        # max_chars=15000 限制注入量：记忆体注入过长（4万+字符）会显著拖慢生成
        # 并导致模型输出坍缩（prompt 越大输出越短），需控制在合理范围
        memory_body = ChapterGenService.retrieve_memory(
            memory_body, chapter_summary, current_chapter_num=next_num, max_chars=15000)

        # ===== 4. 上一章节末尾 500 字（封装方法；生成场景取已发布最后一章） =====
        last_ending, dup_text, _last_name = ChapterGenService.get_prev_ending(db, novel_unique_id)

        # ===== 5. 作品设定 + 提示词组装（提示词工程内容不变） =====
        settings = ChapterService._get_novel_settings(novel_unique_id)
        # 加载角色卡（主角+前几位配角）注入 prompt，解决「疯批不疯/怼神不怼」式人设写崩
        character_cards = ChapterService._load_character_cards(db, novel_unique_id)
        # 未手动选章节模板 → 按作品主角性格自动适配默认模板
        if not chapter_template:
            chapter_template = ChapterService._resolve_default_template(db, novel_unique_id)
            if chapter_template:
                system_logger.info(f"[章节生成] 未手动选模板，按主角性格自动适配: {chapter_template}")
        prompt = ChapterGenService.build_prompt(
            chapter_name=title,
            memory_body=memory_body,
            settings_text=settings.get("content", ""),
            last_chapter_ending=last_ending,
            chapter_summary=chapter_summary,
            word_count=word_count,
            include_combat_meme=True,
            author_style=author_style,
            chapter_template=chapter_template,
            character_cards=character_cards,
            recent_duplicate_text=dup_text,
        )
        system_logger.info(
            f"[章节生成] 请求输入统计: 记忆体={len(memory_body)}字符 | 概要={len(chapter_summary or '')}字 "
            f"| 锚点={len(last_ending or '')}字 | 提示词总长={len(prompt)}字符")

        # ===== 6. 调用 AI 生成（只调用一次，不重试不扩写）+ 后处理截断 =====
        # max_tokens 覆盖目标上限（4000字×4=16000 token），排除 max_tokens 不足导致的提前截断
        gen_max_tokens = max(int(word_count * 4), 16000)
        generated_text, err = await ChapterService._call_generation_api(
            prompt, gen_max_tokens)
        if not generated_text:
            return fail(f"章节生成失败: {err}", code=500)
        system_logger.info(f"[章节生成] max_tokens={gen_max_tokens} 目标字数={word_count}")

        # 概要边界截断（生成内容不得超过概要覆盖的事件范围；自然收尾保留，不砍结尾）
        # _trim_to_summary_boundary 内部已有保护：截断点后残留 ≤500 字视为自然收尾保留全文；
        # 因此直接采用其结果即可——截断后字数少是因为概要本身规模小（prompt 已要求"清单写完即停笔"），
        # 不能因"字数少"再放行概要外超纲内容（历史 bug：第3章概要外新增3329字因截断后<3200被保留）
        if chapter_summary:
            generated_text = ChapterService._trim_to_summary_boundary(generated_text, chapter_summary)
        # 超长上限截断（目标4000字 → 最多约8000字），避免生成超长；
        # 上限放宽到 2.0 倍且不低于 +3000，并按段落/句号边界截断，避免句中硬切导致结尾残缺
        hard_cap = max(int(word_count * 2.0), word_count + 3000)
        if len(generated_text) > hard_cap:
            cut = generated_text[:hard_cap]
            for sep in ("\n\n", "\n", "。", "！", "？"):
                idx = cut.rfind(sep)
                if idx > int(hard_cap * 0.8):
                    cut = cut[:idx + len(sep)]
                    break
            generated_text = cut

        # ===== 6.5 程序化清洗：生成后按代码规则去除 AI 检测统计特征 =====
        # （破折号/冒号/省略号压减、"不是X是Y"压缩、三连排比拆散、明喻换词、均匀长句拆短）
        # 只动标点与高频句式，不删剧情；引号内对话整体保护不改写
        cleaned_text, clean_stats = clean_generated_text(generated_text)
        if clean_stats:
            system_logger.info(f"[章节生成] 程序化清洗 {title}: {clean_stats}")
        generated_text = cleaned_text

        # ===== 6.6 内容层特征超标 → LLM 定向改写（config.yaml ai.text_clean.llm_rewrite=true 启用） =====
        # 比字比较句/台词对仗/"跟X似的"/否定排队程序化删不动，超标时用一次 v4 调用只改超标句
        generated_text = await ChapterService._rewrite_ai_features(generated_text)
        actual_word_count = len(generated_text)

        # ===== 7. 保存：填充概要草稿 / 覆盖旧正文草稿 / 新建草稿；+ TXT 文件 + 清草稿缓存 =====
        from app.models.chapter import Chapter as ChapterModel
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        os.makedirs(novel_dir, exist_ok=True)

        fill_row = None
        if fill_mode == "outline":
            fill_row = next((c for c in mysql_all if c.chapter_number == next_num), None)
        elif fill_mode == "overwrite":
            fill_row = overwrite_target

        if fill_row is not None:
            # 填充概要草稿 / 覆盖旧正文草稿：沿用原 chapter_unique_id（TXT 文件名随之稳定），更新名称/字数
            # 注意：概要不落库，留在 Redis 缓存，发布成功后自动转入 MySQL
            chapter_unique_id = fill_row.chapter_unique_id
            old_name = fill_row.chapter_name
            fill_row.chapter_name = title
            fill_row.word_count = actual_word_count
            db.commit()
            # 章节名变化时清理旧 TXT，避免残留文件
            old_file = os.path.join(novel_dir, f"{old_name}_{chapter_unique_id}.txt")
            new_file = os.path.join(novel_dir, f"{title}_{chapter_unique_id}.txt")
            if old_name and old_file != new_file and os.path.exists(old_file):
                try:
                    os.remove(old_file)
                except Exception:
                    pass
            action_desc = "填充概要草稿" if fill_mode == "outline" else "覆盖旧草稿"
            system_logger.info(f"[章节生成] {title} 已{action_desc}（{actual_word_count}字）→ 草稿箱")
        else:
            chapter_unique_id = uuid.uuid4().hex
            new_chapter = ChapterModel(
                novel_unique_id=novel_unique_id,
                user_id=user_id,
                chapter_unique_id=chapter_unique_id,
                chapter_name=title,
                chapter_number=next_num,
                chapter_summary="",  # 概要不落库：留在 Redis 缓存，发布成功后自动转入 MySQL
                word_count=actual_word_count,
                is_published=0,
                created_by=created_by,
            )
            db.add(new_chapter)
            db.commit()
            db.refresh(new_chapter)

        chapter_file = os.path.join(novel_dir, f"{title}_{chapter_unique_id}.txt")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(generated_text)
        system_logger.info(f"[章节生成] {title} 生成成功（{actual_word_count}字）→ 草稿箱")

        # 概要统一写入 Redis 缓存（发布成功后才落库 MySQL）：
        # 手动填概要生成时缓存无该章条目，这里补写；从缓存概要点生成时条目已存在则跳过
        if chapter_summary:
            try:
                cached = ChapterService._get_outline_cache(novel_unique_id)
                if not any((o.get("chapter_number") or 0) == next_num for o in cached):
                    cached.append({
                        "chapter_name": title,
                        "chapter_number": next_num,
                        "chapter_summary": chapter_summary,
                    })
                    ChapterService._write_outline_cache(novel_unique_id, cached)
            except Exception as e:
                system_logger.warning(f"[章节生成] 写入概要缓存失败: {e}")

        # 清除草稿缓存（保持原行为）
        try:
            r = _redis()
            if r:
                r.delete_pattern(f"chapters:drafts:user:{user_id}")
        except Exception as e:
            system_logger.warning(f"清除缓存失败: {e}")

        return success({
            "chapter_unique_id": chapter_unique_id,
            "chapter_name": title,
            "word_count": actual_word_count,
            "content": generated_text,
        }, f"{title} 章节内容生成成功")

    # ============================================================
    # 辅助方法：文学质量检查
    # ============================================================
    @staticmethod
    def _check_literary_quality(text: str, previous_text: str = "") -> list:
        """检查文学质量，返回问题列表"""
        issues = []
        
        # 检查网文套话
        cliches = [
            "嘴角上扬", "冷哼一声", "眼中闪过", "不以为然", 
            "不由一愣", "心神一震", "倒吸一口凉气", "嘴角抽搐",
            "眉头一皱", "若有所思", "淡淡一笑"
        ]
        for cliche in cliches:
            if cliche in text:
                issues.append(f"使用常见套话：'{cliche}'")
        
        # 检查连续感叹句（网文特征）
        exclamation_count = text.count('！') + text.count('!')
        if exclamation_count > len(text) / 500:  # 每500字超过1个感叹号
            issues.append(f"感叹号使用过多({exclamation_count}个)，建议减少")
        
        # 检查连续长句（超过80字）
        sentences = re.findall(r'[^。！？!?\n]+[。！？!?]', text)
        long_sentences = [s for s in sentences if len(s) > 80]
        if len(long_sentences) > len(sentences) * 0.3:
            issues.append(f"长句过多({len(long_sentences)}/{len(sentences)})，建议长短交替")
        
        # 检查重复段落
        if previous_text:
            duplicates = _detect_duplicate_sentences(text, previous_text)
            if duplicates["has_duplicates"]:
                issues.append(f"与前文有{duplicates['duplicate_count']}处相似内容")
        
        return issues



    @staticmethod
    async def regenerate_with_ai(db: Session, chapter_unique_id: str, user_id: int,
                                 word_count: int = 2000, chapter_summary: str = None,
                                 author_style: str = "", chapter_template: str = "") -> dict:
        """AI 重新生成指定章节（章节编辑）

        流程（与章节生成同一思路，复用公用类方法）：
        1. 计算当前章节号 cur_num，上一章 = cur_num - 1
        2. 上一章内容调用「上一章末尾500字」（get_prev_ending 封装方法，
           current_chapter_num=cur_num 严格取章节号 < cur_num 的最近一章即 cur_num-1）
        3. 生成输入：章节概要 + 按需检索记忆（retrieve_memory 封装方法）
           + 上一章末尾 500 字（提示词工程内容不变 build_prompt）
        """
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
        novel_unique_id = chapter.novel_unique_id
        cur_num = ChapterGenService.chapter_no(chapter)
        if cur_num <= 0:
            return fail("章节号解析失败，无法确定上一章", code=400)
        summary = chapter_summary if chapter_summary is not None else (chapter.chapter_summary or "")
        # 草稿阶段概要不落库（发布成功后才转入 MySQL）：若章节无概要，从 Redis 缓存补充
        if not summary:
            try:
                cached = ChapterService._get_outline_cache(novel_unique_id)
                match = next((o for o in cached if (o.get("chapter_number") or 0) == cur_num), None)
                if match:
                    summary = match.get("chapter_summary") or ""
            except Exception:
                pass

        # ===== 1. 三源修复 + 加载记忆体（以 txt 为准） =====
        memory_body = await ChapterGenService.repair_and_load_memory(novel_unique_id, db)

        # ===== 2. 按需检索对应章节的记忆（排除当前章：current_chapter_num=cur_num） =====
        # max_chars=15000 限制注入量：记忆体注入过长会显著拖慢生成并导致模型输出坍缩
        memory_body = ChapterGenService.retrieve_memory(
            memory_body, summary, current_chapter_num=cur_num, max_chars=15000)

        # ===== 3. 上一章节（cur_num-1）末尾 500 字（封装方法） =====
        last_ending, dup_text, _last_name = ChapterGenService.get_prev_ending(
            db, novel_unique_id, exclude_chapter_id=chapter_unique_id,
            current_chapter_num=cur_num,
        )
        if not last_ending:
            system_logger.warning(
                f"[AI重新生成] 第{cur_num}章 未找到上一章末尾内容（可能是第1章）")

        # ===== 4. 作品设定 + 提示词组装（提示词工程内容不变） =====
        settings = ChapterService._get_novel_settings(novel_unique_id)
        # 加载角色卡（主角+前几位配角）注入 prompt，解决「疯批不疯/怼神不怼」式人设写崩
        character_cards = ChapterService._load_character_cards(db, novel_unique_id)
        # 未手动选章节模板 → 按作品主角性格自动适配默认模板
        if not chapter_template:
            chapter_template = ChapterService._resolve_default_template(db, novel_unique_id)
            if chapter_template:
                system_logger.info(f"[AI重新生成] 未手动选模板，按主角性格自动适配: {chapter_template}")
        prompt = ChapterGenService.build_prompt(
            chapter_name=chapter.chapter_name,
            memory_body=memory_body,
            settings_text=settings.get("content", ""),
            last_chapter_ending=last_ending,
            chapter_summary=summary,
            word_count=word_count,
            include_combat_meme=True,
            author_style=author_style,
            chapter_template=chapter_template,
            character_cards=character_cards,
            recent_duplicate_text=dup_text,
        )
        system_logger.info(
            f"[AI重新生成] 请求输入统计: 记忆体={len(memory_body)}字符 | 概要={len(summary or '')}字 "
            f"| 锚点={len(last_ending or '')}字 | 提示词总长={len(prompt)}字符")

        # ===== 5. 调用 AI 生成（只调用一次，不重试不扩写）+ 后处理截断 =====
        # max_tokens 覆盖目标上限（4000字×4=16000 token），排除 max_tokens 不足导致的提前截断
        gen_max_tokens = max(int(word_count * gen_max_tokens_multiplier()), gen_max_tokens_min())
        generated_text, err = await ChapterService._call_generation_api(
            prompt, gen_max_tokens)
        if not generated_text:
            return fail(f"AI重新生成失败: {err}", code=500)
        system_logger.info(f"[AI重新生成] max_tokens={gen_max_tokens} 目标字数={word_count}")

        # 概要边界截断（同 generate_with_ai：直接采用截断结果，_trim_to_summary_boundary 内部
        # 已有"残留≤500字视为自然收尾保留全文"保护，不再因截断后字数少而放行概要外超纲内容）
        if summary:
            generated_text = ChapterService._trim_to_summary_boundary(generated_text, summary)
        # 超长上限截断（目标字数 → 最多约 hard_cap_ratio 倍），避免生成超长；
        # 上限放宽到 hard_cap_ratio 倍且不低于 +hard_cap_min_extra，并按段落/句号边界截断，避免句中硬切导致结尾残缺
        hard_cap = max(int(word_count * gen_hard_cap_ratio()), word_count + gen_hard_cap_min_extra())
        if len(generated_text) > hard_cap:
            cut = generated_text[:hard_cap]
            for sep in ("\n\n", "\n", "。", "！", "？"):
                idx = cut.rfind(sep)
                if idx > int(hard_cap * 0.8):
                    cut = cut[:idx + len(sep)]
                    break
            generated_text = cut

        # ===== 5.5 程序化清洗：生成后按代码规则去除 AI 检测统计特征 =====
        cleaned_text, clean_stats = clean_generated_text(generated_text)
        if clean_stats:
            system_logger.info(f"[AI重新生成] 程序化清洗: {clean_stats}")
        generated_text = cleaned_text
        actual_word_count = len(generated_text)

        # ===== 6. 保存：覆盖 TXT + 更新 MySQL 字数 =====
        # 注：不再执行生成后增量记忆提取（省去一次等待）。生成输入已通过「按需检索记忆」
        # （retrieve_memory）从 Redis 记忆体注入，足够满足重新生成场景。
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        os.makedirs(novel_dir, exist_ok=True)
        chapter_file = os.path.join(novel_dir, f"{chapter.chapter_name}_{chapter_unique_id}.txt")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(generated_text)
        ChapterDAO.update(db, chapter, word_count=actual_word_count)
        system_logger.info(f"[AI重新生成] 第{cur_num}章 {chapter.chapter_name} 重写成功（{actual_word_count}字）")

        return success({
            "chapter_unique_id": chapter_unique_id,
            "chapter_name": chapter.chapter_name,
            "word_count": actual_word_count,
            "content": generated_text,
        }, f"{chapter.chapter_name} 重新生成成功")

    @staticmethod
    async def continue_with_ai(db: Session, chapter_unique_id: str, word_count: int = 2500) -> dict:
        """AI 续写指定章节：根据作品设定+前文+当前内容，续写本章后续内容"""
        from app.dao.novel_dao import NovelDAO
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)

        # 读取当前章节已有内容：优先从本地 TXT 文件，兜底 DB
        existing_content = ChapterService._read_chapter_content_from_file(
            chapter.novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id
        )

        # 当前章节已写内容（取末尾部分作为上下文）
        context_content = existing_content[-2000:] if len(existing_content) > 2000 else existing_content

        # ===== 记忆体：一次加载 =====
        memory_body = await ChapterService._ensure_memory(chapter.novel_unique_id, db)
        cur_num = ChapterService._chapter_num_from_name(chapter.chapter_name)
        memory_body = ChapterService._retrieve_relevant_memory(
            memory_body, chapter.chapter_summary, current_chapter_num=cur_num)

        # 加载角色卡（主角+前几位配角）注入 prompt，续写也必须符合人设（疯批/怼神不能续写时变乖巧）
        character_cards = ChapterService._load_character_cards(db, chapter.novel_unique_id)
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
            except Exception as e:
                system_logger.warning(f"[AI续写] 角色卡注入异常: {e}")

        # 按主角性格关键词注入对应的疯批/怼神/嘴贱专属规则（与 build_prompt 保持同一套规则）
        chaot_rules = ""
        if isinstance(character_cards, list) and character_cards:
            try:
                pers_all = (character_cards[0].get("personality") or "") + " " + (character_cards[0].get("intro") or "")
                import re as _re
                if _re.search(r'疯|疯批|疯癫|癫|偏执|病娇|嘴贱|反骨|狂', pers_all):
                    chaot_rules = (
                        "【🔴 疯批主角 续写专属规则（本章主角命中疯/疯批/偏执/嘴贱/反骨等关键词，强制）】\n"
                        "1. 台词不配合不礼貌：权威/高位者（神明/观众/上级/审判者/观测员）说话时，至少一次打断/反问/抬杠/答非所问，禁止恭敬回应；\n"
                        "2. 行为反套路：规则让他做的事至少一次不乖乖照做（或问一句「凭什么」），实力不够时做小动作拆台；\n"
                        "3. 怼神/怼观众：若出现神明/观测员/直播间/弹幕/观礼台，至少一次正面怼（反抗/反问/羞辱/无视四选一），示例台词参考：\n"
                        "   「你让我往东我就往东？你谁啊？你说句'请'。」「你们看了三百年不腻？你们站里有食堂吗？」「演？我不是你们的戏子。」「掉就掉呗，你们不还在看吗？」；\n"
                        "4. 直播间互动：设定有弹幕时，至少一次主角对弹幕的反应（吐槽/无视/骂回去/对着空气说风凉话）；\n"
                        "5. 清醒的疯：每一次「疯行」背后都有目的/算计/要保护的人，禁止真的脑子有病；碰到人设规定的底线（如家人/恩人）立刻安静，反差是爽点。")
            except Exception as e:
                system_logger.warning(f"[AI续写] 疯批规则注入异常: {e}")

        prompt = f"""你是在续写这部小说。请根据记忆体和已写内容，续写出高质量、生动、字数充足的小说内容。

{protagonist_block}
{chaot_rules}

【作品记忆体】（必须严格遵循的人物、事件、世界观）
{memory_body}

【本章信息】
章节名称：{chapter.chapter_name}
本章概要：{chapter.chapter_summary or '无'}
当前已写内容（末尾，必须紧密衔接）：
{context_content}

【🔴 续写核心要求 —— 每条都必须做到，违反即作废】

一、字数硬性要求：续写 {word_count} 字左右，绝对不能少于 {max(word_count - 500, 800)} 字！
   - 不是水字数，是每个场景/事件都要展开200-500字的生动描写
   - 一句话带过 = 不及格！每个事件必须有场景入场、动作细节、对话潜台词、五感描写、内心活动

二、人物塑造：对话要有性格辨识度，用动作/神态/心理活动展示人物特征
   - 每句对话配合微表情和肢体语言："没事。"她低头看着手指，尾音颤了一下
   - 嘴里说的≠心里想的，要有潜台词

三、场景环境：用五感（视觉/听觉/嗅觉/触觉/本体觉）渲染场景，让读者有画面感
   - 每个场景至少调动2种感官：火光在墙上跳了一下（视觉）、柴火噼啪响（听觉）、药味很浓（嗅觉）、手指碰到碗壁烫了一下（触觉）

四、情感描写：写出角色内心感受和情绪变化，用自由间接引语融入叙述
   - 不用"他想""她觉得"，直接写内心：碗里的粥凉了。凉了也好。凉的喝下去慢，能多坐一会儿
   - 情绪落到身体：心跳、呼吸、手心、膝盖、嗓子、后背

五、情绪氛围：营造适合当前剧情的氛围，长短句交替控制节奏
   - 紧张场景用短句：他退了一步。又退了一步。背抵住墙。
   - 舒缓场景用长句：她把针线活收进笸箩里，顺手抹了把额头的汗，窗外的日头已经偏了
   - 对话之间穿插动作和环境，不要连续5句以上纯对话

六、剧情张力：有冲突或事件推进，铺垫→冲突→转折→余韵

七、内容丰富：每段都推进剧情或塑造人物，对话与叙述比例约 3:7

八、【🔴 设定至上 —— 续写也必须严格遵守】
   1. 角色独立性：设定中每个角色都是独立个体，禁止合并角色（把 A 的外貌 + B 的能力揉成一个人）。
   2. 禁止发明设定：设定文件中没有的力量体系/概念/术语/组织，一律不得出现在续写中。
   3. 地名/道具名以设定为准：设定里叫什么就写什么，禁止改名；设定列出的随身物品不得遗漏。
   4. 简介承诺必须兑现：简介中描述的关键场景/台词，续写中对应场景必须按简介呈现。
   5. 设定 vs 记忆体冲突时以设定为准。

只输出续写内容，不要重复已有文字，不要加标题。直接从续写的第一句开始。"""

        async with httpx.AsyncClient(timeout=180) as client:
            try:
                response = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {deepseek_api_key()}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": deepseek_long_model(),
                        "messages": [
                            {"role": "system", "content": EXPANDED_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt + "\n\n" + SELF_CHECK_LIST}
                        ],
                        "thinking": {"type": "disabled"},
                        "max_tokens": word_count * 4,
                        "temperature": 0.85,
                        "top_p": 0.92,
                        "frequency_penalty": 0.3,
                        "presence_penalty": 0.4
                    }
                )
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    err_msg = str(data.get("error", {}).get("message", "未知错误"))
                    system_logger.error(f"AI续写失败: {chapter.chapter_name} → {err_msg}")
                    return fail("AI续写失败: " + err_msg, code=500)

                generated_text = data["choices"][0]["message"]["content"]
                if not generated_text or not generated_text.strip():
                    system_logger.error(f"AI续写失败: {chapter.chapter_name} → 模型返回空内容")
                    return fail("AI续写失败: 模型返回空内容，请重试", code=500)
                system_logger.info(f"AI续写成功: {chapter.chapter_name} +{len(generated_text)}字")

                # 程序化清洗续写片段（去 AI 检测统计特征，引号内对话保护不改写）
                cleaned_text, clean_stats = clean_generated_text(generated_text)
                if clean_stats:
                    system_logger.info(f"[AI续写] 程序化清洗: {clean_stats}")
                generated_text = cleaned_text

                # 追加续写内容到文件（兼容）和数据库
                new_content = existing_content + "\n\n" + generated_text
                novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
                os.makedirs(novel_dir, exist_ok=True)
                chapter_file = os.path.join(novel_dir, f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
                with open(chapter_file, "w", encoding="utf-8") as f:
                    f.write(new_content)

                # 更新数据库字数
                ChapterDAO.update(db, chapter, word_count=len(new_content))

                # 清理单章正文缓存，确保章节编辑/列表读取到续写后的最新内容
                rr = _redis()
                if rr:
                    rr.delete(f"chapter:content:{chapter_unique_id}")
                    rr.delete_pattern(f"chapters:novel:{chapter.novel_unique_id}:*")

                await ChapterService._refresh_memory_after_generate(
                    chapter.novel_unique_id, db, new_content, chapter.chapter_name,
                    chapter.chapter_summary or ""
                )

                return success({
                    "chapter_unique_id": chapter_unique_id,
                    "chapter_name": chapter.chapter_name,
                    "continued_text": generated_text,
                    "word_count": len(new_content),
                    "total_word_count": len(new_content)
                }, f"续写成功，新增 {len(generated_text)} 字")

            except httpx.TimeoutException:
                system_logger.error(f"AI续写超时: {chapter.chapter_name}")
                return fail("AI接口调用超时，请重试", code=500)
            except Exception as e:
                system_logger.error(f"AI续写异常: {chapter.chapter_name} → {str(e)}")
                return fail(f"AI续写失败: {str(e)}", code=500)

    @staticmethod
    def get_drafts(db: Session, user_id: int) -> dict:
        """获取用户的所有草稿章节列表，带Redis缓存
        :param db: 数据库会话
        :param user_id: 用户ID
        :return: 草稿章节列表
        """
        cache_key = f"chapters:drafts:user:{user_id}"
        r = _redis()
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)
        chapters = ChapterDAO.get_drafts(db, user_id)
        result = []
        for ch in chapters:
            novel_dir = os.path.join(NOVEL_DATA_PATH, ch.novel_unique_id)
            chapter_file = os.path.join(novel_dir, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
            has_file = os.path.exists(chapter_file)
            # 跳过概要草稿（无正文文件且字数为0），避免草稿列表出现空草稿
            # 概要草稿在「章节概要」Tab 中管理，正文生成填充后再进入草稿列表
            if not has_file and not (ch.word_count or 0):
                continue
            content = ""
            if has_file:
                with open(chapter_file, "r", encoding="utf-8") as f:
                    content = f.read()
            # 优先使用数据库字数字段，否则从文件内容计算
            wc = ch.word_count if ch.word_count else len(content)
            result.append({
                "chapter_unique_id": ch.chapter_unique_id,
                "novel_unique_id": ch.novel_unique_id,
                "chapter_name": ch.chapter_name,
                "chapter_number": ch.chapter_number,
                "word_count": wc,
                "chapter_summary": ch.chapter_summary,
                "content": content,
                "is_published": ch.is_published,
                "created_at": ch.created_at.isoformat() if ch.created_at else None,
                "characters_involved": "",
                "organizations": "",
                "locations": "",
                "skills": "",
                "events": "",
                "time_info": "",
                "key_items": "",
                "power_changes": "",
                "foreshadowing": "",
            })
        if r:
            r.set(cache_key, result)
        return success(result)

    @staticmethod
    def publish_chapter(db: Session, chapter_unique_id: str, content: str = None,
                        characters_involved: str = None, organizations: str = None,
                        locations: str = None, skills: str = None,
                        events: str = None, time_info: str = None,
                        key_items: str = None, power_changes: str = None,
                        foreshadowing: str = None) -> dict:
        """
        发布章节：三阶段保存（txt → MySQL → Redis记忆体）
        每个阶段写入后独立验证，任一失败则回滚已完成的阶段
        """
        from app.dao.interaction_dao import InteractionDAO
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
        if chapter.is_published:
            return fail("该章节已发布", code=400)

        novel_unique_id = chapter.novel_unique_id
        chapter_name = chapter.chapter_name
        # 优先用前端传入的 content，否则从 TXT 文件读取
        if content:
            content_to_save = content
        else:
            content_to_save = ChapterService._read_chapter_content_from_file(
                novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id
            )

        if not content_to_save.strip():
            return fail("章节内容为空，无法发布", code=400)

        chapter_file = None  # 阶段1用

        # ============================================================
        # 阶段1：保存 txt 文件 → 写入后独立验证
        # ============================================================
        t1_ok = False
        try:
            novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
            os.makedirs(novel_dir, exist_ok=True)
            chapter_file = os.path.join(novel_dir, f"{chapter_name}_{chapter_unique_id}.txt")

            with open(chapter_file, "w", encoding="utf-8") as f:
                f.write(content_to_save)
                f.flush()
                os.fsync(f.fileno())  # 强制刷盘

            # ====== 独立验证：重新打开文件读取 ======
            with open(chapter_file, "r", encoding="utf-8") as vf:
                verified_content = vf.read()

            expected_len = len(content_to_save)
            actual_len = len(verified_content)
            file_size = os.path.getsize(chapter_file)

            if file_size > 0 and actual_len == expected_len:
                t1_ok = True
                system_logger.info(f"[发布-验证] ✅ txt保存成功 | 文件={os.path.basename(chapter_file)} | 写入{actual_len}字 | 大小{file_size}字节")
            else:
                system_logger.error(f"[发布-验证] ❌ txt验证失败 | 期望{expected_len}字 | 实际{actual_len}字 | 文件大小{file_size}")
                return fail("章节发布失败：文件保存验证不通过", code=500)
        except Exception as e:
            system_logger.error(f"[发布-验证] ❌ txt阶段异常: {e}")
            return fail(f"章节发布失败：文件保存异常 - {str(e)}", code=500)

        # ============================================================
        # 阶段2：更新 MySQL（is_published + word_count）→ commit → 独立SELECT验证
        # ============================================================
        t2_ok = False
        try:
            actual_word_count = len(content_to_save)
            update_data = {"is_published": 1, "word_count": actual_word_count}

            # 同步更新 ORM 对象，后续回滚场景能拿到正确值
            chapter.word_count = actual_word_count
            chapter.is_published = 1

            ChapterDAO.update(db, chapter, **update_data)
            db.flush()
            db.commit()  # 确保写入磁盘

            # ====== 独立验证：绕过 ORM 直接 SELECT ======
            from sqlalchemy import text
            row = db.execute(
                text("SELECT is_published, word_count FROM chapters WHERE chapter_unique_id = :uid"),
                {"uid": chapter_unique_id}
            ).fetchone()

            if row is None:
                system_logger.error(f"[发布-验证] ❌ MySQL SELECT 查不到记录: {chapter_unique_id}")
                if t1_ok and chapter_file and os.path.exists(chapter_file):
                    os.remove(chapter_file)
                    system_logger.info("[发布-验证] 回滚阶段1: 已删除txt文件")
                db.rollback()
                return fail("章节发布失败：数据库记录丢失", code=500)

            db_is_published = row[0]
            db_word_count = row[1] or 0

            if db_is_published == 1 and db_word_count > 0:
                t2_ok = True
                system_logger.info(f"[发布-验证] ✅ MySQL写入成功 | is_published={db_is_published} | word_count={db_word_count}")
            else:
                system_logger.error(f"[发布-验证] ❌ MySQL验证失败 | is_published={db_is_published} | word_count={db_word_count}")
                if t1_ok and chapter_file and os.path.exists(chapter_file):
                    os.remove(chapter_file)
                    system_logger.info("[发布-验证] 回滚阶段1: 已删除txt文件")
                db.rollback()
                return fail("章节发布失败：数据库更新验证不通过", code=500)
        except Exception as e:
            system_logger.error(f"[发布-验证] ❌ MySQL阶段异常: {e}")
            try:
                db.rollback()
            except:
                pass
            if t1_ok and chapter_file and os.path.exists(chapter_file):
                try: os.remove(chapter_file)
                except: pass
                system_logger.info("[发布-验证] 回滚阶段1: 已删除txt文件")
            return fail(f"章节发布失败：数据库更新异常 - {str(e)}", code=500)

        # ============================================================
        # 阶段3：写入 Redis记忆体 → 读回验证
        # ============================================================
        t3_ok = False
        try:
            # 映射前端字段 → Redis记忆体 维度名（统一配置）
            field_map = get_frontend_to_dimension_map()

            info_data = {}
            if characters_involved: info_data["人物"] = characters_involved
            if organizations: info_data["组织"] = organizations
            if skills: info_data["功法技能"] = skills
            if events: info_data["关键事件"] = events
            if time_info: info_data["时间"] = time_info
            if key_items: info_data["关键物品"] = key_items
            if power_changes: info_data["实力变化"] = power_changes
            if foreshadowing: info_data["伏笔"] = foreshadowing

            # 先记录写入前的各维度长度，用于对比
            pre_lengths = {}
            r = _redis()
            if r and r.ping():
                key = ChapterService._memory_key(novel_unique_id)
                for dim_cat in field_map.values():
                    try:
                        val = r.hget(key, dim_cat)
                        pre_lengths[dim_cat] = len(val) if val else 0
                    except Exception:
                        pre_lengths[dim_cat] = 0

            # 写入（使用自然语言转换，不再存管道符）
            saved_count = 0
            written_dimensions = []
            for front_field, dim_cat in field_map.items():
                raw_val = info_data.get(front_field, "")
                if not raw_val or raw_val == "无":
                    continue
                natural = ChapterService._pipe_to_natural(front_field, raw_val, chapter_name)
                if not natural:
                    continue
                ChapterService._append_to_dimension(novel_unique_id, dim_cat, natural)
                written_dimensions.append(dim_cat)
                saved_count += 1
                system_logger.info(f"[发布-验证] 记忆体写入 {dim_cat}: +{len(natural)}字")

            # ====== 独立验证：逐个维度读回 ======
            if saved_count == 0:
                # 前端未传提取字段 → 后台 AI 提取后写入 Redis
                t3_ok = True
                system_logger.info("[发布-验证] ✅ 记忆体 前端未传提取信息，启动后台 AI 提取")
                try:
                    import threading, asyncio
                    _nid = novel_unique_id
                    _ct = content_to_save
                    _cn = chapter_name
                    _cs = chapter.chapter_summary or ""
                    def _extract_and_save():
                        try:
                            asyncio.run(ChapterService._extract_and_append_to_memory(
                                _nid, _ct, _cn, _cs
                            ))
                        except BaseException as e:
                            system_logger.error(f"[发布-验证] 后台AI提取失败: {e}")
                    threading.Thread(target=_extract_and_save, daemon=True).start()
                except Exception as e:
                    system_logger.error(f"[发布-验证] 启动后台AI提取线程失败: {e}")
            elif not (r and r.ping()):
                system_logger.error("[发布-验证] ❌ Redis 不可用")
            else:
                verify_failures = []
                key = ChapterService._memory_key(novel_unique_id)
                for dim_cat in written_dimensions:
                    try:
                        post_text = r.hget(key, dim_cat) or ""
                        post_len = len(post_text)
                        pre_len = pre_lengths.get(dim_cat, 0)

                        # 验证：数据增长了，且包含本章名称
                        if post_len > pre_len and chapter_name in post_text:
                            system_logger.info(f"[发布-验证] ✅ 记忆体 {dim_cat}: {pre_len}→{post_len}字 (+{post_len-pre_len}) | 含章节名")
                        else:
                            verify_failures.append(dim_cat)
                            system_logger.error(f"[发布-验证] ❌ 记忆体 {dim_cat}: 验证失败 | pre={pre_len} post={post_len} | 含章节名={chapter_name in post_text}")
                    except Exception as ve:
                        verify_failures.append(dim_cat)
                        system_logger.error(f"[发布-验证] ❌ 记忆体 {dim_cat}: 读回异常 {ve}")

                if verify_failures:
                    system_logger.error(f"[发布-验证] ❌ 记忆体 验证失败: {verify_failures}")
                    # 回滚阶段1+2
                    if t1_ok and chapter_file and os.path.exists(chapter_file):
                        try: os.remove(chapter_file)
                        except: pass
                        system_logger.info("[发布-验证] 回滚阶段1: 已删除txt文件")
                    if t2_ok:
                        try:
                            ChapterDAO.update(db, chapter, is_published=0)
                            db.commit()
                            system_logger.info("[发布-验证] 回滚阶段2: MySQL is_published 已回滚为0")
                        except Exception as re:
                            system_logger.error(f"[发布-验证] 回滚阶段2 失败: {re}")
                    return fail(f"章节发布失败：记忆体验证不通过 ({','.join(verify_failures)})", code=500)
                else:
                    t3_ok = True
                    system_logger.info(f"[发布-验证] ✅ Redis记忆体 全部验证通过: {written_dimensions}")

        except Exception as e:
            system_logger.error(f"[发布-验证] ❌ Redis记忆体阶段异常: {e}")
            if t1_ok and chapter_file and os.path.exists(chapter_file):
                try: os.remove(chapter_file)
                except: pass
                system_logger.info("[发布-验证] 回滚阶段1: 已删除txt文件")
            if t2_ok:
                try:
                    ChapterDAO.update(db, chapter, is_published=0)
                    db.commit()
                    system_logger.info("[发布-验证] 回滚阶段2: MySQL is_published 已回滚为0")
                except Exception as re:
                    system_logger.error(f"[发布-验证] 回滚阶段2 失败: {re}")
            return fail(f"章节发布失败：记忆体写入异常 - {str(e)}", code=500)

        # ============================================================
        # 三阶段全部成功 → 发布到作品圈 + 清缓存
        # ============================================================
        interaction_text = f"发布了新章节「{chapter_name}」"
        try:
            from app.dao.interaction_dao import InteractionDAO
            from app.models.interaction import WorkInteraction
            # 幂等：先查是否已有同章节发布评论，有则跳过
            existing_comment = db.query(WorkInteraction).filter(
                WorkInteraction.novel_unique_id == novel_unique_id,
                WorkInteraction.comment_text == interaction_text
            ).first()
            if existing_comment:
                system_logger.info(f"[发布-验证] 作品圈: 同章节已发布过，跳过")
            else:
                InteractionDAO.create_or_update(
                    db,
                    user_id=chapter.user_id,
                    novel_unique_id=novel_unique_id,
                    interactor_id=chapter.user_id,
                    interactor_name=chapter.created_by or "",
                    comment_text=interaction_text
                )
                system_logger.info(f"[发布-验证] ✅ 作品圈同步成功")
        except Exception as e:
            system_logger.warning(f"[发布-验证] ⚠️ 作品圈同步失败（非致命）: {e}")

        r = _redis()
        if r:
            try:
                r.delete_pattern("chapters:*")
                r.delete_pattern("chapter:content:*")
                r.delete_pattern("interactions:*")
            except Exception:
                pass

        # ============================================================
        # 阶段4：概要自动落库（三阶段成功后才触发）
        # 发布成功 = MySQL存在 + txt存在 + Redis记忆体存在，
        # 此时把该章概要从 Redis 缓存自动转入 MySQL chapter_summary，并清理缓存条目
        # ============================================================
        try:
            cached = ChapterService._get_outline_cache(novel_unique_id)
            cached_num = chapter.chapter_number or 0
            match = next((o for o in cached if (o.get("chapter_number") or 0) == cached_num), None)
            # 章节概要为空且缓存有该章概要 → 自动写入 MySQL
            if match and match.get("chapter_summary") and not (chapter.chapter_summary or "").strip():
                chapter.chapter_summary = match["chapter_summary"]
                db.commit()
                system_logger.info(f"[发布-概要落库] ✅ 第{cached_num}章概要已自动写入MySQL chapter_summary")
            # 该章概要已被消费：无论是否写入，从缓存移除该条
            kept = [o for o in cached if (o.get("chapter_number") or 0) != cached_num]
            if len(kept) != len(cached):
                ChapterService._write_outline_cache(novel_unique_id, kept)
                system_logger.info(f"[发布-概要落库] ✅ 已从缓存移除第{cached_num}章概要（剩{len(kept)}条）")
        except Exception as e:
            # 概要落库失败不影响发布主流程，仅记录日志
            system_logger.warning(f"[发布-概要落库] ⚠️ 异常（非致命）: {e}")

        system_logger.info(
            f"[发布-验证] 🎉 三阶段全部验证通过 | "
            f"章节={chapter_name} | "
            f"txt={os.path.getsize(chapter_file) if chapter_file and os.path.exists(chapter_file) else '?'}字节 | "
            f"MySQL=is_published:{t2_ok} | "
            f"Redis记忆体={saved_count if 'saved_count' in dir() else 0}维度"
        )
        return success(
            {"chapter_unique_id": chapter_unique_id, "chapter_name": chapter_name},
            "章节发布成功，已同步到作品圈"
        )

    @staticmethod
    def update_chapter(db: Session, chapter_unique_id: str,
                       chapter_name: str = None, chapter_summary: str = None,
                       content: str = None) -> dict:
        """更新已存在的章节名称、概要或正文
        :param db: 数据库会话
        :param chapter_unique_id: 章节唯一ID
        :param chapter_name: 新章节名称
        :param chapter_summary: 新章节概要
        :param content: 新章节正文（写入 TXT 文件）
        :return: 操作结果
        """
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
        old_chapter_name = chapter.chapter_name  # 更新前的章节名，用于记忆体重建时清除旧条目
        update_data = {}
        if chapter_name is not None:
            old_file = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id,
                                    f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
            update_data["chapter_name"] = chapter_name
            new_file = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id,
                                    f"{chapter_name}_{chapter.chapter_unique_id}.txt")
            if os.path.exists(old_file):
                os.rename(old_file, new_file)
        if chapter_summary is not None:
            update_data["chapter_summary"] = chapter_summary
        ChapterDAO.update(db, chapter, **update_data)
        # 如果传入了正文 content，写入对应 TXT 文件
        if content is not None:
            target_chapter_name = update_data.get("chapter_name", chapter.chapter_name)
            novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
            os.makedirs(novel_dir, exist_ok=True)
            target_file = os.path.join(novel_dir, f"{target_chapter_name}_{chapter.chapter_unique_id}.txt")
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
            # 后台异步重建本章记忆体（编辑内容已变更，旧提取作废；不阻塞保存返回）
            import threading
            threading.Thread(
                target=ChapterService._background_rebuild_memory,
                args=(chapter.novel_unique_id, old_chapter_name, content,
                      target_chapter_name, chapter_summary or ""),
                daemon=True,
            ).start()
        r3 = _redis()
        if r3:
            r3.delete_pattern(f"chapters:*")
            r3.delete_pattern("chapter:content:*")
        return success(None, "章节更新成功")

    @staticmethod
    def _background_rebuild_memory(novel_unique_id: str, old_chapter_name: str,
                                   content: str, chapter_name: str, chapter_summary: str):
        """编辑保存后后台重建章节记忆体：清旧条目 → AI提取新内容 → 写入（不阻塞接口返回）"""
        import asyncio
        try:
            asyncio.run(ChapterService._rebuild_memory_for_chapter(
                novel_unique_id, old_chapter_name, content, chapter_name, chapter_summary))
            system_logger.info(f"[编辑保存] {chapter_name} 记忆体重建完成")
        except Exception as e:
            system_logger.error(f"[编辑保存] 记忆体重建异常: {e}")

    @staticmethod
    def delete_chapter(db: Session, chapter_unique_id: str) -> dict:
        """删除章节及其本地文件和数据库记录，后台重建记忆体
        :param db: 数据库会话
        :param chapter_unique_id: 章节唯一ID
        :return: 操作结果
        """
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)

        novel_unique_id = chapter.novel_unique_id
        chapter_name = chapter.chapter_name

        # 1. 删除本地 txt 文件
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        if os.path.exists(novel_dir):
            for fname in os.listdir(novel_dir):
                if chapter_unique_id in fname:
                    fpath = os.path.join(novel_dir, fname)
                    os.remove(fpath)
                    system_logger.info(f"[删除章节] 已删除本地文件: {fpath}")

                    break

        # 2. 删除数据库记录（先提交，确保成功）
        ChapterDAO.delete(db, chapter_unique_id)

        # 3. 清理 Redis 缓存
        r4 = _redis()
        if r4:
            r4.delete_pattern("chapters:*")
            r4.delete_pattern("chapter:content:*")
            r4.delete_pattern("interactions:*")

        # 4. 从 Redis记忆体 记忆体中定点删除该章节条目
        # 先确定该章节在所有章节中的序号
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        sorted_chapters = sorted(all_chapters, key=lambda c: c.created_at or "")
        chapter_num = None
        for i, ch in enumerate(sorted_chapters):
            if ch.chapter_unique_id == chapter_unique_id:
                chapter_num = i + 1
                break

        for cat in get_memory_category_names():
            if cat == "作品设定":
                continue  # 作品设定不删
            ChapterService._remove_from_dimension(novel_unique_id, cat, chapter_name, chapter_num)

        system_logger.info(f"[删除章节] {chapter_name} 已删除，记忆体定点清除完成")

        return success(None, "章节删除成功，记忆体后台更新中")

    @staticmethod
    def get_novel_chapters(db: Session, novel_unique_id: str) -> dict:
        """获取指定作品的所有章节列表，带Redis缓存（TTL 300秒）

        性能优化：
          1. 逐章内容单独缓存到 Redis，避免冷启动时反复读 TXT 文件
          2. 文件读取使用 ThreadPoolExecutor 并行完成
          3. 总列表缓存 TTL 从 60s 延长至 300s，减少缓存穿透
        """
        cache_key = f"chapters:novel:{novel_unique_id}:all"
        r5 = _redis()
        if r5:
            cached = r5.get(cache_key)
            if cached:
                return success(cached)

        chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _load_content(ch):
            """从 Redis 内容缓存或 TXT 文件读取单章正文"""
            content_ck = f"chapter:content:{ch.chapter_unique_id}"
            if r5:
                cached_content = r5.get(content_ck)
                if cached_content is not None:
                    return ch, cached_content
            novel_dir = os.path.join(NOVEL_DATA_PATH, ch.novel_unique_id)
            chapter_file = os.path.join(novel_dir, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
            content = ""
            if os.path.exists(chapter_file):
                with open(chapter_file, "r", encoding="utf-8") as f:
                    content = f.read()
            if r5 and content:
                r5.set(content_ck, content, ttl=600)
            return ch, content

        content_map = {}
        if chapters:
            with ThreadPoolExecutor(max_workers=min(len(chapters), 10)) as pool:
                futures = {pool.submit(_load_content, ch): ch for ch in chapters}
                for future in as_completed(futures):
                    ch, content = future.result()
                    content_map[ch.id] = content

        result = []
        for ch in chapters:
            content = content_map.get(ch.id, "")
            wc = ch.word_count if ch.word_count else len(content)
            result.append({
                "chapter_unique_id": ch.chapter_unique_id,
                "chapter_name": ch.chapter_name,
                "chapter_number": ch.chapter_number,
                "word_count": wc,
                "chapter_summary": ch.chapter_summary,
                "content": content,
                "is_published": ch.is_published,
                "created_at": ch.created_at.isoformat() if ch.created_at else None
            })

        if r5:
            r5.set(cache_key, result, ttl=300)
        return success(result)

    # ============================================================
    # Worker Handler 方法（供 TaskQueue Worker 线程调用）
    # ============================================================

    @staticmethod
    def _worker_extract_info(task_id: str, task_data: dict) -> dict:
        """Worker handler：AI 提取关键信息（失败直接报错，不降级，避免脏数据污染记忆体）"""
        content = task_data.get("content", "")
        chapter_name = task_data.get("chapter_name", "")
        novel_unique_id = task_data.get("novel_unique_id", "")
        _genre = ChapterService._get_novel_genre(novel_unique_id) if novel_unique_id else ""
        try:
            result = run_async(ChapterService._extract_with_light_prompt, content, _genre)
            if not result.get("success"):
                system_logger.error(f"[Worker-extract] AI提取失败({chapter_name}): {result.get('error', '未知错误')}")
            return result
        except Exception as e:
            system_logger.error(f"[Worker-extract] 异常: {e}")
            return {"success": False, "error": str(e)}


    @staticmethod
    def _worker_generate(task_id: str, task_data: dict) -> dict:
        """Worker handler：AI 生成新章节（三源校验 → 一致生成 / 不一致修复）"""
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            result = run_async(
                ChapterService.generate_with_ai,
                db,
                novel_unique_id=task_data["novel_unique_id"],
                user_id=task_data["user_id"],
                chapter_name=task_data.get("chapter_name", ""),
                characters_involved=task_data.get("characters_involved", ""),
                organizations=task_data.get("organizations", ""),
                locations=task_data.get("locations", ""),
                skills=task_data.get("skills", ""),
                word_count=task_data.get("word_count", 2000),
                chapter_summary=task_data.get("chapter_summary", ""),
                created_by=task_data.get("created_by", ""),
                author_style=task_data.get("author_style", ""),
                chapter_template=task_data.get("chapter_template", ""),
            )
            if result.get("状态码") == 200:
                return {"success": True, "data": result.get("数据")}
            return {"success": False, "error": result.get("消息", "生成失败")}
        except Exception as e:
            system_logger.error(f"[Worker-generate] 异常: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    def _worker_continue(task_id: str, task_data: dict) -> dict:
        """Worker handler：AI 续写章节"""
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            result = run_async(
                ChapterService.continue_with_ai,
                db,
                chapter_unique_id=task_data["chapter_unique_id"],
                word_count=task_data.get("word_count", 2000),
            )
            if result.get("状态码") == 200:
                return {"success": True, "data": result.get("数据")}
            return {"success": False, "error": result.get("消息", "续写失败")}
        except Exception as e:
            system_logger.error(f"[Worker-continue] 异常: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    def _worker_generate_outline(task_id: str, task_data: dict) -> dict:
        """Worker handler：章节概要规划（生成后续 N 章概要并批量创建草稿）"""
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            result = run_async(
                ChapterService.generate_outline_with_ai,
                db,
                novel_unique_id=task_data["novel_unique_id"],
                user_id=task_data["user_id"],
                story_direction=task_data.get("story_direction", ""),
                chapter_count=task_data.get("chapter_count", 5),
            )
            if result.get("状态码") == 200:
                return {"success": True, "data": result.get("数据")}
            return {"success": False, "error": result.get("消息", "概要生成失败")}
        except Exception as e:
            system_logger.error(f"[Worker-outline] 异常: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    def _worker_generate_screenplay(task_id: str, task_data: dict) -> dict:
        """Worker handler：将小说章节转换为剧本格式"""
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            result = run_async(
                ChapterService.generate_screenplay,
                db,
                novel_unique_id=task_data["novel_unique_id"],
                chapter_ids=task_data["chapter_ids"],
            )
            if result.get("状态码") == 200:
                return {"success": True, "data": result.get("数据")}
            return {"success": False, "error": result.get("消息", "生成失败")}
        except Exception as e:
            system_logger.error(f"[Worker-screenplay] 异常: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    async def generate_screenplay(
        db: Session,
        novel_unique_id: str,
        chapter_ids: list,
    ) -> dict:
        """将选定的小说章节内容转换为剧本格式"""
        import traceback

        # 1. 获取作品信息
        novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
        if not novel:
            return fail("作品不存在", code=404)

        novel_title = novel.title or "未知作品"
        novel_settings = ""
        try:
            settings_path = os.path.join(NOVEL_DATA_PATH, novel_unique_id, "作品设定.txt")
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as f:
                    novel_settings = f.read()[:2000]  # 最多取2000字
        except Exception as e:
            system_logger.warning(f"[剧本] 读取作品设定失败: {e}")
            novel_settings = "无"

        # 2. 获取章节内容
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        chapter_map = {c.chapter_unique_id: c for c in all_chapters}
        # 按 chapter_number 排序
        ordered_chapters = []
        for cid in chapter_ids:
            ch = chapter_map.get(cid)
            if ch:
                ordered_chapters.append(ch)
        ordered_chapters.sort(key=lambda c: c.chapter_number or 0)

        if not ordered_chapters:
            return fail("未找到任何章节内容", code=404)

        # 3. 拼接章节内容
        chapters_content_parts = []
        for ch in ordered_chapters:
            # 尝试从 TXT 文件读取（使用标准文件名格式）
            content = ""
            txt_path = os.path.join(NOVEL_DATA_PATH, novel_unique_id, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    pass

            if content:
                chapters_content_parts.append(
                    f"【{ch.chapter_name}】\n{content[:3000]}"
                )

        if not chapters_content_parts:
            return fail("所选章节暂无正文内容", code=404)

        full_chapters_content = "\n\n---\n\n".join(chapters_content_parts)

        # 4. 构建章节范围说明
        first_num = ordered_chapters[0].chapter_number or 1
        last_num = ordered_chapters[-1].chapter_number or len(ordered_chapters)
        chapter_range = f"{_to_chinese(first_num)}-{_to_chinese(last_num)}章"

        # 5. 构建 Prompt
        prompt = GENERATE_SCREENPLAY_DIRECTION.format(
            novel_settings=novel_settings or "未设定",
            chapters_content=full_chapters_content,
            novel_title=novel_title,
        )
        chapter_range_prompt = f"\n\n## 章节范围\n选择的章节：{chapter_range}"
        prompt += chapter_range_prompt

        system_prompt = SCREENPLAY_SYSTEM_PROMPT

        # 6. 调用 AI
        MAX_RETRIES = 2
        generated_text = ""

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    response = await client.post(
                        f"{deepseek_base_url()}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {deepseek_api_key()}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": deepseek_model(),
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": prompt}
                            ],
                            "thinking": {"type": "disabled"},
                            "max_tokens": 16384,
                            "temperature": 0.7,
                            "top_p": 0.9,
                        }
                    )

                    data = response.json()
                    if "choices" not in data or not data["choices"]:
                        err_msg = str(data.get("error", {}).get("message", "未知错误"))
                        system_logger.error(f"[剧本] AI 调用失败: {err_msg}")
                        if attempt < MAX_RETRIES:
                            continue
                        return fail("剧本生成失败: " + err_msg, code=500)

                    generated_text = data["choices"][0]["message"]["content"]

                    if generated_text and len(generated_text) > 100:
                        system_logger.info(f"[剧本] 生成成功 ({len(generated_text)}字)")
                        break
                    else:
                        if attempt < MAX_RETRIES:
                            system_logger.warning(f"[剧本] 重试 {attempt+1}: 内容过短")
                            continue
                        return fail("生成内容过短，请重试", code=500)

            except httpx.TimeoutException:
                system_logger.error("[剧本] AI 调用超时")
                if attempt < MAX_RETRIES:
                    continue
                return fail("AI接口调用超时，请重试", code=500)
            except Exception as e:
                system_logger.error(f"[剧本] AI 调用异常: {e}")
                traceback.print_exc()
                if attempt < MAX_RETRIES:
                    continue
                return fail(f"AI调用异常: {str(e)}", code=500)

        # 7. 返回结果
        return success({
            "novel_title": novel_title,
            "chapter_range": chapter_range,
            "content": generated_text,
            "word_count": len(generated_text),
        }, "剧本生成成功")


# ============================================================
# 独立函数：中文数字转换
# ============================================================
_num_map = list("零一二三四五六七八九十")

def _to_chinese(n: int) -> str:
    """将阿拉伯数字转为中文数字（1→一, 12→十二, 123→一百二十三）"""
    if n <= 10:
        return _num_map[n] if n > 0 else "一"
    elif n < 100:
        s = ""
        if n >= 20:
            s += _num_map[n // 10]
        s += "十"
        if n % 10 != 0:
            s += _num_map[n % 10]
        return s
    elif n < 1000:
        s = _num_map[n // 100] + "百"
        n = n % 100
        if n == 0:
            return s
        if n < 10:
            s += "零" + _num_map[n]
        else:
            s += _num_map[n // 10] + "十"
            if n % 10 != 0:
                s += _num_map[n % 10]
        return s
    else:
        s = _num_map[n // 1000] + "千"
        n = n % 1000
        if n == 0:
            return s
        if n < 100:
            s += "零"
        if n >= 100:
            s += _num_map[n // 100] + "百"
        n = n % 100
        if n == 0:
            return s
        if n < 10:
            s += "零" + _num_map[n]
        else:
            s += _num_map[n // 10] + "十"
            if n % 10 != 0:
                s += _num_map[n % 10]
        return s


# ============================================================
# 独立函数：重复检测
# ============================================================
def _detect_duplicate_sentences(generated_text: str, previous_content: str) -> dict:
    """检测重复句子"""
    if not previous_content:
        return {"has_duplicates": False, "duplicate_count": 0, "duplicate_sentences": []}

    sentences1 = re.findall(r'[^。！？]*[。！？]', generated_text)
    sentences2 = re.findall(r'[^。！？]*[。！？]', previous_content)

    duplicates = []
    s2_set = set(s for s in sentences2[:200] if len(s) > 10)

    for s in sentences1[:100]:
        if len(s) > 10 and s in s2_set:
            duplicates.append({"generated": s, "similarity": 1.0})

    return {
        "has_duplicates": len(duplicates) > 0,
        "duplicate_count": len(duplicates),
        "duplicate_sentences": duplicates[:5]
    }
