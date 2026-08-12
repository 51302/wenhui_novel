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

from app.config import gen_word_count_ratio
from app.dao.chapter_dao import ChapterDAO
from app.prompts.chapter_prompts import (
    GENERATE_CREATIVE_DIRECTION,
    SELF_CHECK_LIST,
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

    @staticmethod
    def _estimate_event_count(chapter_summary: str) -> int:
        """估算章节概要中的事件数量：按句末标点（。！？；）和箭头（→）切分

        概要格式为"剧情发展路线"，用箭头/句号串联关键事件
        （如："主角偷袭天道教宗→夺取镇教之宝→被追杀→坠崖获机缘"）。
        统计结果用于动态计算本章参考字数（事件数×500，随概要规模浮动），
        避免概要事件少时 AI 被固定字数硬下限逼着编造新剧情。
        """
        if not chapter_summary:
            return 0
        parts = re.split(r'[。！？；;→➜\n]', chapter_summary)
        # 过滤纯标点/纯连接词/过短片段（如"偷袭→夺宝→追杀"中2字事件也要计入）
        parts = [p.strip() for p in parts if len(p.strip()) >= 2
                 and not re.match(r'^[的了着呢吗啊吧嗄是还有在就便亦且~]*$', p.strip())]
        return len(parts)

    # ==================== 1. 三源章节数量统计 ====================

    @staticmethod
    def _txt_file_id(fname: str) -> str:
        """从章节 TXT 文件名提取唯一 ID（_<32位hex>.txt），提取失败返回空串"""
        m = re.search(r'_([0-9a-f]{32})\.txt$', fname)
        return m.group(1) if m else ""

    @staticmethod
    def _dedupe_chapters(items, num_fn, id_fn) -> list:
        """章节号去重收集：逐项解析章节号（num_fn），相同章节号只保留第一条
        （id 取 id_fn 结果），按章节号升序。返回 [{"num": 章节号, "id": 唯一ID}, ...]"""
        num_map = {}
        for item in items:
            n = num_fn(item)
            if n > 0:
                num_map.setdefault(n, {"num": n, "id": id_fn(item)})
        return [num_map[k] for k in sorted(num_map)]

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
            # 排除"无正文草稿"（概要规划保存的概要草稿等：未发布且字数为0），
            # 避免纯概要草稿撑高 MySQL 数量，导致三源误判不一致、生成章节号错位
            chapters = ChapterGenService._dedupe_chapters(
                (c for c in all_chapters if c.is_published or (c.word_count or 0)),
                ChapterGenService.chapter_no,
                lambda c: c.chapter_unique_id,
            )
            mysql_info = {"count": len(chapters), "chapters": chapters}
        except Exception as e:
            system_logger.error(f"[三源统计] MySQL 章节统计失败: {e}")

        txt_info = {"count": 0, "chapters": []}
        from app.service.chapter_service import NOVEL_DATA_PATH
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        if os.path.isdir(novel_dir):
            try:
                files = [f for f in os.listdir(novel_dir)
                         if f.endswith(".txt") and "设定" not in f]
                chapters = ChapterGenService._dedupe_chapters(
                    files, ChapterGenService._extract_chapter_num,
                    ChapterGenService._txt_file_id,
                )
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
            # 取上一章末尾 200 字用于跨章查重（跨章重复集中在结尾收束句；
            # 注入过长会让 AI 注意力分散、把查重文本当"风格样本"照抄）
            if full:
                dup_text = full[-200:]
        return ending, dup_text, last_name

    # ==================== 5. Prompt 组装（提示词工程内容固定，不允许变更） ====================

    @staticmethod
    def _append_multi_guides(prompt: str, ids: str, getter) -> str:
        """按逗号分隔的多个 ID（如 "chendong,xiaohei"）逐个注入对应指南，
        ID 存在且指南非空才追加（近因效应注入位置由调用方决定）"""
        for gid in [s.strip() for s in (ids or "").split(",") if s.strip()]:
            guide = getter(gid)
            if guide:
                prompt += "\n\n" + guide
        return prompt

    @staticmethod
    def build_prompt(*, chapter_name: str, memory_body: str, settings_text: str,
                     last_chapter_ending: str, chapter_summary: str, word_count: int,
                     include_combat_meme: bool = True, author_style: str = "",
                     chapter_template: str = "", character_cards: list = None,
                     recent_duplicate_text: str = "") -> str:
        """组装章节生成 Prompt（提示词工程内容不变）

        :param include_combat_meme: 是否包含 战斗写作指南 + 网梗风格指南
            原生成实现包含；若复用方需要精简可传 False。
        :param author_style: 作家风格ID（如 "chendong"），匹配 AUTHOR_STYLES 注入对应章节技法模板
        :param chapter_template: 章节模板ID（如 "crush_fight"），匹配 CHAPTER_TEMPLATES 注入对应写作模板
        :param character_cards: 角色卡列表（novels.characters JSON 原数组）。
            取第一个作为主角，注入 personality/intro/核心台词风格/position 到提示词，
            避免模型不知道主角「疯/嘴贱/怼神」等性格设定写崩人设；
            其余角色若在本章概要涉及也顺带列出作提示。
        """
        # ========== 角色卡 → 人设注入（主角首卡，其余卡若在概要中提及也追加）==========
        # 目的：解决「主角性格写不出来」的根本问题——以前 prompt 只有记忆体但记忆体是逐章提取的
        # 渐进式结果，刚开头前几章几乎没有人设信息，导致主角言行像路人。
        # 这里把 novels.characters 原始设定（用户填的 personality/intro/台词）在 L1 铁律之后立刻注入，
        # 用高权重约束主角人设、台词风格、底线。
        # 字数服从概要：目标字数仅作参考，清单事件写完即停笔，禁止为凑字数编新剧情
        protagonist_guide = ""
        side_roles_guide = ""
        if isinstance(character_cards, list) and character_cards:
            def _clean(x: str) -> str:
                return (x or "").strip().replace("\r\n", "\n")

            def _normalize(card: dict) -> dict:
                return {
                    "name": _clean(card.get("name") or ""),
                    "personality": _clean(card.get("personality") or ""),
                    "intro": _clean(card.get("intro") or ""),
                    "position": _clean(card.get("position") or ""),
                    "core_lines": _clean(card.get("core_lines") or card.get("台词风格") or ""),
                }

            # 主角（约定：characters 第 0 个 = 主角，含 personality 就必须是主角）
            n_main = _normalize(character_cards[0])
            if n_main["name"]:
                lines = []
                lines.append(f"【🔴 主角人设硬约束 —— 违反即整章作废】")
                lines.append(f"主角名：{n_main['name']}")
                if n_main["personality"]:
                    lines.append(f"性格关键词（所有言行必须符合此性格，禁止写相反的人）：{n_main['personality']}")
                if n_main["position"]:
                    lines.append(f"角色定位/全书功能（不得写崩其定位）：{n_main['position']}")
                if n_main["intro"]:
                    # 截取前 1200 字，避免注入过长导致坍缩
                    snippet = n_main["intro"][:1200]
                    lines.append(f"人物卡（外貌/习惯/成长弧线/台词风格/关键动作/底线：以下内容只能更具体，不能违背）：\n{snippet}")
                lines.append("硬约束：本章中主角的每一次开口、每一个选择、每一次情绪变化，都必须符合上述性格与定位；"
                             "禁止写出与性格相反的反应（如嘴贱型忽然恭敬、疯批型忽然乖巧、清醒疯型忽然无脑）。")
                # 弹幕/怼神互动：代码层面判断条件，满足时直接注入强制命令（不给 AI 判断余地）
                # 原先该规则埋在 lang_chaos 模板里 → 改为"若...则..."让 AI 自己判断 → AI 不执行
                # 现在改为代码检测到条件满足时，直接注入"本章必须"的无条件强制命令
                _rebel_kws = ("疯", "疯批", "嘴贱", "反骨", "狂", "贱", "痞", "怼", "骂", "桀骜", "不驯")
                _stream_kws = ("直播间", "弹幕", "观测员", "观众", "神明", "观礼台", "审判者", "直播", "被看", "被观")
                _main_text = (n_main["personality"] + n_main["intro"] + n_main["position"] + n_main["core_lines"]).lower()
                _all_text = (_main_text + (settings_text or "")).lower()
                _is_rebel = any(k in _main_text for k in _rebel_kws)
                _has_stream = any(k in _all_text for k in _stream_kws)
                if _is_rebel and _has_stream:
                    lines.append("【🔴 弹幕/怼神互动铁律 —— 本章强制执行，违反即整章作废】")
                    lines.append("（代码已检测到：主角性格含反叛性特征 + 作品设定含直播/弹幕/观测员元素，以下规则无条件生效）")
                    lines.append("1. 弹幕互动（强制）：本章至少出现 2 次主角对弹幕/观众的正面反应——吐槽、反问、骂回去、对着空气说风凉话、故意无视后补一刀。"
                                 "禁止「弹幕来了就白给」「观众说啥就照做」「全程不看弹幕」「弹幕刷爆主角理都不理」。"
                                 "弹幕越是炸裂/揭秘级场面，主角越要嘴贱接梗，不得沉默走过。"
                                 "写法：弹幕刷出来 → 主角立刻吐槽/怼回去/说风凉话，弹幕和主角对话形成对手戏。")
                    lines.append("2. 怼神/怼观众（强制）：本章至少 1 次正面怼——神明/观众提要求或围观时，直接反抗、反问、羞辱、无视四选一。"
                                 "怼人必须戳对方最在意的点（神爱面子→你也配当神？观众要看剧本→你们看三百年就为了看这个？）。")
                    lines.append("3. 反剧本：观测员/神明给明确剧情任务时，主角要故意反着来或在规则边缘蹦迪——过程必须是他自己选的，不是被按头走的。")
                    lines.append("4. 底线固定：人物卡里标注的「对某人不嘴贱/唯一安静时刻」必须遵守，碰到这条线立刻安静，前后反差感本身就是爽点。")
                protagonist_guide = "\n".join(lines)

            # 其他角色：只把在本章概要或记忆体/设定中可能出现的（取前 5 个）列出来，避免 AI 忘了配角定位
            extras = []
            for c in character_cards[1:6]:
                n = _normalize(c)
                if not n["name"]:
                    continue
                one = f"- {n['name']}"
                bits = []
                if n["position"]:
                    bits.append(n["position"][:120])
                if n["personality"]:
                    bits.append(f"性格：{n['personality'][:200]}")
                if n["intro"]:
                    bits.append(f"关键设定：{n['intro'][:260]}")
                if bits:
                    one += " | " + "；".join(bits)
                extras.append(one)
            if extras:
                side_roles_guide = (
                    "【🔴 配角人设硬约束 —— 违反即整章作废】\n"
                    + "\n".join(extras)
                    + "\n硬约束：每个配角的每一次开口、动作、情绪反应，都必须严格符合其设定性格，禁止写崩。"
                    "\n【台词归属铁律】设定里标注由某角色亲口说出的标志性台词/关键信息/身世揭秘，"
                    "必须由该角色本人在其登场的对应场景亲口说出，禁止借其他角色之口转述、预告、剧透。"
                    "（例：设定写「叉号等了三百年对陈妄说不要跨过去」，这句话就只能由叉号本人说，"
                    "灾厄/解尘/任何其他角色都不得替他转述这句台词，否则叉号后续登场将无戏可演。）"
                    "\n【非人角色话量铁律】设定里标注「不交流/不结盟/丧失人性/只剩本能/人性归零」的角色"
                    "（如灾厄、丧尸、异化体、无意识怪物），禁止长篇连贯独白，不得成为信息输出主力；"
                    "其台词只能是短碎片（1-2 句、多为确认/否认/单字），或以动作/生理反应替代语言。"
                    "大段背景揭秘/前史讲述/动机说明必须交给设定里「清醒、健谈、有动机讲述」的角色，不得塞给非人角色。"
                )

        prompt = GENERATE_CREATIVE_DIRECTION.format(
            memory_body=memory_body or "暂无已写章节记忆体",
            truth_context="无",
            settings_text=settings_text or "未设定",
            context_summary=f"上一章末尾（从这里接着写）：\n{last_chapter_ending}" if last_chapter_ending else "这是第一章，无需承接",
            event_checklist=chapter_summary or "根据前文自然推进剧情",
        )
        # 主角人设硬约束：紧贴「最高优先级」之后注入（权重最高）
        if protagonist_guide:
            prompt += "\n\n" + protagonist_guide
        if side_roles_guide:
            prompt += "\n\n" + side_roles_guide
        # 跨章查重铁律：紧跟人设硬约束注入（高权重区域），只注入上一章结尾，
        # 明确点名禁止复用的句子，防止 AI 把查重文本当"风格样本"照抄
        # （历史问题：注入最近3章各400字过长 + 位置靠后，AI 无视禁令，导致
        #  "左肋的断骨还在疼。右手的金线疤还在发亮。他继续走。"连续3章一字不差）
        if recent_duplicate_text:
            prompt += (
                "\n\n🔴 跨章查重铁律（最高优先级，违反即整章作废）：\n"
                "1. 以下文本是【上一章结尾】，本章【结尾收束句】禁止出现其中任何句子的原句或同义变体"
                "（换词重写也算违规）。\n"
                "2. 禁止连续两章以『身体状态+动作+继续走/离开』式三连句收尾"
                "（如'XX还在疼。XX还在亮。他继续走。'），收尾句式必须与前章完全不同。\n"
                "3. 本章与上一章的任何描写重复不得超过一处，同一意象/动作/比喻全章≤2次且必须有状态变化。\n"
                "【上一章结尾（禁止复用）】：\n" + recent_duplicate_text
            )
        # 提示词工程组装：约束分层/冲突裁决/写作流程）→ 各风格指南 → 字数要求 → 自查清单
        # 字数服从概要：目标字数仅作参考上限，清单事件写完即停笔，禁止为凑字数编新剧情
        # （修复历史问题：原"必须写X~Y字"硬下限 + "字数未达标补充内容"暗示，导致AI在概要事件少时
        #   突破清单边界编造新剧情凑字数。现改为字数服从概要边界，事件少则少写）
        # 动态字数参考（随概要规模浮动）：目标字数 = min(用户目标字数, 概要事件数×500)，
        # 事件少则参考字数自动下浮（如3个事件→1500字，而非硬逼4000字），
        # 避免"字数硬下限 > 概要可写量"时 AI 突破概要边界编造新剧情凑字数
        target_words = word_count
        event_count = ChapterGenService._estimate_event_count(chapter_summary)
        if event_count > 0:
            # 每个事件约展开400-600字，按中值500字/事件估算本章可写量
            event_based = event_count * 500
            if event_based < target_words:
                target_words = event_based
                system_logger.info(
                    f"[章节生成] 概要事件数={event_count}，参考字数由 {word_count} 下浮为 {target_words}"
                )
        max_words = int(word_count * gen_word_count_ratio())
        prompt += f"\n\n🔴 本章字数参考：约 {target_words} 字（上限 {max_words} 字，概要事件少则少写、事件多则多写，不是硬性下限）。"
        # 长文衰减提醒锚点：反 AI 规则在 5000 字后会被模型稀释，此处强制提醒
        # 作用时机：模型读到字数要求时正处于写作起点，提醒会随上下文持续生效到中后段
        prompt += (
            "\n\n🔴【长文防衰减提醒】写到 60% 篇幅后回头自查，违反任一项立即调整后续写法："
            "\n- 比喻密度：全章「像X/跟X似的/仿佛X」不超过 3 处，同一段落不超过 1 处，句式必须错开"
            "\n- 五感扫描：单个场景禁止视觉+听觉+嗅觉+触觉+味觉全覆盖，只聚焦 1-2 个感官，其余不写"
            "\n- 推理枚举：人物推理只给结论+1 依据，禁止「结论+反例①②③」枚举式展开"
            "\n- 判断句排比：禁止连续段落以「是X。」独立成句开头，制造冷峻模板感"
            "\n- 场景扫描：禁止把房间/空间每个角落都描写一遍，只给 1-2 个关键细节+体感"
        )
        # 固定写作指南（GENERATION_FRAMEWORK / 人物具名 / 人味情感 / 认知边界）
        # 已并入 system prompt 恒定核心，战斗/静态/网感按需指南按概要推荐注入
        # （build_generate_system_prompt），不再注入 user 正文——避免双份注入浪费
        # token，且 system 前缀恒定可稳定命中 DeepSeek 前缀缓存
        # 作家风格模板（近因效应：紧贴字数硬性要求之前注入，让"本章技法"离正文指令最近）
        # 支持逗号分隔多选：如 "chendong,xiaohei" 逐个注入，多个风格可叠加
        prompt = ChapterGenService._append_multi_guides(prompt, author_style, get_author_style_guide)
        # 章节写作模板（场景/情绪/字数结构/语言风格，与作家风格可叠加使用）
        # 支持逗号分隔多选：如 "crush_fight,bloody_fight" 逐个注入
        prompt = ChapterGenService._append_multi_guides(prompt, chapter_template, get_chapter_template_guide)

        # 追加字数+边界铁律到 prompt 末尾（最高优先级，近因效应）
        # 核心修复：字数服从概要边界。清单事件写完即停笔，禁止为凑字数编新剧情
        prompt += (
            f"\n\n🔴 字数与边界铁律（最高优先级，违反即整章作废）：\n"
            f"1. 概要=唯一边界：清单事件全写完即可停笔。清单外的新事件/新剧情/新对话/新场景一律不写。\n"
            f"2. 字数是参考值不是硬下限：写完清单事件后字数不足 {target_words} 字，立即用1-2句话自然收尾停笔。"
            f"禁止为凑字数编造新剧情、推进新事件、延长对话、新增场景。\n"
            f"3. 每个事件展开400-600字（环境+动作+对话+内心+感官+情绪六要素交织），把清单事件写饱写透即可。\n"
            f"4. 只有在「清单事件尚未写完」时才允许继续展开；清单事件全部写完=本章结束，立即收尾。\n"
            f"开头第一句就是正文。【绝对禁止复述、换词重写已经写过的内容！】每段必须有新信息，"
            f"不得与前面任何段落内容雷同或语义重复——平台会检测「相邻或跨段大段雷同/复述」并直接驳回签约。"
            f"绝对禁止凑字数或水文字。"
        )
        prompt += f"\n章节标题：「{chapter_name}」"
        # 自查清单放最末尾（近因效应）：停笔前逐项核对
        prompt += "\n\n" + SELF_CHECK_LIST
        return prompt
