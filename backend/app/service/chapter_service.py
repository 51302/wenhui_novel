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
from app.utils.chroma_client import chroma_memory
from app.service.es_service import es_service
from app.config import deepseek_api_key, deepseek_base_url, deepseek_model
from app.utils.logger import system_logger
from app.prompts.chapter_prompts import (
    LIGHT_EXTRACT_PROMPT,
    GENERATE_CREATIVE_DIRECTION, GENERATE_WRITING_EXAMPLES, GENERATE_CREATIVE_BOUNDARIES,
    GENERATE_SYSTEM_PROMPT, GENERATE_CHAPTER_SETTING,
    REGENERATE_PROMPT, REGENERATE_SYSTEM_PROMPT,
    CONTINUE_PROMPT, CONTINUE_SYSTEM_PROMPT,
    EMOTIONAL_WRITING_GUIDE,
)

NOVEL_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "novel_structure_data")
os.makedirs(NOVEL_DATA_PATH, exist_ok=True)


def _redis():
    """获取Redis客户端实例"""
    return redis_mod.redis_client


class ChapterService:

    @staticmethod
    def _get_novel_settings(novel_unique_id: str) -> dict:
        """读取作品设定文件内容
        :param novel_unique_id: 作品唯一ID
        :return: 设定内容字典（含content和path）
        """
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        settings_file = os.path.join(novel_dir, "作品设定.txt")
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                return {"content": f.read(), "path": settings_file}
        return {"content": "", "path": ""}

    # ==================== 记忆体系统（AI提取关键信息 → 向量数据库） ====================

    @staticmethod
    def _ensure_chroma():
        """懒加载：如果 chroma_memory 未初始化，自动创建"""
        global chroma_memory
        if chroma_memory is not None:
            return True
        try:
            from app.utils.chroma_client import ChromaMemoryStore
            persist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vector_db_data")
            chroma_memory = ChromaMemoryStore(
                persist_path=persist_path,
                collection_name="novel_memory"
            )
            import app.utils.chroma_client as mod_chroma
            mod_chroma.chroma_memory = chroma_memory
            system_logger.info("[记忆体] ChromaDB 懒加载成功")

            return True
        except Exception as e:
            system_logger.error(f"[记忆体] ChromaDB 初始化失败: {e}")

            return False

    # ----------------------------------------------------------------
    #  记忆体存储：按维度拆分存入 ChromaDB，检索时按需合并
    # ----------------------------------------------------------------
    _MEMORY_CATEGORIES = [
        "作品设定",
        "人物", "组织势力", "功法技能法宝", "关键事件",
        "地点", "时间线", "人物关系", "伏笔悬念", "实力变化", "关键物品"
    ]

    _CATEGORY_ALIASES = {"组织势力": "组织势力", "功法技能法宝": "功法技能法宝",
                          "关键事件": "关键事件", "人物关系": "人物关系",
                          "伏笔悬念": "伏笔悬念", "实力变化": "实力变化", "关键物品": "关键物品"}

    @staticmethod
    def _load_memory(novel_unique_id: str) -> str:
        """从向量数据库加载所有维度记忆体并合并"""
        if not ChapterService._ensure_chroma():
            return ""
        parts = []
        for cat in ChapterService._MEMORY_CATEGORIES:
            doc_id = f"memory:{novel_unique_id}:{cat}"
            try:
                results = chroma_memory.collection.get(ids=[doc_id])
                if results and results["documents"] and results["documents"][0]:
                    parts.append(f"【{cat}】\n{results['documents'][0]}")
            except Exception:
                pass
        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _save_memory(novel_unique_id: str, memory_text: str):
        """按维度拆分保存记忆体到向量数据库"""
        if not ChapterService._ensure_chroma():
            return
        # 解析 AI 输出的记忆体文本，按【XX】分割
        import re
        sections = re.split(r'\n(?=【)', memory_text)
        cat_map = {}
        current_cat = "概览"
        for sec in sections:
            m = re.match(r'【(.+?)】\s*\n?(.*)', sec, re.DOTALL)
            if m:
                current_cat = m.group(1)
                content = m.group(2).strip()
                if content and content != "无新增":
                    cat_map[current_cat] = content
            else:
                if current_cat not in cat_map:
                    cat_map[current_cat] = ""
                cat_map[current_cat] += "\n" + sec.strip()

        # 映射到标准分类名，存入 ChromaDB
        for std_cat in ChapterService._MEMORY_CATEGORIES:
            doc_id = f"memory:{novel_unique_id}:{std_cat}"
            # 模糊匹配：AI 输出的分类名可能略有差异
            content = ""
            for key in cat_map:
                if std_cat in key or key in std_cat or any(
                    kw in key for kw in std_cat.split()
                ):
                    content = cat_map[key]
                    break
            if content:
                chroma_memory.collection.upsert(
                    documents=[content],
                    ids=[doc_id],
                    metadatas=[{"doc_type": "novel_memory", "category": std_cat, "novel_unique_id": novel_unique_id}]
                )
            else:
                # 空内容也写空串，标记该维度已处理
                chroma_memory.collection.upsert(
                    documents=[""],
                    ids=[doc_id],
                    metadatas=[{"doc_type": "novel_memory", "category": std_cat, "novel_unique_id": novel_unique_id}]
                )

    # ----------------------------------------------------------------
    #  AI 提取记忆：用 DeepSeek 从章节文本中提取结构化信息
    # ----------------------------------------------------------------
    _MEMORY_EXTRACT_PROMPT = """你是一位资深小说编辑。请仔细阅读以下章节内容，按10个维度提取关键信息，关键事件必须详细不要遗漏：

1.【人物】姓名|身份|性格|当前状态，如：张三|散修|阴险多疑|第3章加入青云宗
2.【组织/势力】名称|性质|成员|动向，如：青云宗|正道宗门|弟子3000|正追查魔教
3.【功法/技能/法宝】名称|效果|归属，如：天雷诀|召唤雷电|张三从古墓获得
4.【关键事件】按时间顺序详细描述：战斗（谁vs谁、结果）、突破、发现、结识、获得物品、地点转移等
5.【地点】地名|特征|发生事件，如：青云山|灵气充沛|宗门所在
6.【时间线】关键时间节点，如：春季入宗、一月后突破练气三层
7.【人物关系】A→B|关系类型，如：张三→李四|仇敌；王五→张三|师父
8.【伏笔/悬念】未解之谜，如：张三身上玉佩来历不明，疑似与上古遗迹有关
9.【实力变化】角色|修为变化，如：张三|练气一层→练气三层
10.【关键物品】物品名|功能|归属，如：神秘玉佩|发光时提升修炼速度|张三所有

格式：每条一行纯文本，不需序号和列表符号，每条标注「（第X章）」，无新信息写「无新增」

以下是要分析的章节内容：
{chapter_texts}

请开始分析："""

    # ----------------------------------------------------------------
    #  增量提取：仅分析单个新章节，追加到已有记忆
    # ----------------------------------------------------------------
    _MEMORY_INCREMENTAL_PROMPT = """你是一位资深小说编辑。以下是一章新出的内容，请从中提取关键信息，按10个维度输出：

1.【人物】姓名|身份|性格|当前状态，尽可能全
2.【组织/势力】名称|性质|成员|动向
3.【功法/技能/法宝】名称|效果|归属
4.【关键事件】按时间顺序详细列出本章每个重要事件：战斗（谁vs谁、结果）、突破、发现、结识、获得物品、地点转移等，不要遗漏
5.【地点】地名|特征|发生事件
6.【时间线】关键时间节点
7.【人物关系】A→B|关系类型
8.【伏笔/悬念】未解之谜
9.【实力变化】角色|修为变化
10.【关键物品】物品名|功能|归属

格式：每条一行纯文本不需序号，每条末尾标注「（本章新增）」，无新信息写「无新增」。

=== 本章内容 ===
{chapter_content}

=== 已有记忆（只做参考，不要重复） ===
{existing_memory}

请详细提取本章新增/变化的信息，关键事件不要遗漏："""

    @staticmethod
    async def _extract_memory_with_ai(novel_settings: str, chapters_text: str) -> str:
        """调用 DeepSeek 从所有章节文本中提取结构化记忆体"""
        prompt = ChapterService._MEMORY_EXTRACT_PROMPT.replace(
            "{chapter_texts}", chapters_text
        )
        # 前面加上作品设定
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
    @staticmethod
    def _append_to_dimension(novel_unique_id: str, category: str, new_text: str):
        """向 ChromaDB 中某个维度的文档追加新内容"""
        if not ChapterService._ensure_chroma():
            return
        doc_id = f"memory:{novel_unique_id}:{category}"
        try:
            existing = chroma_memory.collection.get(ids=[doc_id])
            old_text = existing["documents"][0] if existing and existing.get("documents") and existing["documents"][0] else ""
            merged = (old_text + "\n" + new_text).strip() if old_text else new_text.strip()
            chroma_memory.collection.upsert(
                documents=[merged],
                ids=[doc_id],
                metadatas=[{"doc_type": "novel_memory", "category": category, "novel_unique_id": novel_unique_id}]
            )
        except Exception as e:
            system_logger.error(f"[记忆体] 追加维度 {category} 失败: {e}")


    @staticmethod
    def save_extracted_to_memory(novel_unique_id: str, info_data: dict, chapter_name: str):
        """
        extract-info 提取成功后，将9维数据直接追加到 ChromaDB 记忆体
        info_data 格式: {"人物": "...", "组织": "...", ...}
        """
        # 映射前端字段 → ChromaDB 标准维度
        field_map = {
            "人物": "人物", "组织": "组织势力", "功法技能": "功法技能法宝",
            "关键事件": "关键事件", "地点": "地点", "时间": "时间线",
            "关键物品": "关键物品", "实力变化": "实力变化", "伏笔": "伏笔悬念",
        }
        for front_field, chroma_cat in field_map.items():
            val = info_data.get(front_field, "")
            if not val or val == "无":
                continue
            # 给每条加上章节标注
            text = f"{val}（{chapter_name}）"
            ChapterService._append_to_dimension(novel_unique_id, chroma_cat, text)
            system_logger.info(f"[记忆体] extract后追加 {chroma_cat}: +{len(text)}字符")

        system_logger.info(f"[记忆体] {chapter_name} 提取信息已追加到记忆体")


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

        # 截取章节内容（前5000字 + 后3000字，覆盖开头和结尾关键事件）
        text_len = len(chapter_content)
        if text_len <= 8000:
            snippet = chapter_content
        else:
            snippet = chapter_content[:5000] + "\n...\n" + chapter_content[-3000:]

        chapter_text = f"=== {chapter_name} ==="
        if chapter_summary:
            chapter_text += f"\n概要：{chapter_summary}"
        chapter_text += f"\n内容：{snippet}"

        # 构建增量提取 prompt
        prompt = ChapterService._MEMORY_INCREMENTAL_PROMPT.replace(
            "{chapter_content}", chapter_text
        ).replace("{existing_memory}", existing[-3000:] if len(existing) > 3000 else existing)

        full_prompt = f"以下小说的作品设定：\n{settings_text}\n\n 只参考设定不重复输出，只提取本章新增内容。\n\n{prompt}"

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
                        "max_tokens": 2048,
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
        import re
        sections = re.split(r'\n(?=【)', result)
        for sec in sections:
            m = re.match(r'【(.+?)】\s*\n?(.*)', sec, re.DOTALL)
            if not m:
                continue
            ai_cat = m.group(1)
            new_content = m.group(2).strip()
            if not new_content or new_content == "无新增":
                continue

            # 模糊匹配标准维度名
            for std_cat in ChapterService._MEMORY_CATEGORIES:
                if std_cat in ai_cat or ai_cat in std_cat or any(kw in ai_cat for kw in std_cat.split()):
                    ChapterService._append_to_dimension(novel_unique_id, std_cat, new_content)
                    system_logger.info(f"[记忆体] 增量追加 {std_cat}: +{len(new_content)} 字符")

                    break

        system_logger.info(f"[记忆体] 章节 {chapter_name} 增量更新完成")


    # ----------------------------------------------------------------
    #  全量记忆体：逐章提取 → 本地代码合并去重 → 存ChromaDB
    # ----------------------------------------------------------------

    @staticmethod
    def _aggregate_memory_by_code(settings_text: str, chapter_summaries: list) -> str:
        """本地代码合并记忆体（不调 AI）：逐章提取结果按维度去重合并"""
        DIMENSIONS = [
            ("人物",     ["人物"],     "【人物】",     True),
            ("组织",     ["组织"],     "【组织】",     True),
            ("功法技能", ["功法技能"], "【功法技能】", True),
            ("关键事件", ["关键事件"], "【关键事件】", False),
            ("地点",     ["地点"],     "【地点】",     True),
            ("伏笔",     ["伏笔"],     "【伏笔】",     True),
            ("时间",     ["时间"],     "【时间】",     False),
            ("关键物品", ["关键物品"], "【关键物品】", True),
            ("实力变化", ["实力变化"], "【实力变化】", True),
            ("境界",     ["境界"],     "【境界】",     True),
            ("章节数",   ["章节数"],   "【章节数】",   False),
        ]
        raw = {d[0]: [] for d in DIMENSIONS}
        chapter_count = 0
        for summary in chapter_summaries:
            lines = summary.split("\n")
            chapter_name = ""
            current_field = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                header_m = re.match(r'^===\s*第?\d+章\s*(.+?)\s*===$', line)
                if header_m:
                    chapter_name = header_m.group(1).strip()
                    chapter_count += 1
                    continue
                field_m = re.match(r'^\s*(\S+?)\s*[:：]\s*(.*)', line)
                if field_m:
                    fname = field_m.group(1).strip()
                    fval = field_m.group(2).strip()
                    for dim_name, aliases, _, _ in DIMENSIONS:
                        if fname in aliases:
                            if fval and fval not in ("无", "无新增", "无新", "—"):
                                raw[dim_name].append((chapter_name, fval))
                            current_field = dim_name
                            break
                elif current_field and line and not line.startswith("==="):
                    for dim_name, _, _, _ in DIMENSIONS:
                        if dim_name == current_field:
                            raw[dim_name].append((chapter_name, line))
                            break
        sections = [f"【作品设定】\n{settings_text}\n"]
        sections.append(f"当前已写{chapter_count}章\n")
        for dim_name, _aliases, title, dedup in DIMENSIONS:
            entries = raw[dim_name]
            if not entries:
                continue
            if dedup:
                merged = {}
                for ch, val in entries:
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
                for _, val in entries:
                    sections.append(val)
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
        5. 存入 ChromaDB
        """
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        os.makedirs(novel_dir, exist_ok=True)

        novel_settings = ChapterService._get_novel_settings(novel_unique_id)
        settings_text = novel_settings.get('content', '无')

        # 扫描章节 txt
        txt_files = [f for f in os.listdir(novel_dir) if f.endswith(".txt") and f != "作品设定.txt"]
        txt_files.sort(key=lambda f: os.path.getmtime(os.path.join(novel_dir, f)))

        if not txt_files:
            memory = f"""【作品设定】\n{settings_text}"""
            ChapterService._save_memory(novel_unique_id, memory)
            return memory

        # 逐章提取关键信息（asyncio 并发，线程数从 config.yaml 读取）
        import asyncio
        from app.config import get as cfg
        concurrency = cfg("chromadb.memory_extract_threads", 10)

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
                system_logger.info(f"[记忆体] 提取第{idx+1}/{total}章: {chapter_name}")


                info = await ChapterService.extract_chapter_info(full_text, chapter_name)

                if info.get("success") and info.get("data"):
                    data = info["data"]
                    lines = [f"=== 第{idx+1}章 {chapter_name} ==="]
                    for field in ["人物", "组织", "功法技能", "关键事件", "地点", "时间", "关键物品", "实力变化", "伏笔"]:
                        val = data.get(field, "")
                        if val and val != "无":
                            lines.append(f"  {field}: {val}")
                    result_text = "\n".join(lines)
                    system_logger.info(f"[记忆体] 第{idx+1}章 {chapter_name} 提取完成:\n{result_text}")

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
        system_logger.info(f"[记忆体] 逐章提取完成，共{chapter_num}章，摘要总长度={len(chapters_text)}")


        # === 本地代码合并记忆体（不调 AI，按维度去重合并逐章提取结果）===
        memory = ChapterService._aggregate_memory_by_code(settings_text, chapter_summaries)
        system_logger.info(f"[记忆体] 代码合并完成，记忆体总长度={len(memory)} 字符")

        ChapterService._save_memory(novel_unique_id, memory)
        return memory

    @staticmethod
    async def _ensure_memory(novel_unique_id: str, db: Session = None) -> str:
        """获取记忆体：向量库有则直接用，没有则从本地txt全量构建"""
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

    # ----------------------------------------------------------------
    #  前端草稿箱：AI提取章节关键信息（只读，不存记忆体）
    # ----------------------------------------------------------------
    _LIGHT_EXTRACT_PROMPT = """你是一位资深小说编辑。请从以下章节内容中提取关键信息，按以下格式输出：

---人物---
姓名|身份|性格特点|当前状态|修为
每个出场角色单独一行，尽可能全
（若没有新人物则写「无」）

---组织---
名称|性质|成员规模|当前动向
每个组织单独一行
（若没有新组织则写「无」）

---功法技能---
名称|效果描述|使用者/归属|来源
每个功法技能单独一行
（若没有新功法技能则写「无」）

---关键事件---
请按时间顺序，详细列出本章发生的每一个重要事件，不要遗漏！
包括：战斗（谁vs谁、结果）、突破晋级、发现秘密、结识新角色、
对话中的关键信息、获得物品、离开/到达新地点、做出重大决定等。
每件事单独一行，描述尽量完整。
（若没有关键事件则写「无」）

---地点---
地名|特征描述|发生了什么
每个地点单独一行
（若没有新地点则写「无」）

---时间---
时间节点|发生了什么事
（若没有时间信息则写「无」）

---关键物品---
物品名|功能效果|归属/发现者
每个物品单独一行
（若没有关键物品则写「无」）

---实力变化---
角色名|变化前→变化后|原因
（若没有实力变化则写「无」）

---伏笔---
描述未解之谜或暗示的信息
（若没有伏笔则写「无」）

=== 章节内容 ===
{content}

请开始提取，关键事件必须详细不要遗漏："""

    @staticmethod
    async def extract_chapter_info(content: str, chapter_name: str = "") -> dict:
        """
        从章节内容中 AI 提取关键信息（轻量级，不存记忆体）
        返回结构化 dict 供前端展示
        """
        if not content or len(content) < 50:
            return {"success": True, "data": {"人物": "", "组织": "", "功法技能": "",
                     "关键事件": "", "地点": "", "时间": "",
                     "关键物品": "", "实力变化": "", "伏笔": ""}}

        # 截取内容：短章节全取，超长取前5000+后3000（覆盖开头和结尾关键事件）
        content_len = len(content)
        if content_len <= 8000:
            snippet = content
        else:
            snippet = content[:5000] + "\n...\n" + content[-3000:]

        prompt = ChapterService._LIGHT_EXTRACT_PROMPT.replace("{content}", snippet)

        result = {}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {deepseek_api_key()}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": deepseek_model(),
                        "messages": [
                            {"role": "system", "content": "你是一位小说编辑，请尽可能详细地提取关键信息，尤其是关键事件不要遗漏。"},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 3072,
                        "temperature": 0.2
                    }
                )
                data = response.json()
                if "choices" in data and data["choices"]:
                    ai_output = data["choices"][0]["message"]["content"]
                    system_logger.info(f"[提取信息] AI返回长度={len(ai_output)}, 前200字: {ai_output[:200]}")

                    # 解析 ---标签--- / 【标签】 / **标签** 等多种格式
                    import re
                    current_key = ""
                    for line in ai_output.split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        # 匹配多种标签格式：---人 物--- / 【人物】 / **人物** / 人物：
                        m = re.match(r'^[-—]{1,3}\s*(.+?)\s*[-—]{0,3}$', line)
                        if not m:
                            m = re.match(r'^【(.+?)】$', line)
                        if not m:
                            m = re.match(r'^\*\*(.+?)\*\*$', line)
                        if not m:
                            m = re.match(r'^([^\|]+)：$', line)  # e.g. "人物："
                        if m:
                            current_key = m.group(1).strip()
                            if current_key not in result:
                                result[current_key] = []
                        elif current_key:
                            if line not in ("无", "无新增", "无新"):
                                result[current_key].append(line)
                else:
                    return {"success": False, "error": "AI提取失败: " + str(data.get("error", {}).get("message", "未知错误"))}

            # list → string
            for key in list(result.keys()):
                result[key] = "\n".join(result[key])

            # 确保所有字段存在
            for field in ["人物", "组织", "功法技能", "关键事件", "地点", "时间", "关键物品", "实力变化", "伏笔"]:
                if field not in result:
                    result[field] = ""

            return {"success": True, "data": result}
        except Exception as e:
            system_logger.error(f"[提取信息] 异常: {e}")

            return {"success": False, "error": str(e)}

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
                       chapter_summary: str = None, created_by: str = None) -> dict:
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
        :return: 创建结果（含chapter_unique_id）
        """
        chapter_unique_id = uuid.uuid4().hex
        chapter = ChapterDAO.create(
            db,
            novel_unique_id=novel_unique_id,
            user_id=user_id,
            chapter_unique_id=chapter_unique_id,
            chapter_name=chapter_name,
            characters_involved=characters_involved,
            organizations=organizations,
            locations=locations,
            skills=skills,
            word_count=word_count,
            chapter_summary=chapter_summary,
            is_published=0,
            created_by=created_by
        )
        chapter_data = {
            "chapter_unique_id": chapter_unique_id,
            "chapter_name": chapter_name,
            "novel_unique_id": novel_unique_id,
            "characters_involved": characters_involved,
            "organizations": organizations,
            "locations": locations,
            "skills": skills,
            "word_count": word_count,
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
    # 主生成函数（统一记忆体+概要边界体系）
    # ============================================================
    @staticmethod
    async def generate_with_ai(db: Session, novel_unique_id: str, user_id: int,
                               chapter_name: str, characters_involved: str = None,
                               organizations: str = None, locations: str = None,
                               skills: str = None, word_count: int = 2000,
                               chapter_summary: str = None,
                               created_by: str = None) -> dict:
        """调用DeepSeek AI生成章节正文内容（统一记忆体+概要边界体系）"""

        # ============================================================
        # 自动编号
        # ============================================================
        existing_count = ChapterDAO.count_by_novel_id(db, novel_unique_id)
        chapter_num = existing_count + 1
        num_map = list("零一二三四五六七八九十")
        
        def to_chinese(n):
            if n <= 10:
                return num_map[n] if n > 0 else "一"
            elif n < 100:
                s = ""
                if n >= 20:
                    s += num_map[n // 10]
                s += "十"
                if n % 10 != 0:
                    s += num_map[n % 10]
                return s
            elif n < 1000:
                s = num_map[n // 100] + "百"
                n = n % 100
                if n == 0:
                    return s
                if n < 10:
                    s += "零" + num_map[n]
                else:
                    s += num_map[n // 10] + "十"
                    if n % 10 != 0:
                        s += num_map[n % 10]
                return s
            else:
                s = num_map[n // 1000] + "千"
                n = n % 1000
                if n == 0:
                    return s
                if n < 100:
                    s += "零"
                if n >= 100:
                    s += num_map[n // 100] + "百"
                n = n % 100
                if n == 0:
                    return s
                if n < 10:
                    s += "零" + num_map[n]
                else:
                    s += num_map[n // 10] + "十"
                    if n % 10 != 0:
                        s += num_map[n % 10]
                return s
        
        chinese_num = to_chinese(chapter_num)
        if not re.match(r'^第.+章', chapter_name):
            chapter_name = f"第{chinese_num}章 {chapter_name}"

        # ============================================================
        # 记忆体：从 ChromaDB 加载（没有则从 txt 全量构建）
        # ============================================================
        memory_body = await ChapterService._ensure_memory(novel_unique_id, db)
        system_logger.info(f"[章节生成] 记忆体长度={len(memory_body)} 字符")

        # ============================================================
        # 获取作品设定
        # ============================================================
        novel_settings = ChapterService._get_novel_settings(novel_unique_id)
        settings_text = novel_settings.get('content', '无')

        # ============================================================
        # 获取上一章结尾（用于续写衔接，取末尾 500 字）
        # ============================================================
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        sorted_chapters = sorted(all_chapters, key=lambda c: c.created_at or "")
        prev_chapters = sorted_chapters[:-1] if len(sorted_chapters) > 1 else []

        last_chapter_ending = ""
        last_chapter_full = ""
        previous_text_for_duplicate = ""

        if prev_chapters:
            last_ch = prev_chapters[-1]
            last_chapter_full = last_ch.content or ""
            if not last_chapter_full:
                novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
                chapter_file = os.path.join(novel_dir, f"{last_ch.chapter_name}_{last_ch.chapter_unique_id}.txt")
                if os.path.exists(chapter_file):
                    with open(chapter_file, "r", encoding="utf-8") as f:
                        last_chapter_full = f.read()

            if last_chapter_full:
                last_chapter_ending = last_chapter_full[-500:]
                system_logger.info(f"[章节生成] 续写锚点：上一章末尾500字")

            # 取最近3章用于去重检测
            recent_3 = prev_chapters[-3:] if len(prev_chapters) >= 3 else prev_chapters
            for ch in recent_3:
                content = ch.content or ""
                if not content:
                    novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
                    chapter_file = os.path.join(novel_dir, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
                    if os.path.exists(chapter_file):
                        with open(chapter_file, "r", encoding="utf-8") as f:
                            content = f.read()
                if content:
                    previous_text_for_duplicate += content + "\n"

        # ============================================================
        # 章节概要 → 作为 AI 生成硬边界
        # ============================================================
        chapter_setting = f"""本章设定：
章节名称：{chapter_name}
本章概要：{chapter_summary or '继承前文自然推进'}
目标字数：{word_count}字
涉及人物：{characters_involved or '继承前文'}
场景地点：{locations or '继承前文'}"""

        # 构建自然语言概要
        summary_narrative = ""
        if chapter_summary:
            sentences = re.split(r'[，,。.！!？?；;]', chapter_summary)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
            if sentences:
                summary_narrative = "本章要写：" + "；".join(sentences) + "。"

        # ============================================================
        # 构建 prompt（与 regenerate 统一体系）
        # ============================================================
        prompt = f"""你是一个文笔精湛的小说家，擅长创作生动、有感染力的网文章节。请严格按照以下要求续写本章。

【🔴 本章核心剧情 —— 必须严格遵循，不可偏离】
{chapter_summary or '根据前文自然推进剧情，不做脱离'}
{summary_narrative}

【已写章节记忆体 —— 人物/事件/世界观，必须保持一致】
{memory_body}

【上一章节结尾 —— 必须无缝衔接】
{last_chapter_ending if last_chapter_ending else '这是第一章，无需承接'}

{chapter_setting}

【写作铁律 —— 每条都必须做到】

一、概要即边界（违反即作废）：
- 本章概要列出的剧情 = 你唯一要写的内容
- 概要没写的（新人物、新事件、新地点）一律不许加入
- 概要里每个事件都要写到，顺序即叙事顺序

二、衔接与节奏：
- 开篇从上一章结尾自然过渡：续写动作 / 接住情绪 / 回答问题
- 不要倒带、不要回放、不要"回顾之前"
- 场景切换用空行分隔，不写过渡段

三、人物鲜活：
- 每个出场角色通过对话/神态/动作展现性格，不贴标签
- 不同角色说话方式要有区分
- 用 2-3 个细节让角色立体

四、情感丰富：
- 每个情绪点至少展开 50-100 字，不许一笔带过
- 用身体语言传递情绪：心跳、呼吸、手心、嗓子、后背
- 一章至少 2 次情绪转折

五、内容丰富：
- 字数控制在{word_count}字左右，不要灌水
- 对话占全文 30% 左右，每句对话推动剧情或展现性格
- 场景描写用五感（视觉/听觉/嗅觉/触觉/味觉）至少 2 种

六、输出格式：
- 只输出章节正文（含标题「{chapter_name}」）
- 不加额外说明、总结或注释"""

        # ============================================================
        # 情感描写指南 + System Prompt
        # ============================================================
        prompt += "\n\n" + EMOTIONAL_WRITING_GUIDE

        system_prompt = """你是一个文笔精湛、擅长人物塑造和氛围营造的资深小说家。
你写的小说人物性格鲜明、情感细腻、场景有画面感、剧情有张力。
你擅长用细节描写让人物和场景活起来，用情绪变化让读者产生共鸣。

铁律：
- 从上一章结尾直接接着写，不加标题、不加开场白
- 概要里列出的事件，每一个都要写，不能跳过
- 概要没写的——街景、路人、百姓议论、新人物——一律不写
- 保持上一章结尾的时间、地点、情绪连续
- 禁止直说情绪词，必须通过动作和身体感受传递"""

        # ============================================================
        # API 调用（带重试）
        # ============================================================
        MAX_RETRIES = 2
        generated_text = ""

        for attempt in range(MAX_RETRIES + 1):
            try:
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
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": prompt}
                            ],
                            "max_tokens": word_count * 3,
                            "temperature": 0.75,
                            "top_p": 0.9,
                            "frequency_penalty": 0.5,
                            "presence_penalty": 0.3
                        }
                    )

                    data = response.json()
                    if "choices" not in data or not data["choices"]:
                        err_msg = str(data.get("error", {}).get("message", "未知错误"))
                        system_logger.error(f"AI章节生成失败: {chapter_name} → {err_msg}")
                        return fail("AI生成失败: " + err_msg, code=500)

                    generated_text = data["choices"][0]["message"]["content"]

                    if generated_text and len(generated_text) > 100:
                        actual_words = len(generated_text)
                        system_logger.info(f"AI章节生成成功: {chapter_name} ({actual_words}字)")
                        break
                    else:
                        if attempt < MAX_RETRIES:
                            system_logger.warning(f"[重试 {attempt+1}] {chapter_name} 生成内容过短")
                            continue
                        else:
                            return fail("AI生成内容过短，请重试", code=500)

            except httpx.TimeoutException:
                system_logger.error(f"AI章节生成超时: {chapter_name}")
                if attempt < MAX_RETRIES:
                    continue
                return fail("AI接口调用超时，请重试", code=500)
            except Exception as e:
                if attempt < MAX_RETRIES:
                    system_logger.warning(f"[重试 {attempt+1}] AI调用异常: {e}")
                    continue
                else:
                    return fail(f"AI生成失败: {str(e)}", code=500)

        # ============================================================
        # 后处理：文学质量检查
        # ============================================================
        quality_issues = ChapterService._check_literary_quality(generated_text, previous_text_for_duplicate)
        if quality_issues:
            system_logger.warning(f"[文学质量] {chapter_name} 发现 {len(quality_issues)} 个问题:")
            for issue in quality_issues:
                system_logger.warning(f"  - {issue}")

        # ============================================================
        # 保存章节
        # ============================================================
        chapter_unique_id = uuid.uuid4().hex
        actual_word_count = len(generated_text)

        try:
            chapter = ChapterDAO.create(
                db,
                novel_unique_id=novel_unique_id,
                user_id=user_id,
                chapter_unique_id=chapter_unique_id,
                chapter_name=chapter_name,
                characters_involved=characters_involved,
                organizations=organizations,
                locations=locations,
                skills=skills,
                word_count=actual_word_count,
                chapter_summary=chapter_summary,
                is_published=0,
                content=generated_text,
                created_by=created_by
            )
        except Exception as e:
            system_logger.error(f"保存章节到数据库失败: {e}")
            return fail(f"保存章节失败: {str(e)}", code=500)

        try:
            novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
            os.makedirs(novel_dir, exist_ok=True)
            chapter_file = os.path.join(novel_dir, f"{chapter_name}_{chapter_unique_id}.txt")
            with open(chapter_file, "w", encoding="utf-8") as f:
                f.write(generated_text)
        except Exception as e:
            system_logger.error(f"保存章节文件失败: {e}")

        try:
            r = _redis()
            if r:
                r.delete_pattern(f"chapters:drafts:user:{user_id}")
        except Exception as e:
            system_logger.warning(f"清除缓存失败: {e}")

        return success({
            "chapter_unique_id": chapter_unique_id,
            "chapter_name": chapter_name,
            "word_count": actual_word_count,
            "content": generated_text
        }, f"{chapter_name} 章节内容生成成功")

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
                                 word_count: int = 2000, chapter_summary: str = None) -> dict:
        """重新生成指定章节：记忆体基于第1章到当前章节之前的所有内容，覆盖当前章节
        :param db: 数据库会话
        :param chapter_unique_id: 要重新生成的章节唯一ID
        :param user_id: 用户ID
        :param word_count: 目标字数
        :param chapter_summary: 剧情发展路线（前端编辑后传入，优先使用；为空则用DB中的）
        :return: 生成结果（含新内容和章节ID）
        """
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
        if chapter.user_id != user_id:
            return fail("无权操作此章节", code=403)

        novel_unique_id = chapter.novel_unique_id
        chapter_name = chapter.chapter_name
        # 如果前端传入了chapter_summary（用户编辑后），优先用；否则用数据库里的
        if chapter_summary is None:
            chapter_summary = chapter.chapter_summary or ""

        # 获取作品设定
        novel_settings = ChapterService._get_novel_settings(novel_unique_id)
        settings_text = novel_settings.get('content', '无')

        # 获取所有章节，按创建时间排序
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        sorted_chapters = sorted(all_chapters, key=lambda c: c.created_at or "")

        # 找到当前章节位置，取第1章到当前章节之前的所有章节
        current_idx = None
        for i, ch in enumerate(sorted_chapters):
            if ch.chapter_unique_id == chapter_unique_id:
                current_idx = i
                break

        prev_chapters = sorted_chapters[:current_idx] if current_idx is not None and current_idx > 0 else []

        # 构建记忆体：从第1章到前一章，逐章提取关键信息
        memory_body = f"【作品设定】\n{settings_text}\n\n"

        if prev_chapters:
            # 对每一章提取关键信息
            for i, ch in enumerate(prev_chapters, 1):
                content = ch.content or ""
                if not content:
                    # 兜底从本地文件读取
                    novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
                    chapter_file = os.path.join(novel_dir, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
                    if os.path.exists(chapter_file):
                        with open(chapter_file, "r", encoding="utf-8") as f:
                            content = f.read()

                if content and not content.strip().startswith("{"):
                    # 提取章节摘要（前1500字作为概要）
                    snippet = content[:1500].replace("\n", " ")
                    memory_body += f"=== 第{i}章 {ch.chapter_name} ===\n"
                    memory_body += f"内容概要: {snippet}...\n"
                    memory_body += f"字数: {len(content)}字\n\n"
                else:
                    memory_body += f"=== 第{i}章 {ch.chapter_name} ===\n（暂无内容）\n\n"
        else:
            memory_body += "（这是第一章，无前文参考）\n"

        # 上一章末尾内容（用于无缝衔接）
        last_chapter_content = ""
        if prev_chapters:
            last_ch = prev_chapters[-1]
            last_chapter_content = last_ch.content or ""
            if not last_chapter_content:
                novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
                chapter_file = os.path.join(novel_dir, f"{last_ch.chapter_name}_{last_ch.chapter_unique_id}.txt")
                if os.path.exists(chapter_file):
                    with open(chapter_file, "r", encoding="utf-8") as f:
                        last_chapter_content = f.read()

        chapter_setting = f"""本章设定：
章节名称：{chapter_name}
本章概要：{chapter_summary or '无'}
目标字数：{word_count}字"""

        prompt = f"""你是一个文笔精湛的小说家，擅长创作生动、有感染力的网文章节。请根据以下设定和已写章节内容，重新生成这一章。

【本章核心剧情 —— 必须严格按此剧情写，不能偏离】
{chapter_summary or '（无特定剧情要求，请根据前文自然推进）'}

【已写章节内容】（第1章到前一章的关键信息，必须严格遵循）
{memory_body}

【上一章节结尾】（必须无缝衔接，可以从动作/对话/场景自然过渡）
{last_chapter_content[-2500:] if last_chapter_content else '这是第一章，无需承接'}

{chapter_setting}

【写作核心要求 —— 每条都必须做到】
一、剧情遵从（本章概要必须执行）：
- 本章概要列出的剧情必须全部覆盖，不能遗漏
- 每个概要里提到的事件都必须在正文中体现
- 如果概要提到某个人物或地点，必须让该人物/地点在正文中出场
- 概要的剧情顺序就是本章的叙事顺序

二、人物塑造（性格要鲜明立体）：
- 每个出场角色要有独特的说话方式、动作习惯和内心活动
- 通过对话、神态、心理活动来展示性格，不要直接贴标签
- 角色的选择和行为要符合其已建立的性格设定
- 用 2-3 个细节描写让角色鲜活（如：一个习惯动作、一句口头禅、一个表情变化）

三、情感描写（要有情绪层次）：
- 写出角色的内心感受：喜悦/愤怒/恐惧/悲伤/纠结/期待，要有情绪变化的过程
- 情感不要一笔带过，至少用 2-3 句话展开描写
- 关键情感节点要有内心独白或细腻的动作神态来呈现
- 让读者能感受到角色的情绪波动，产生代入感

四、场景与环境描写（要让读者身临其境）：
- 每个场景切换时必须描写新环境：光线、气味、声音、温度、空间格局
- 用五感（视觉/听觉/嗅觉/触觉/味觉）至少 2 种来渲染场景
- 战斗场景：写出招式动作、灵力波动、破坏效果、周围人的反应
- 日常场景：写出氛围感，不干巴巴的叙述

五、情绪氛围营造（要有张力和节奏）：
- 根据剧情需要营造对应氛围：紧张/温馨/诡异/悲壮/热血/压抑
- 用短句和长句交替控制节奏：紧张时短句快节奏，抒情时长句慢节奏
- 适当使用环境烘托情绪（如：阴雨衬托悲伤，阳光衬托希望）
- 章节结尾必须留悬念或情绪钩子，让读者想看下一章

六、剧情张力（要有冲突和推进）：
- 每章至少有一个核心冲突或事件推进（战斗/争执/发现/决定/危机）
- 剧情要有起伏：铺垫→冲突→转折→余韵，不是平铺直叙
- 角色之间要有互动和化学反应（对话交锋、合作、对抗）
- 如果本章是过渡章，也要有信息量推进（获取情报/关系变化/世界观展开）

七、内容丰富度（情节要饱满）：
- 字数控制在{word_count}字左右
- 不要灌水，每段都推进剧情或塑造人物
- 对话与叙述比例约 3:7，不要纯对话或纯叙述

八、输出格式：
- 只输出章节正文（含章节标题如「{chapter_name}」）
- 不要加额外的说明、总结或注释
- 段落分明，适当留白，增强可读性"""

        async with httpx.AsyncClient(timeout=180) as client:
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
                            {"role": "system", "content": "你是一个文笔精湛、擅长人物塑造和氛围营造的资深小说家。你写的小说人物性格鲜明、情感细腻、场景有画面感、剧情有张力。你擅长用细节描写让人物和场景活起来，用情绪变化让读者产生共鸣，用剧情冲突让故事扣人心弦。"},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": word_count * 3,
                        "temperature": 0.85
                    }
                )
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    err_msg = str(data.get("error", {}).get("message", "未知错误"))
                    system_logger.error(f"AI章节重新生成失败: {chapter_name} → {err_msg}")
                    return fail("AI重新生成失败: " + err_msg, code=500)

                generated_text = data["choices"][0]["message"]["content"]
                actual_words = len(generated_text)
                system_logger.info(f"AI章节重新生成成功: {chapter_name} ({actual_words}字) novel={novel_unique_id}")

                # 更新当前章节（覆盖内容，不新建）
                ChapterDAO.update(db, chapter,
                    content=generated_text,
                    word_count=actual_words
                )

                # 更新本地文件
                novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
                os.makedirs(novel_dir, exist_ok=True)
                chapter_file = os.path.join(novel_dir, f"{chapter_name}_{chapter_unique_id}.txt")
                with open(chapter_file, "w", encoding="utf-8") as f:
                    f.write(generated_text)

                # 清除草稿缓存
                r = _redis()
                if r:
                    r.delete_pattern(f"chapters:drafts:user:{user_id}")

                return success({
                    "chapter_unique_id": chapter_unique_id,
                    "chapter_name": chapter_name,
                    "word_count": actual_words,
                    "content": generated_text
                }, f"{chapter_name} 重新生成成功")

            except httpx.TimeoutException:
                system_logger.error(f"AI章节重新生成超时: {chapter_name}")
                return fail("AI接口调用超时，请重试", code=500)
            except Exception as e:
                system_logger.error(f"AI章节重新生成异常: {chapter_name} → {str(e)}")
                return fail(f"AI重新生成失败: {str(e)}", code=500)

    @staticmethod
    async def continue_with_ai(db: Session, chapter_unique_id: str, word_count: int = 800) -> dict:
        """AI 续写指定章节：根据作品设定+前文+当前内容，续写本章后续内容"""
        from app.dao.novel_dao import NovelDAO
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)

        # 读取当前章节已有内容：优先从 DB content 字段，兜底本地文件
        existing_content = chapter.content or ""
        if not existing_content:
            novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
            chapter_file = os.path.join(novel_dir, f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
            if os.path.exists(chapter_file):
                with open(chapter_file, "r", encoding="utf-8") as f:
                    existing_content = f.read()

        # 当前章节已写内容（取末尾部分作为上下文）
        context_content = existing_content[-2000:] if len(existing_content) > 2000 else existing_content

        # ===== 记忆体：一次加载 =====
        memory_body = await ChapterService._ensure_memory(chapter.novel_unique_id, db)

        prompt = f"""你是一个文笔精湛的小说家。请根据记忆体和已写内容，续写出高质量的小说内容。

【作品记忆体】（必须严格遵循的人物、事件、世界观）
{memory_body}

【本章信息】
章节名称：{chapter.chapter_name}
本章概要：{chapter.chapter_summary or '无'}
当前已写内容（末尾，必须紧密衔接）：
{context_content}

【续写核心要求 —— 每条都必须做到】
一、人物塑造：对话要有性格辨识度，用动作/神态/心理活动展示人物特征
二、情感描写：写出角色内心感受和情绪变化，至少 2-3 句展开
三、场景环境：用五感（视觉/听觉/嗅觉等）渲染场景，让读者有画面感
四、情绪氛围：营造适合当前剧情的氛围，长短句交替控制节奏
五、剧情张力：有冲突或事件推进，铺垫→冲突→转折→余韵
六、内容丰富：每段都推进剧情或塑造人物，对话与叙述比例约 3:7
七、续写 {word_count} 字左右，只输出续写内容，不要重复已有文字，不要加标题"""

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
                            {"role": "system", "content": "你是一个文笔精湛、擅长人物塑造和氛围营造的资深小说家。你写的小说人物性格鲜明、情感细腻、场景有画面感、剧情有张力。"},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": word_count * 3,
                        "temperature": 0.8
                    }
                )
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    err_msg = str(data.get("error", {}).get("message", "未知错误"))
                    system_logger.error(f"AI续写失败: {chapter.chapter_name} → {err_msg}")
                    return fail("AI续写失败: " + err_msg, code=500)

                generated_text = data["choices"][0]["message"]["content"]
                system_logger.info(f"AI续写成功: {chapter.chapter_name} +{len(generated_text)}字")

                # 追加续写内容到文件（兼容）和数据库
                new_content = existing_content + "\n\n" + generated_text
                novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
                os.makedirs(novel_dir, exist_ok=True)
                chapter_file = os.path.join(novel_dir, f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
                with open(chapter_file, "w", encoding="utf-8") as f:
                    f.write(new_content)

                # 更新数据库字数 + 内容
                ChapterDAO.update(db, chapter, word_count=len(new_content), content=new_content)

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
            content = ""
            if os.path.exists(chapter_file):
                with open(chapter_file, "r", encoding="utf-8") as f:
                    content = f.read()
            result.append({
                "chapter_unique_id": ch.chapter_unique_id,
                "novel_unique_id": ch.novel_unique_id,
                "chapter_name": ch.chapter_name,
                "word_count": ch.word_count,
                "chapter_summary": ch.chapter_summary,
                "content": content,
                "is_published": ch.is_published,
                "created_at": ch.created_at.isoformat() if ch.created_at else None,
                "characters_involved": ch.characters_involved,
                "organizations": ch.organizations,
                "locations": ch.locations,
                "skills": ch.skills,
                "events": ch.events,
                "time_info": ch.time_info,
                "key_items": ch.key_items,
                "power_changes": ch.power_changes,
                "foreshadowing": ch.foreshadowing,
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
        """发布章节：保存内容到txt、保存AI提取信息、标记已发布、同步到作品圈"""
        from app.dao.interaction_dao import InteractionDAO
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
        if chapter.is_published:
            return fail("该章节已发布", code=400)
        update_data = {"is_published": 1}
        if content is not None:
            novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
            os.makedirs(novel_dir, exist_ok=True)
            chapter_file = os.path.join(novel_dir, f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
            with open(chapter_file, "w", encoding="utf-8") as f:
                f.write(content)
            update_data["word_count"] = len(content)
        # 保存前端 AI 提取的关键信息
        if characters_involved: update_data["characters_involved"] = characters_involved
        if organizations: update_data["organizations"] = organizations
        if locations: update_data["locations"] = locations
        if skills: update_data["skills"] = skills
        if events: update_data["events"] = events
        if time_info: update_data["time_info"] = time_info
        if key_items: update_data["key_items"] = key_items
        if power_changes: update_data["power_changes"] = power_changes
        if foreshadowing: update_data["foreshadowing"] = foreshadowing
        ChapterDAO.update(db, chapter, **update_data)
        # 发布到作品圈：创建一条动态
        interaction_text = f"发布了新章节「{chapter.chapter_name}」"
        InteractionDAO.create_or_update(
            db,
            user_id=chapter.user_id,
            novel_unique_id=chapter.novel_unique_id,
            interactor_id=chapter.user_id,
            interactor_name=chapter.created_by or "",
            comment_text=interaction_text
        )
        r = _redis()
        if r:
            r.delete_pattern("chapters:*")
            r.delete_pattern("interactions:*")

        return success({"chapter_unique_id": chapter_unique_id, "chapter_name": chapter.chapter_name}, "章节发布成功，已同步到作品圈")

    @staticmethod
    def update_chapter(db: Session, chapter_unique_id: str, content: str = None,
                       chapter_name: str = None, chapter_summary: str = None) -> dict:
        """更新已存在的章节内容、名称或概要
        :param db: 数据库会话
        :param chapter_unique_id: 章节唯一ID
        :param content: 新章节正文
        :param chapter_name: 新章节名称
        :param chapter_summary: 新章节概要
        :return: 操作结果
        """
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
        update_data = {}
        if content is not None:
            novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
            os.makedirs(novel_dir, exist_ok=True)
            chapter_file = os.path.join(novel_dir, f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
            with open(chapter_file, "w", encoding="utf-8") as f:
                f.write(content)
            update_data["word_count"] = len(content)
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
        r3 = _redis()
        if r3:
            r3.delete_pattern(f"chapters:*")
        # 章节内容更新后异步增量更新记忆体（不阻塞响应）
        if content is not None:
            import asyncio, threading
            _nid = chapter.novel_unique_id
            _ct = content
            _cn = chapter_name or chapter.chapter_name
            _cs = chapter_summary or chapter.chapter_summary or ""
            def _async_memory():
                try:
                    asyncio.run(ChapterService._incremental_memory_update(
                        _nid, None, _ct, _cn, _cs
                    ))
                except BaseException as e:
                    system_logger.error(f"[更新章节] 记忆体增量更新失败: {e}")
            t = threading.Thread(target=_async_memory, daemon=True)
            t.start()
            system_logger.info(f"[更新章节] {chapter_name or chapter.chapter_name} 已保存，记忆体后台更新中")
        return success(None, "章节更新成功")

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
            r4.delete_pattern("interactions:*")

        # 4. 异步重建记忆体（不阻塞响应，失败也不回滚 DB）
        import asyncio, threading
        def _async_rebuild():
            try:
                asyncio.run(ChapterService._rebuild_memory_from_files(novel_unique_id, db=None))
            except BaseException as e:
                system_logger.error(f"[删除章节] 记忆体重建失败: {e}")


        t = threading.Thread(target=_async_rebuild, daemon=True)
        t.start()

        system_logger.info(f"[删除章节] {chapter_name} 已删除，记忆体后台重建中")

        return success(None, "章节删除成功，记忆体后台更新中")

    @staticmethod
    def get_novel_chapters(db: Session, novel_unique_id: str) -> dict:
        """获取指定作品的所有章节列表，带Redis缓存
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :return: 章节列表（含正文内容）
        """
        cache_key = f"chapters:novel:{novel_unique_id}:all"
        r5 = _redis()
        if r5:
            cached = r5.get(cache_key)
            if cached:
                return success(cached)
        chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        result = []
        for ch in chapters:
            novel_dir = os.path.join(NOVEL_DATA_PATH, ch.novel_unique_id)
            chapter_file = os.path.join(novel_dir, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
            content = ""
            if os.path.exists(chapter_file):
                with open(chapter_file, "r", encoding="utf-8") as f:
                    content = f.read()
            result.append({
                "chapter_unique_id": ch.chapter_unique_id,
                "chapter_name": ch.chapter_name,
                "word_count": ch.word_count,
                "chapter_summary": ch.chapter_summary,
                "content": content,
                "is_published": ch.is_published,
                "created_at": ch.created_at.isoformat() if ch.created_at else None
            })
        if r5:
            r5.set(cache_key, result)
        return success(result)

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
