import json
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

NOVEL_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "novel_structure_data")
os.makedirs(NOVEL_DATA_PATH, exist_ok=True)


def _redis():
    return redis_mod.redis_client


class ChapterService:

    @staticmethod
    def _get_novel_settings(novel_unique_id: str) -> dict:
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        settings_file = os.path.join(novel_dir, "作品设定.txt")
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                return {"content": f.read(), "path": settings_file}
        return {"content": "", "path": ""}

    @staticmethod
    def _get_last_chapter_content(db: Session, novel_unique_id: str, exclude_chapter_name: str = None) -> str:
        """从数据库按 created_at 顺序取上一章的正文内容"""
        chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        if not chapters or len(chapters) < 2:
            return ChapterService._get_last_chapter_from_file(novel_unique_id, exclude_chapter_name)
        sorted_chapters = sorted(chapters, key=lambda c: c.created_at or "")
        candidates = [c for c in sorted_chapters if c.chapter_name != exclude_chapter_name]
        if not candidates:
            return ""
        last = candidates[-1]
        if last.content:
            return last.content
        novel_dir = os.path.join(NOVEL_DATA_PATH, last.novel_unique_id)
        chapter_file = os.path.join(novel_dir, f"{last.chapter_name}_{last.chapter_unique_id}.txt")
        if os.path.exists(chapter_file):
            with open(chapter_file, "r", encoding="utf-8") as f:
                txt = f.read().strip()
                if txt.startswith("{"):
                    return ""
                return txt
        return ""

    @staticmethod
    def _get_last_chapter_from_file(novel_unique_id: str, exclude_chapter_name: str = None) -> str:
        """从本地文件读取最后章节内容（兼容旧数据）"""
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        if not os.path.exists(novel_dir):
            return ""
        txt_files = sorted(
            [f for f in os.listdir(novel_dir) if f.endswith(".txt") and f != "作品设定.txt"],
            key=lambda x: os.path.getmtime(os.path.join(novel_dir, x)),
        )
        for fname in reversed(txt_files):
            if exclude_chapter_name and fname.startswith(exclude_chapter_name + "_"):
                continue
            filepath = os.path.join(novel_dir, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                txt = f.read().strip()
                if txt.startswith("{"):
                    continue
                return txt
        return ""

    # ==================== 记忆体系统 ====================

    @staticmethod
    def _load_memory(novel_unique_id: str) -> str:
        """从向量数据库加载记忆体"""
        if chroma_memory:
            memories = chroma_memory.search_memory(
                f"记忆体:{novel_unique_id}", n_results=1
            )
            for m in memories:
                if m.get("metadata", {}).get("doc_type") == "novel_memory":
                    return m["document"]
        return ""

    @staticmethod
    def _save_memory(novel_unique_id: str, memory_text: str):
        """保存记忆体到向量数据库（覆盖写入）"""
        if chroma_memory:
            doc_id = f"memory:{novel_unique_id}"
            # 删除旧记忆
            chroma_memory.delete_memory(doc_id)
            # 写入新记忆
            chroma_memory.collection.add(
                documents=[memory_text],
                ids=[doc_id],
                metadatas=[{"doc_type": "novel_memory", "novel_unique_id": novel_unique_id}]
            )

    @staticmethod
    def _build_memory(db: Session, novel_unique_id: str) -> str:
        """
        全量构建记忆体：读取所有章节内容（DB + 本地文件兜底），
        生成结构化的记忆摘要，存入向量数据库。
        """
        novel_settings = ChapterService._get_novel_settings(novel_unique_id)
        chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        sorted_chapters = sorted(chapters, key=lambda c: c.created_at or "")
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)

        lines = []
        lines.append("=" * 40)
        lines.append("【作品全局设定】")
        lines.append(novel_settings.get('content', '无'))

        if sorted_chapters:
            lines.append("")
            lines.append("=" * 40)
            lines.append("【已写章节记忆】")
            for i, ch in enumerate(sorted_chapters, 1):
                content = ch.content or ""
                # DB content 为空时从本地文件兜底
                if not content:
                    ch_file = os.path.join(novel_dir, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
                    if os.path.exists(ch_file):
                        with open(ch_file, "r", encoding="utf-8") as f:
                            content = f.read()
                            if content.strip().startswith("{"):
                                content = ""

                summary_parts = [f"第{i}章 {ch.chapter_name}"]
                if ch.chapter_summary:
                    summary_parts.append(f"概要: {ch.chapter_summary}")
                if content:
                    # 取前400字（覆盖更多情节信息）
                    snippet = content[:400].replace("\n", " ").strip()
                    summary_parts.append(f"内容: {snippet}...")
                lines.append(" | ".join(summary_parts))

        memory = "\n".join(lines)
        # 存入向量数据库
        ChapterService._save_memory(novel_unique_id, memory)
        return memory

    @staticmethod
    def _ensure_memory(db: Session, novel_unique_id: str) -> str:
        """获取记忆体：向量库有则直接用，没有则全量构建"""
        memory = ChapterService._load_memory(novel_unique_id)
        if memory:
            return memory
        return ChapterService._build_memory(db, novel_unique_id)

    @staticmethod
    def _update_memory(novel_unique_id: str, chapter_name: str,
                       chapter_summary: str, generated_text: str):
        """增量更新记忆体：从向量库加载 → 追加新章节 → 写回向量库"""
        memory = ChapterService._load_memory(novel_unique_id)
        if not memory:
            # 记忆体不存在（不应该发生，但兜底）
            return

        snippet = generated_text[:400].replace("\n", " ").strip()
        new_entry = f"\n{chapter_name}"
        if chapter_summary:
            new_entry += f" | 概要: {chapter_summary}"
        new_entry += f" | 内容: {snippet}..."

        memory += new_entry
        ChapterService._save_memory(novel_unique_id, memory)

    @staticmethod
    def create_chapter(db: Session, novel_unique_id: str, user_id: int,
                       chapter_name: str, characters_involved: str = None,
                       organizations: str = None, locations: str = None,
                       skills: str = None, word_count: int = 0,
                       chapter_summary: str = None, created_by: str = None) -> dict:
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

    @staticmethod
    async def generate_with_ai(db: Session, novel_unique_id: str, user_id: int,
                               chapter_name: str, characters_involved: str = None,
                               organizations: str = None, locations: str = None,
                               skills: str = None, word_count: int = 2000,
                               chapter_summary: str = None,
                               created_by: str = None) -> dict:
        # 自动编号：统计已有章节数 + 1，转中文数字
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
        
        # 如果用户没手动写"第X章"，自动加上
        import re
        if not re.match(r'^第.+章', chapter_name):
            chapter_name = f"第{chinese_num}章 {chapter_name}"
        
        novel_settings = ChapterService._get_novel_settings(novel_unique_id)

        # ===== 记忆体：一次加载，终身复用 =====
        memory_body = ChapterService._ensure_memory(db, novel_unique_id)
        # 上一章末尾内容（用于紧密衔接）
        last_chapter = ChapterService._get_last_chapter_content(db, novel_unique_id, chapter_name)

        chapter_setting = f"""本章设定：
章节名称：{chapter_name}
本章概要：{chapter_summary or '无'}
涉及人物：{characters_involved or '无'}
涉及组织：{organizations or '无'}
涉及地点：{locations or '无'}
涉及技能：{skills or '无'}
目标字数：{word_count}字"""

        prompt = f"""你是一个专业的小说写作助手。请根据以下记忆和设定生成小说章节内容。

【作品记忆体】（已写章节的全貌）
{memory_body}

【上一章节结尾】（必须紧密承接）
{last_chapter[-2500:] if last_chapter else '这是第一章，无需承接'}

{chapter_setting}

要求：
1. 必须承接上一章的结尾，故事连续、人物性格一致
2. 如果上一章结尾有悬念/事件，本章必须自然延续
3. 字数控制在{word_count}字左右
4. 语言流畅，情节合理，描写生动
5. 只需输出章节正文，不要额外的说明文字"""

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
                            {"role": "system", "content": "你是一个专业的小说写作助手。"},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": word_count * 2,
                        "temperature": 0.8
                    }
                )
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    return fail("AI生成失败: " + str(data.get("error", {}).get("message", "未知错误")), code=500)

                generated_text = data["choices"][0]["message"]["content"]

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
                    word_count=len(generated_text),
                    chapter_summary=chapter_summary,
                    is_published=0,
                    content=generated_text,
                    created_by=created_by
                )

                novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
                os.makedirs(novel_dir, exist_ok=True)
                chapter_file = os.path.join(novel_dir, f"{chapter_name}_{chapter_unique_id}.txt")
                with open(chapter_file, "w", encoding="utf-8") as f:
                    f.write(generated_text)

                if chroma_memory:
                    full_text = f"[{chapter_name}] {chapter_summary or ''}\n{generated_text[:2000]}"
                    chroma_memory.add_memory(
                        doc_id=f"{novel_unique_id}_{chapter_unique_id}",
                        text=full_text,
                        metadata={"novel_unique_id": novel_unique_id, "chapter_name": chapter_name, "word_count": len(generated_text)}
                    )

                # ===== 增量更新记忆体 =====
                ChapterService._update_memory(
                    novel_unique_id, chapter_name,
                    chapter_summary or '', generated_text
                )

                return success({
                    "chapter_unique_id": chapter_unique_id,
                    "chapter_name": chapter_name,
                    "word_count": len(generated_text)
                }, f"{chapter_name} 章节内容生成成功")

            except httpx.TimeoutException:
                return fail("AI接口调用超时，请重试", code=500)
            except Exception as e:
                return fail(f"AI生成失败: {str(e)}", code=500)

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
        memory_body = ChapterService._ensure_memory(db, chapter.novel_unique_id)

        prompt = f"""你是一个专业的小说写作助手。请根据记忆体和已写内容，续写本章节。

【作品记忆体】
{memory_body}

【本章信息】
章节名称：{chapter.chapter_name}
本章概要：{chapter.chapter_summary or '无'}
当前已写内容（末尾）：
{context_content}

【续写要求】
1. 内容需紧密承接上文，保持情节连贯
2. 人物性格、世界观设定保持一致
3. 续写 {word_count} 字左右
4. 只需输出续写内容，不要重复已有的文字，不要加"续写"等标题"""

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
                            {"role": "system", "content": "你是一个专业的小说写作助手，擅长续写小说章节。"},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": word_count * 2,
                        "temperature": 0.8
                    }
                )
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    return fail("AI续写失败: " + str(data.get("error", {}).get("message", "未知错误")), code=500)

                generated_text = data["choices"][0]["message"]["content"]

                # 追加续写内容到文件（兼容）和数据库
                new_content = existing_content + "\n\n" + generated_text
                novel_dir = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id)
                os.makedirs(novel_dir, exist_ok=True)
                chapter_file = os.path.join(novel_dir, f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
                with open(chapter_file, "w", encoding="utf-8") as f:
                    f.write(new_content)

                # 更新数据库字数 + 内容
                ChapterDAO.update(db, chapter, word_count=len(new_content), content=new_content)

                return success({
                    "chapter_unique_id": chapter_unique_id,
                    "chapter_name": chapter.chapter_name,
                    "continued_text": generated_text,
                    "word_count": len(new_content),
                    "total_word_count": len(new_content)
                }, f"续写成功，新增 {len(generated_text)} 字")

            except httpx.TimeoutException:
                return fail("AI接口调用超时，请重试", code=500)
            except Exception as e:
                return fail(f"AI续写失败: {str(e)}", code=500)

    @staticmethod
    def get_drafts(db: Session, user_id: int) -> dict:
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
                "created_at": ch.created_at.isoformat() if ch.created_at else None
            })
        if r:
            r.set(cache_key, result)
        return success(result)

    @staticmethod
    def publish_chapter(db: Session, chapter_unique_id: str, content: str = None) -> dict:
        """发布章节：保存内容到txt、标记已发布、同步到作品圈"""
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
        return success(None, "章节更新成功")

    @staticmethod
    def delete_chapter(db: Session, chapter_unique_id: str) -> dict:
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)
        chapter_file = os.path.join(NOVEL_DATA_PATH, chapter.novel_unique_id,
                                    f"{chapter.chapter_name}_{chapter.chapter_unique_id}.txt")
        if os.path.exists(chapter_file):
            os.remove(chapter_file)

        # 删除向量数据库中的记录
        if chroma_memory:
            chroma_doc_id = f"{chapter.novel_unique_id}_{chapter_unique_id}"
            chroma_memory.delete_memory(chroma_doc_id)

        ChapterDAO.delete(db, chapter_unique_id)
        r4 = _redis()
        if r4:
            r4.delete_pattern(f"chapters:*")
        return success(None, "章节删除成功")

    @staticmethod
    def get_novel_chapters(db: Session, novel_unique_id: str) -> dict:
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
