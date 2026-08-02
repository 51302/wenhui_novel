"""章节生成公用类：三源数量统计 / AI提取补全 / 按需检索 / 续写锚点 / Prompt组装

提供生成流程可复用的公共能力（当前章节生成/AI重新生成功能已下线，接口保留；
本类方法保留，供后续生成逻辑或其他调用方复用）。
- count_sources：三源章节号数量统计（MySQL / TXT / Redis）
- repair_and_load_memory：三源不一致时 AI 提取 TXT 补 Redis
- retrieve_memory：按章节概要按需检索记忆体
- get_prev_ending：上一章末尾500字续写锚点 + 最近3章查重
- build_prompt：章节生成 Prompt 组装（提示词工程内容固定，不允许改动）
"""
import os
import re

from app.dao.chapter_dao import ChapterDAO
from app.prompts.chapter_prompts import (
    GENERATE_SYSTEM_PROMPT, GENERATE_CREATIVE_DIRECTION,
    GENERATION_FRAMEWORK, SELF_CHECK_LIST, CHARACTER_NAMING_GUIDE,
    EMOTIONAL_WRITING_GUIDE, COMBAT_WRITING_GUIDE, MEME_STYLE_GUIDE,
    DEAI_WRITING_GUIDE, HUMAN_WRITING_GUIDE, COGNITION_BOUNDARY_GUIDE,
    get_author_style_guide, get_chapter_template_guide,
)
from app.utils.logger import system_logger

# 注意：不要在模块顶层 import ChapterService（chapter_service 会 import 本模块，避免循环导入），
# 统一在方法内部延迟导入


class ChapterGenService:
    """章节生成的公共能力封装（只抽取公共方法，不改变提示词内容）"""

    # ==================== 章节号解析 ====================

    CN_UNIT = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
               '六': 6, '七': 7, '八': 8, '九': 9}

    @staticmethod
    def _extract_chapter_num(text: str) -> int:
        """解析文本中的章节号：'第三十一章 xxx' → 31，'第31章' → 31，解析失败返回 -1"""
        if not text:
            return -1
        m = re.search(r'第\s*([一二三四五六七八九十百零\d]+)\s*章', str(text))
        if not m:
            return -1
        num_str = m.group(1)
        if num_str.isdigit():
            return int(num_str)
        # 中文数字：二十=20，二十一=21，一百二十=120
        val = 0
        cur = 0
        for ch in num_str:
            if ch == '十':
                val += cur * 10 if cur > 0 else 10
                cur = 0
            elif ch == '百':
                val += cur * 100 if cur > 0 else 100
                cur = 0
            elif ch in ChapterGenService.CN_UNIT:
                cur = ChapterGenService.CN_UNIT[ch]
        val += cur
        return val if val > 0 else -1

    @staticmethod
    def chapter_no(ch) -> int:
        """章节对象的章节号：优先 chapter_number 字段，旧数据回退解析章节名"""
        if ch is None:
            return -1
        n = getattr(ch, 'chapter_number', 0) or 0
        if n and n > 0:
            return n
        return ChapterGenService._extract_chapter_num(ch.chapter_name)

    @staticmethod
    def chapter_sort_key(ch):
        """按章节号排序（支持阿拉伯/中文数字），解析失败返回 9999"""
        n = ChapterGenService.chapter_no(ch)
        return n if n > 0 else 9999

    # ==================== 1. 三源章节数量统计 ====================

    @staticmethod
    def count_sources(novel_unique_id: str, db) -> dict:
        """统计 MySQL / TXT / Redis 三个数据源的章节号（第一章、第二章…）

        统计口径：以「章节号」为准（解析"第X章"中的 X，中文/阿拉伯数字统一归一化）。
        - mysql: 全部章节（含草稿）→ chapters=[{"num":章节号,"id":chapter_unique_id}]（按章节号去重、升序）+ count
        - txt:   章节 TXT 文件名 → chapters=[{"num":章节号,"id":文件名中的唯一ID}] + count
        - redis: 记忆体 [第X章…] 条目 → chapters=[章节号列表] + count
        - consistent: mysql.count == txt.count == redis.count → 一致可走生成路线
        """
        mysql_info = {"count": 0, "chapters": []}
        try:
            all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id) or []
            num_map = {}
            for c in all_chapters:
                # 排除"无正文草稿"（概要规划保存的概要草稿等：未发布且字数为0），
                # 避免纯概要草稿撑高 MySQL 数量，导致三源误判不一致、生成章节号错位
                if not c.is_published and not (c.word_count or 0):
                    continue
                n = ChapterGenService.chapter_no(c)
                if n > 0:
                    # 章节号去重（不允许重复），保留第一条
                    num_map.setdefault(n, {"num": n, "id": c.chapter_unique_id})
            chapters = [num_map[k] for k in sorted(num_map)]
            mysql_info = {"count": len(chapters), "chapters": chapters}
        except Exception as e:
            system_logger.error(f"[三源统计] MySQL 章节统计失败: {e}")

        txt_info = {"count": 0, "chapters": []}
        from app.service.chapter_service import NOVEL_DATA_PATH
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        if os.path.isdir(novel_dir):
            try:
                num_map = {}
                for f in os.listdir(novel_dir):
                    if not f.endswith(".txt") or "设定" in f:
                        continue
                    n = ChapterGenService._extract_chapter_num(f)
                    if n <= 0:
                        continue
                    m = re.search(r'_([0-9a-f]{32})\.txt$', f)
                    fid = m.group(1) if m else ""
                    num_map.setdefault(n, {"num": n, "id": fid})
                chapters = [num_map[k] for k in sorted(num_map)]
                txt_info = {"count": len(chapters), "chapters": chapters}
            except Exception as e:
                system_logger.error(f"[三源统计] TXT 章节统计失败: {e}")

        redis_info = {"count": 0, "chapters": []}
        try:
            nums = ChapterGenService._redis_chapter_nums(novel_unique_id)
            redis_info = {"count": len(nums), "chapters": sorted(nums)}
        except Exception as e:
            system_logger.error(f"[三源统计] Redis 章节统计失败: {e}")

        consistent = (mysql_info["count"] == txt_info["count"] == redis_info["count"])
        system_logger.info(
            f"[三源统计] novel={novel_unique_id} MySQL={mysql_info['count']} "
            f"TXT={txt_info['count']} Redis={redis_info['count']} "
            f"→ {'一致，可走生成' if consistent else '不一致，需修复'}"
        )
        return {
            "mysql": mysql_info,
            "txt": txt_info,
            "redis": redis_info,
            "consistent": consistent,
        }

    @staticmethod
    def _redis_chapter_nums(novel_unique_id: str) -> set:
        """记忆体 hash 中出现的去重章节号集合（'第31章'与'第三十一章'归一化为 31）"""
        import app.utils.redis_cache as redis_mod
        from app.service.chapter_service import ChapterService
        r = redis_mod.redis_client
        if not r or not r.ping():
            return set()
        key = ChapterService._memory_key(novel_unique_id)
        nums = set()
        try:
            all_data = r.hgetall(key) or {}
        except Exception as e:
            system_logger.error(f"[三源统计] Redis 读取失败: {e}")
            return set()
        for _, val in all_data.items():
            if not val:
                continue
            # 条目格式：[第三十一章 初步了解仙界] 内容 / [第31章] 1. xxx
            for m in re.finditer(r'\[(第[^]]*章[^]]*)\]', val):
                n = ChapterGenService._extract_chapter_num(m.group(1))
                if n > 0:
                    nums.add(n)
        return nums

    # ==================== 2. 三源一致性校验 + AI 提取补全 ====================

    @staticmethod
    async def repair_and_load_memory(novel_unique_id: str, db, current_chapter_num: int = 1) -> str:
        """三源校验并加载记忆体（生成前调用）

        - 逐章检查 MySQL 记录 / Redis 条目
        - 缺失章节：读取对应 TXT 内容 → DeepSeek AI 提取维度信息 → 写入 Redis 补全
        - 返回全量记忆体文本

        说明：这是"不一致 → AI 提取 TXT 补全 Redis"的实现主体，
        内部委托 ChapterService._ensure_memory_chain（保持原逻辑与质量不变）。
        """
        from app.service.chapter_service import ChapterService
        return await ChapterService._ensure_memory_chain(novel_unique_id, db, current_chapter_num)

    # ==================== 3. 按需检索记忆体 ====================

    @staticmethod
    def retrieve_memory(memory_body: str, summary: str,
                        current_chapter_num: int = None, max_chars: int = None) -> str:
        """按需检索注入：从全量记忆体检索与本章概要相关的条目注入生成 prompt"""
        from app.service.chapter_service import ChapterService
        return ChapterService._retrieve_relevant_memory(
            memory_body, summary, max_chars=max_chars, current_chapter_num=current_chapter_num
        )

    # ==================== 4. 上一章末尾500字 + 最近3章（查重） ====================

    @staticmethod
    def get_prev_ending(db, novel_unique_id: str, exclude_chapter_id: str = None,
                        current_chapter_num: int = None):
        """获取续写锚点与查重文本

        :param current_chapter_num: 当前章节号。传入时取「章节号 < 当前章号」的最近一章
            （AI 重新生成场景：编辑第45章 → 上一章取第44章）；
            不传时取已发布最后一章（新章节生成场景）。
        :return: (last_chapter_ending_500, recent3_for_duplicate, last_chapter_name)
        - last_chapter_ending_500: 上一章末尾 500 字（从这里接着写）
        - recent3_for_duplicate:   上一章（含）往前最近 3 章全文拼接（查重检测用）
        - last_chapter_name:       上一章章节名（日志用）
        """
        from app.service.chapter_service import ChapterService
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id) or []
        published = [
            c for c in all_chapters if c.is_published
            and (exclude_chapter_id is None or c.chapter_unique_id != exclude_chapter_id)
        ]
        if current_chapter_num is not None:
            # 严格取「章节号 < 当前章号」的章节（编辑第45章 → 上一章是第44章）
            published = [
                c for c in published
                if 0 < ChapterGenService.chapter_no(c) < current_chapter_num
            ]
        published.sort(key=ChapterGenService.chapter_sort_key)

        ending = ""
        dup_text = ""
        last_name = ""
        if published:
            last = published[-1]
            last_name = last.chapter_name
            system_logger.info(f"[章节生成] 续写锚点：基于已发布最后一章 [{last_name}]")
            full = ChapterService._read_chapter_content_from_file(
                novel_unique_id, last.chapter_name, last.chapter_unique_id
            )
            if full:
                ending = full[-500:]
                system_logger.info(f"[章节生成] 续写锚点：上一章末尾500字（开头: {ending[:80]}...）")
            # 取最近 3 章用于去重检测
            recent = published[-3:] if len(published) >= 3 else published
            parts = []
            for ch in recent:
                content = ChapterService._read_chapter_content_from_file(
                    novel_unique_id, ch.chapter_name, ch.chapter_unique_id
                )
                if content:
                    parts.append(content)
            dup_text = "\n".join(parts)
        return ending, dup_text, last_name

    # ==================== 5. Prompt 组装（提示词工程内容固定，不允许变更） ====================

    @staticmethod
    def build_prompt(*, chapter_name: str, memory_body: str, settings_text: str,
                     last_chapter_ending: str, chapter_summary: str, word_count: int,
                     include_combat_meme: bool = True, author_style: str = "",
                     chapter_template: str = "") -> str:
        """组装章节生成 Prompt（提示词工程内容不变）

        :param include_combat_meme: 是否包含 战斗写作指南 + 网梗风格指南
            原生成实现包含；若复用方需要精简可传 False。
        :param author_style: 作家风格ID（如 "chendong"），匹配 AUTHOR_STYLES 注入对应章节技法模板
        :param chapter_template: 章节模板ID（如 "crush_fight"），匹配 CHAPTER_TEMPLATES 注入对应写作模板
        """
        # 章节概要 → 事件清单（给 AI 的硬边界）
        summary_narrative = ""
        if chapter_summary:
            sentences = re.split(r'[，,。.！!？?；;]', chapter_summary)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
            if sentences:
                summary_narrative = "；".join(sentences) + "。"

        prompt = GENERATE_CREATIVE_DIRECTION.format(
            memory_body=memory_body or "暂无已写章节记忆体",
            truth_context="无",
            settings_text=settings_text or "未设定",
            context_summary=f"上一章末尾（从这里接着写）：\n{last_chapter_ending}" if last_chapter_ending else "这是第一章，无需承接",
            event_checklist=chapter_summary or "根据前文自然推进剧情",
            summary_narrative=summary_narrative or "根据前文自然推进剧情",
        )
        # 提示词工程组装：约束分层/冲突裁决/写作流程）→ 各风格指南 → 字数要求 → 自查清单
        # 开头先强调字数目标（首尾双强调，防止模型过早停笔）
        # 字数区间=目标~目标*1.2（默认2500 → 2500~3000字），与后端硬截断上限一致，
        # 让模型在区间内自然收尾，避免写超后被截断破坏结尾
        min_words = word_count
        max_words = int(word_count * 1.2)
        prompt += f"\n\n🔴 本章目标字数：{min_words}~{max_words} 字。"
        prompt += "\n\n" + GENERATION_FRAMEWORK
        # 人物具名规则紧贴 L1 生死线：新出场角色必须有名有姓，组织/事件必须带出人名
        prompt += "\n\n" + CHARACTER_NAMING_GUIDE
        prompt += "\n\n" + EMOTIONAL_WRITING_GUIDE
        prompt += "\n\n" + DEAI_WRITING_GUIDE
        prompt += "\n\n" + HUMAN_WRITING_GUIDE
        if include_combat_meme:
            prompt += "\n\n" + COMBAT_WRITING_GUIDE
        prompt += "\n\n" + COGNITION_BOUNDARY_GUIDE
        # 作家风格模板（近因效应：紧贴字数硬性要求之前注入，让"本章技法"离正文指令最近）
        author_guide = get_author_style_guide(author_style)
        if author_guide:
            prompt += "\n\n" + author_guide
        # 章节写作模板（场景/情绪/字数结构/语言风格，与作家风格可叠加使用）
        template_guide = get_chapter_template_guide(chapter_template)
        if template_guide:
            prompt += "\n\n" + template_guide

        # 追加字数指令到 prompt 末尾（硬性要求）：目标 word_count ~ word_count*1.2 字
        # （默认2500 → 2500~3000字：下限=目标字数，保证重试阈值 word_count 之上还有余量）
        prompt += f"\n\n🔴 字数硬性要求：本章必须写 {min_words}~{max_words} 字。每个事件至少展开400-600字的生动描写！开头第一句就是正文，事件全部写完但字数未达标时继续在已写事件内展开（环境/动作/对话/内心/情绪），直到写满目标字数才允许收尾。绝对禁止凑字数或水文字，但每个事件必须写饱写透！"
        prompt += f"\n章节标题：「{chapter_name}」"
        # 自查清单放最末尾（近因效应）：停笔前逐项核对
        prompt += "\n\n" + SELF_CHECK_LIST
        return prompt
