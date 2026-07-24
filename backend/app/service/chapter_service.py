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
from app.config import deepseek_api_key, deepseek_base_url, deepseek_model
from app.utils.logger import system_logger
from app.utils.task_queue import run_async
from app.prompts.chapter_prompts import (
    LIGHT_EXTRACT_PROMPT, FULL_EXTRACT_PROMPT,
    MEMORY_DIMENSION_DEFS, MEMORY_EXTRACT_PROMPT, MEMORY_INCREMENTAL_PROMPT,
    get_memory_category_names, get_frontend_to_chroma_map,
    match_ai_label_to_chroma, get_chroma_dedup_map,
    EMOTIONAL_WRITING_GUIDE,
    GENERATE_SYSTEM_PROMPT, GENERATE_CREATIVE_DIRECTION,
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
    def reset_and_rebuild_memory(novel_unique_id: str, db) -> dict:
        """清空 Redis 记忆体 + 后台逐章 AI 提取重建

        1. 删除 Redis Hash key
        2. 统计已发布章节数
        3. 启动后台线程：逐章读 TXT → AI 提取 → 写入 Redis
        4. 立即返回章节数（不等待重建完成）
        """
        r = _redis()
        if not r or not r.ping():
            return fail("Redis 不可用", code=500)

        # 清空
        key = ChapterService._memory_key(novel_unique_id)
        try:
            r.delete(key)
            system_logger.info(f"[记忆体重置] 已清空 {novel_unique_id} 的 Redis 记忆体")
        except Exception as e:
            system_logger.error(f"[记忆体重置] 清空失败: {e}")
            return fail(f"清空失败: {str(e)}", code=500)

        # 统计章节数
        from app.dao.chapter_dao import ChapterDAO
        all_ch = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        published = [c for c in all_ch if c.is_published]

        chapter_count = len(published)
        if chapter_count == 0:
            system_logger.info(f"[记忆体重置] {novel_unique_id} 无已发布章节，无需重建")
            return success({"章节数": 0, "消息": "记忆体已清除，暂无已发布章节"}, "重置完成")

        # 后台线程：逐章 AI 提取写入 Redis
        import threading
        _nid = novel_unique_id
        _db_factory = None
        try:
            from app.models.base import SessionLocal as _s
            _db_factory = _s
        except Exception:
            pass

        def _rebuild_async():
            import asyncio
            async def _work():
                system_logger.info(f"[记忆体重置] 开始后台重建 {chapter_count} 章的记忆体...")
                try:
                    await ChapterService._rebuild_memory_from_files(_nid, db=None)
                    system_logger.info(f"[记忆体重置] 后台重建完成: {_nid}")
                except Exception as e:
                    system_logger.error(f"[记忆体重置] 后台重建失败: {e}")
            try:
                asyncio.run(_work())
            except Exception as e:
                system_logger.error(f"[记忆体重置] 后台线程异常: {e}")

        threading.Thread(target=_rebuild_async, daemon=True, name=f"memory-rebuild-{novel_unique_id[:8]}").start()

        msg = f"记忆体已清除，正在后台重建 {chapter_count} 章记忆数据（章节越多越慢，请耐心等待）"
        system_logger.info(f"[记忆体重置] {novel_unique_id}: {msg}")
        return success({"章节数": chapter_count, "消息": msg}, "重置已启动，后台重建中...")

    @staticmethod
    def _ensure_memory_store():
        """检查 Redis 是否可用"""
        r = _redis()
        return r is not None and r.ping()

    # ----------------------------------------------------------------
    #  记忆体存储：按维度拆分存入 ChromaDB，维度定义统一来自 chapter_prompts
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
                if match_ai_label_to_chroma(ai_cat) == std_cat:
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
        """向 Redis Hash 中某个维度写入新内容（去重维度按首字段替换旧条目）"""
        if category not in get_memory_category_names():
            system_logger.warning(f"[记忆体] 非标准维度 '{category}'，跳过追加（允许: {get_memory_category_names()}）")
            return
        r = _redis()
        if not r or not r.ping():
            return
        key = ChapterService._memory_key(novel_unique_id)
        try:
            dedup_map = get_chroma_dedup_map()
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
        field_map = get_frontend_to_chroma_map()
        for front_field, chroma_cat in field_map.items():
            raw_val = info_data.get(front_field, "")
            if not raw_val or raw_val == "无":
                continue
            natural = ChapterService._pipe_to_natural(front_field, raw_val, chapter_name)
            if not natural:
                continue
            ChapterService._append_to_dimension(novel_unique_id, chroma_cat, natural)
            system_logger.info(f"[记忆体] extract后追加 {chroma_cat}: +{len(natural)}字符")

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
    def _trim_to_summary_boundary(generated_text: str, chapter_summary: str) -> str:
        """硬截断：找到概要最后一个事件的正文落点，删除之后所有内容。"""
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

        keep_lines = lines[:target_line_idx + 1]
        # 最多再加 1 行短收束
        if target_line_idx + 1 < len(lines):
            next_line = lines[target_line_idx + 1].strip()
            if next_line and len(next_line) <= 30:
                keep_lines.append(lines[target_line_idx + 1])

        trimmed = '\n'.join(keep_lines).strip()
        if len(trimmed) < len(generated_text) * 0.3:
            return generated_text

        return trimmed


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
                prompt = FULL_EXTRACT_PROMPT.replace("{content}", content[-15000:])
                response = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {deepseek_api_key()}", "Content-Type": "application/json"},
                    json={"model": deepseek_model(), "messages": [
                        {"role": "system", "content": "你是一位资深小说编辑，擅长从文本中提取结构化信息，输出详尽完整的章节分析报告。"},
                        {"role": "user", "content": prompt}
                    ], "max_tokens": 8000, "temperature": 0.2},
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
            async with httpx.AsyncClient(timeout=120) as client:
                prompt = LIGHT_EXTRACT_PROMPT.replace("{content}", content[-8000:])
                response = await client.post(
                    f"{deepseek_base_url()}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {deepseek_api_key()}", "Content-Type": "application/json"},
                    json={"model": deepseek_model(), "messages": [
                        {"role": "system", "content": "你是一位资深小说编辑，擅长从文本中提取结构化信息。"},
                        {"role": "user", "content": prompt}
                    ], "max_tokens": 4000, "temperature": 0.2},
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
        prompt = MEMORY_INCREMENTAL_PROMPT.format(
            chapter_content=chapter_text,
            existing_memory=existing[-3000:] if len(existing) > 3000 else existing
        )

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
            matched = match_ai_label_to_chroma(ai_cat)
            if matched:
                ChapterService._append_to_dimension(novel_unique_id, matched, new_content)
                system_logger.info(f"[记忆体] 增量追加 {matched}: +{len(new_content)} 字符")
            else:
                system_logger.warning(f"[记忆体] 未识别的AI维度标签: {ai_cat}")

        system_logger.info(f"[记忆体] 章节 {chapter_name} 增量更新完成")


    # ----------------------------------------------------------------
    #  全量记忆体：逐章提取 → 本地代码合并去重 → 存ChromaDB
    # ----------------------------------------------------------------

    @staticmethod
    def _aggregate_memory_by_code(settings_text: str, chapter_summaries: list) -> str:
        """本地代码合并记忆体（不调 AI）：逐章提取结果按维度去重合并"""
        # 从统一配置构建 (name, [aliases], title, dedup)
        DIMENSIONS = []
        for chroma_key, frontend_key, _, dedup in MEMORY_DIMENSION_DEFS:
            if chroma_key == "作品设定":
                continue
            aliases = [frontend_key]
            # 补充常用别名（代码解析用）
            if chroma_key == "功法技能法宝":
                aliases.append("功法技能")
            elif chroma_key == "组织势力":
                aliases.append("组织")
            elif chroma_key == "时间线":
                aliases.append("时间")
            elif chroma_key == "伏笔悬念":
                aliases.append("伏笔")
            DIMENSIONS.append((chroma_key, aliases, f"【{chroma_key}】", dedup))
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

                info = await ChapterService.extract_chapter_info(full_text, chapter_name)

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
    async def _ensure_memory_chain(novel_unique_id: str, db: Session = None, current_chapter_num: int = 1) -> str:
        """三数据源完整性校验 + 记忆体加载

        对当前章节号之前的所有已发布章节，逐一检查 TXT/Redis：
        - TXT 文件存在 → ✅
        - Redis 含该章节条目 → ✅
        任一缺失：从 TXT 读取内容 → AI 提取维度信息 → 写入 Redis

        最终返回完整的记忆体文本。
        """
        cn_unit = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
        def _parse_cn(s):
            if s.isdigit(): return int(s)
            v=c=0
            for ch in s:
                if ch=='十': v+=c*10 if c>0 else 10; c=0
                elif ch=='百': v+=c*100 if c>0 else 100; c=0
                elif ch in cn_unit: c=cn_unit[ch]
            return v+c

        def _chapter_num(name):
            m = re.search(r'第([^章]+)章', name or '')
            return _parse_cn(m.group(1)) if m else 99999

        # 获取所有已发布章节
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id) if db else []
        published = [c for c in all_chapters if c.is_published]
        # 筛选序号 < current_chapter_num 的章节
        prev_chapters = [c for c in published if _chapter_num(c.chapter_name) < current_chapter_num]
        prev_chapters.sort(key=lambda c: _chapter_num(c.chapter_name))

        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        r = _redis()
        mem_key = ChapterService._memory_key(novel_unique_id)

        # ============================================================
        # 第一遍：识别所有需要修复的章节，收集内容和概要
        # ============================================================
        repair_candidates = []  # [(ch_name, content, summary), ...]
        for ch in prev_chapters:
            ch_num = _chapter_num(ch.chapter_name)
            ch_name = ch.chapter_name

            # 检查 1: MySQL 章节记录是否存在
            from app.models.chapter import Chapter as ChapterModel
            mysql_ok = db.query(ChapterModel).filter(
                ChapterModel.chapter_unique_id == ch.chapter_unique_id
            ).first() is not None

            # 检查 2: Redis
            redis_ok = False
            if r and r.ping():
                for cat in get_memory_category_names():
                    val = r.hget(mem_key, cat) or ""
                    if ch_name in val:
                        redis_ok = True
                        break

            status = f"MySQL={'✅' if mysql_ok else '❌'} Redis={'✅' if redis_ok else '❌'}"
            if mysql_ok and redis_ok:
                system_logger.info(f"[三源校验] 第{ch_num}章 {ch_name}: {status} — 通过")
                continue

            system_logger.warning(f"[三源校验] 第{ch_num}章 {ch_name}: {status} — 开始修复")
            content = ChapterService._read_chapter_content_from_file(
                novel_unique_id, ch.chapter_name, ch.chapter_unique_id
            )
            if not content:
                system_logger.error(f"[三源校验] 第{ch_num}章 {ch_name}: 无内容可提取，跳过")
                continue

            repair_candidates.append((ch_name, content, ch.chapter_summary or ""))

        # ============================================================
        # 第二遍：根据 memory_extract_threads 并发提取 + 串行写入 Redis
        # ============================================================
        if repair_candidates:
            import asyncio
            from app.config import get as cfg
            max_concurrency = cfg("chromadb.memory_extract_threads", 10)
            sem = asyncio.Semaphore(max_concurrency)

            async def _extract_only(chapter_name: str, content: str, summary: str) -> tuple:
                """仅做 AI 提取，不写 Redis"""
                async with sem:
                    info_data = {}
                    try:
                        async with httpx.AsyncClient(timeout=120) as client:
                            prompt = LIGHT_EXTRACT_PROMPT.replace("{content}", content[-8000:])
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
                                    "max_tokens": 4000, "temperature": 0.2
                                },
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                text = data["choices"][0]["message"]["content"]
                                info_data = ChapterService._parse_extract_result(text)
                    except Exception as e:
                        system_logger.error(f"[并发修复] AI提取异常 {chapter_name}: {e}")
                    return chapter_name, info_data

            # 并发 AI 提取
            system_logger.info(
                f"[三源校验] 开始并发修复 {len(repair_candidates)} 章记忆体"
                f"（并发数={max_concurrency}）"
            )
            results = await asyncio.gather(*[
                _extract_only(name, ct, sm)
                for name, ct, sm in repair_candidates
            ])

            # 串行写入 Redis（避免并发 HSET 覆盖）
            written = 0
            for ch_name, info_data in results:
                if info_data:
                    ChapterService.save_extracted_to_memory(novel_unique_id, info_data, ch_name)
                    written += 1

            system_logger.info(
                f"[三源校验] 修复完成: 共提取 {len(results)} 章，"
                f"写入 Redis {written} 章"
            )

        # 最终加载记忆体
        return await ChapterService._ensure_memory(novel_unique_id, db)

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

    @staticmethod
    async def extract_chapter_info(content: str, chapter_name: str = "") -> dict:
        """
        从章节内容中 AI 提取关键信息（轻量级，不存记忆体）
        返回结构化 dict 供前端展示
        使用内容哈希缓存避免重复调用DeepSeek
        """
        if not content or len(content) < 50:
            return {"success": True, "data": {"人物": "", "组织": "", "功法技能": "",
                     "关键事件": "", "地点": "", "时间": "",
                     "关键物品": "", "实力变化": "", "伏笔": ""}}

        # 内容哈希缓存：相同内容直接返回缓存结果
        import hashlib
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        cache_key = f"extract:info:{content_hash}"
        r = _redis()
        if r:
            cached = r.get(cache_key)
            if cached:
                system_logger.info(f"[提取缓存] 命中内容哈希缓存: {chapter_name} hash={content_hash[:12]}")
                return cached

        # 截取内容：短章节全取，超长取前5000+后3000（覆盖开头和结尾关键事件）
        content_len = len(content)
        if content_len <= 8000:
            snippet = content
        else:
            snippet = content[:5000] + "\n...\n" + content[-3000:]

        prompt = LIGHT_EXTRACT_PROMPT.replace("{content}", snippet)

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

            final_result = {"success": True, "data": result}
            # 写入缓存（TTL 1小时）
            if r:
                r.set(cache_key, final_result, ttl=3600)
            return final_result
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
        # 自动编号：有"第X章"前缀则校验 X 是否匹配，不匹配则修正
        front_num_match = re.match(r'^第(.+?)章', chapter_name)
        if front_num_match:
            front_num = front_num_match.group(1)
            if front_num != chinese_num:
                system_logger.warning(
                    f"[章节命名] 前端编号 '{front_num}' 与实际编号 '{chinese_num}' 不匹配，自动修正"
                )
                chapter_name = re.sub(r'^第.+?章\s*', f'第{chinese_num}章 ', chapter_name)
        else:
            chapter_name = f"第{chinese_num}章 {chapter_name}"

        # ============================================================
        # 三数据源完整性校验：逐章检查 TXT/MySQL/Redis，缺失则从 TXT 补
        # ============================================================
        memory_body = await ChapterService._ensure_memory_chain(novel_unique_id, db, chapter_num)
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
        # 只取已发布的章节，按章节号排序（不是 created_at）
        published_chapters = [c for c in all_chapters if c.is_published]
        # 按章节名中的数字排序：第一章、第二章...
        def _chapter_sort_key(ch):
            m = re.search(r'第([一二三四五六七八九十百零\d]+)章', ch.chapter_name or '')
            if m:
                num_str = m.group(1)
                if num_str.isdigit():
                    return int(num_str)
                # 正确解析中文数字：二十=20，二十一=21，一百二十=120
                cn_unit = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
                val = 0
                cur = 0
                for ch in num_str:
                    if ch == '十':
                        val += cur * 10 if cur > 0 else 10
                        cur = 0
                    elif ch == '百':
                        val += cur * 100 if cur > 0 else 100
                        cur = 0
                    elif ch in cn_unit:
                        cur = cn_unit[ch]
                val += cur
                return val if val > 0 else 9999
            return 9999
        published_chapters.sort(key=_chapter_sort_key)

        last_chapter_ending = ""
        last_chapter_full = ""
        previous_text_for_duplicate = ""

        if published_chapters:
            last_ch = published_chapters[-1]
            system_logger.info(f"[章节生成] 续写锚点：基于已发布最后一章 [{last_ch.chapter_name}]")
            last_chapter_full = ChapterService._read_chapter_content_from_file(
                novel_unique_id, last_ch.chapter_name, last_ch.chapter_unique_id
            )

            if last_chapter_full:
                last_chapter_ending = last_chapter_full[-500:]
                system_logger.info(f"[章节生成] 续写锚点：上一章末尾500字（开头: {last_chapter_ending[:80]}...）")

            # 取最近3章用于去重检测
            recent_3 = published_chapters[-3:] if len(published_chapters) >= 3 else published_chapters
            for ch in recent_3:
                content = ChapterService._read_chapter_content_from_file(
                    novel_unique_id, ch.chapter_name, ch.chapter_unique_id
                )
                if content:
                    previous_text_for_duplicate += content + "\n"

        # ============================================================
        # 章节概要 → 事件清单（给 AI 的硬边界）
        # ============================================================
        summary_narrative = ""
        if chapter_summary:
            sentences = re.split(r'[，,。.！!？?；;]', chapter_summary)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
            if sentences:
                summary_narrative = "；".join(sentences) + "。"

        # ============================================================
        # 构建 Prompt：GENERATE_CREATIVE_DIRECTION + 末尾500字 + 情感指南
        # ============================================================
        prompt = GENERATE_CREATIVE_DIRECTION.format(
            memory_body=memory_body or "暂无已写章节记忆体",
            truth_context="无",
            settings_text=settings_text or "未设定",
            context_summary=f"上一章末尾（从这里接着写）：\n{last_chapter_ending}" if last_chapter_ending else "这是第一章，无需承接",
            event_checklist=chapter_summary or "根据前文自然推进剧情",
            summary_narrative=summary_narrative or "根据前文自然推进剧情",
        )
        prompt += "\n\n" + EMOTIONAL_WRITING_GUIDE

        system_prompt = GENERATE_SYSTEM_PROMPT

        # 追加字数指令到 prompt 末尾（硬性要求）
        min_words = max(word_count - 500, 800)
        prompt += f"\n\n🔴 字数硬性要求：本章必须写 {min_words}~{word_count} 字。开头第一句就是正文，结尾最后一句话写完立刻停笔。绝对禁止凑字数或水文字。"
        prompt += f"\n章节标题：「{chapter_name}」"

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
                            "max_tokens": int(word_count * 1.8),
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
                        # 只有明显偏短（不足要求的60%）才重试
                        min_acceptable = max(int(word_count * 0.6), 500)
                        if actual_words < min_acceptable and attempt < MAX_RETRIES:
                            system_logger.warning(
                                f"[重试 {attempt+1}] {chapter_name} 仅{actual_words}字"
                                f"，不足要求的60%({min_acceptable})"
                            )
                            continue
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
        # 后处理：硬边界截断 —— 概要最后一个事件之后的内容全删
        # ============================================================
        generated_text = ChapterService._trim_to_summary_boundary(
            generated_text, chapter_summary or ""
        )

        # ============================================================
        # 后处理：字数上限截断（最多允许超出 10%）
        # ============================================================
        max_allowed = int(word_count * 1.1)
        if len(generated_text) > max_allowed:
            before_len = len(generated_text)
            trimmed = generated_text[:max_allowed]
            # 在最后一个句号/感叹号/问号处截断
            last_end = max(trimmed.rfind('。'), trimmed.rfind('！'),
                           trimmed.rfind('？'), trimmed.rfind('\n'))
            if last_end > max_allowed * 0.7:  # 找到了合适的截断点
                generated_text = trimmed[:last_end + 1]
            else:
                generated_text = trimmed
            system_logger.info(
                f"[字数截断] {chapter_name} 从 {before_len} 字截到 {len(generated_text)} 字"
            )

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
                chapter_number=chapter_num,
                chapter_summary=chapter_summary,
                word_count=actual_word_count,
                is_published=0,
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

        # 获取所有已发布章节，按章节号排序，取当前章之前的所有章节
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        published_chapters = [c for c in all_chapters if c.is_published and c.chapter_unique_id != chapter_unique_id]
        # 按章节名中的数字排序
        def _chapter_sort_key(ch):
            m = re.search(r'第([一二三四五六七八九十百零\d]+)章', ch.chapter_name or '')
            if m:
                num_str = m.group(1)
                if num_str.isdigit():
                    return int(num_str)
                # 正确解析中文数字：二十=20，二十一=21，一百二十=120
                cn_unit = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
                val = 0
                cur = 0
                for ch in num_str:
                    if ch == '十':
                        val += cur * 10 if cur > 0 else 10
                        cur = 0
                    elif ch == '百':
                        val += cur * 100 if cur > 0 else 100
                        cur = 0
                    elif ch in cn_unit:
                        cur = cn_unit[ch]
                val += cur
                return val if val > 0 else 9999
            return 9999
        published_chapters.sort(key=_chapter_sort_key)

        # 找到当前章节序号，只取序号在它之前的章节
        cur_num = _chapter_sort_key(chapter)
        prev_chapters_for_gen = [c for c in published_chapters if _chapter_sort_key(c) < cur_num]

        # 构建记忆体：三数据源完整性校验（和 generate_with_ai 一致）
        memory_body = await ChapterService._ensure_memory_chain(novel_unique_id, db, cur_num)

        # 上一章末尾内容（用于无缝衔接）
        last_chapter_content = ""
        if prev_chapters_for_gen:
            last_ch = prev_chapters_for_gen[-1]
            last_chapter_content = ChapterService._read_chapter_content_from_file(
                novel_unique_id, last_ch.chapter_name, last_ch.chapter_unique_id
            )

        # 构建自然语言概要
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
            context_summary=f"上一章末尾（从这里接着写）：\n{last_chapter_content[-500:]}" if last_chapter_content else "这是第一章，无需承接",
            event_checklist=chapter_summary or "根据前文自然推进剧情",
            summary_narrative=summary_narrative or "根据前文自然推进剧情",
        )
        prompt += "\n\n" + EMOTIONAL_WRITING_GUIDE
        prompt += f"\n\n本章字数：{word_count}字左右。章节标题：「{chapter_name}」"

        system_prompt = GENERATE_SYSTEM_PROMPT

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
                            {"role": "system", "content": system_prompt},
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

        # 读取当前章节已有内容：优先从本地 TXT 文件，兜底 DB
        existing_content = ChapterService._read_chapter_content_from_file(
            chapter.novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id
        )

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

                # 更新数据库字数
                ChapterDAO.update(db, chapter, word_count=len(new_content))

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
        发布章节：三阶段保存（txt → MySQL → ChromaDB）
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
        # 阶段3：写入 ChromaDB → 读回验证
        # ============================================================
        t3_ok = False
        try:
            # 映射前端字段 → ChromaDB 维度名（统一配置）
            field_map = get_frontend_to_chroma_map()

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
                for chroma_cat in field_map.values():
                    try:
                        val = r.hget(key, chroma_cat)
                        pre_lengths[chroma_cat] = len(val) if val else 0
                    except Exception:
                        pre_lengths[chroma_cat] = 0

            # 写入（使用自然语言转换，不再存管道符）
            saved_count = 0
            written_dimensions = []
            for front_field, chroma_cat in field_map.items():
                raw_val = info_data.get(front_field, "")
                if not raw_val or raw_val == "无":
                    continue
                natural = ChapterService._pipe_to_natural(front_field, raw_val, chapter_name)
                if not natural:
                    continue
                ChapterService._append_to_dimension(novel_unique_id, chroma_cat, natural)
                written_dimensions.append(chroma_cat)
                saved_count += 1
                system_logger.info(f"[发布-验证] 记忆体写入 {chroma_cat}: +{len(natural)}字")

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
                for chroma_cat in written_dimensions:
                    try:
                        post_text = r.hget(key, chroma_cat) or ""
                        post_len = len(post_text)
                        pre_len = pre_lengths.get(chroma_cat, 0)

                        # 验证：数据增长了，且包含本章名称
                        if post_len > pre_len and chapter_name in post_text:
                            system_logger.info(f"[发布-验证] ✅ 记忆体 {chroma_cat}: {pre_len}→{post_len}字 (+{post_len-pre_len}) | 含章节名")
                        else:
                            verify_failures.append(chroma_cat)
                            system_logger.error(f"[发布-验证] ❌ 记忆体 {chroma_cat}: 验证失败 | pre={pre_len} post={post_len} | 含章节名={chapter_name in post_text}")
                    except Exception as ve:
                        verify_failures.append(chroma_cat)
                        system_logger.error(f"[发布-验证] ❌ 记忆体 {chroma_cat}: 读回异常 {ve}")

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
                    system_logger.info(f"[发布-验证] ✅ ChromaDB 全部验证通过: {written_dimensions}")

        except Exception as e:
            system_logger.error(f"[发布-验证] ❌ ChromaDB阶段异常: {e}")
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
                r.delete_pattern("interactions:*")
            except Exception:
                pass

        system_logger.info(
            f"[发布-验证] 🎉 三阶段全部验证通过 | "
            f"章节={chapter_name} | "
            f"txt={os.path.getsize(chapter_file) if chapter_file and os.path.exists(chapter_file) else '?'}字节 | "
            f"MySQL=is_published:{t2_ok} | "
            f"ChromaDB={saved_count if 'saved_count' in dir() else 0}维度"
        )
        return success(
            {"chapter_unique_id": chapter_unique_id, "chapter_name": chapter_name},
            "章节发布成功，已同步到作品圈"
        )

    @staticmethod
    def update_chapter(db: Session, chapter_unique_id: str,
                       chapter_name: str = None, chapter_summary: str = None) -> dict:
        """更新已存在的章节名称或概要
        :param db: 数据库会话
        :param chapter_unique_id: 章节唯一ID
        :param chapter_name: 新章节名称
        :param chapter_summary: 新章节概要
        :return: 操作结果
        """
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
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
        r3 = _redis()
        if r3:
            r3.delete_pattern(f"chapters:*")
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

        # 4. 从 ChromaDB 记忆体中定点删除该章节条目
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
        """Worker handler：从章节内容中 AI 提取关键信息"""
        content = task_data.get("content", "")
        chapter_name = task_data.get("chapter_name", "")
        try:
            result = run_async(ChapterService.extract_chapter_info, content, chapter_name)
            return result
        except Exception as e:
            system_logger.error(f"[Worker-extract] 异常: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _worker_generate(task_id: str, task_data: dict) -> dict:
        """Worker handler：AI 生成章节正文"""
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            result = run_async(
                ChapterService.generate_with_ai,
                db,
                novel_unique_id=task_data["novel_unique_id"],
                user_id=task_data["user_id"],
                chapter_name=task_data["chapter_name"],
                characters_involved=task_data.get("characters_involved"),
                organizations=task_data.get("organizations"),
                locations=task_data.get("locations"),
                skills=task_data.get("skills"),
                word_count=task_data.get("word_count", 2000),
                chapter_summary=task_data.get("chapter_summary"),
                created_by=task_data.get("created_by"),
            )
            # 标准化返回格式
            if result.get("状态码") == 200:
                return {"success": True, "data": result.get("数据")}
            return {"success": False, "error": result.get("消息", "生成失败")}
        except Exception as e:
            system_logger.error(f"[Worker-generate] 异常: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    def _worker_regenerate(task_id: str, task_data: dict) -> dict:
        """Worker handler：AI 重新生成章节"""
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            result = run_async(
                ChapterService.regenerate_with_ai,
                db,
                chapter_unique_id=task_data["chapter_unique_id"],
                user_id=task_data["user_id"],
                word_count=task_data.get("word_count", 2000),
                chapter_summary=task_data.get("chapter_summary"),
            )
            if result.get("状态码") == 200:
                return {"success": True, "data": result.get("数据")}
            return {"success": False, "error": result.get("消息", "重新生成失败")}
        except Exception as e:
            system_logger.error(f"[Worker-regenerate] 异常: {e}")
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
                word_count=task_data.get("word_count", 800),
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
    def _worker_reset_memory(task_id: str, task_data: dict) -> dict:
        """Worker handler：重置作品 Redis 记忆体"""
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            result = ChapterService.reset_and_rebuild_memory(
                task_data["novel_unique_id"], db
            )
            return result
        except Exception as e:
            system_logger.error(f"[Worker-reset-memory] 异常: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()


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
