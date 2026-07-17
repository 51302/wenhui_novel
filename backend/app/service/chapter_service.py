import json
import re
import uuid
import os
import httpx
from sqlalchemy.orm import Session
from app.dao.chapter_dao import ChapterDAO
from app.utils.response import success, fail
import app.utils.redis_cache as redis_mod
from app.utils.chroma_client import novel_memory_manager
from app.config import deepseek_api_key, deepseek_base_url, deepseek_model
from app.utils.logger import system_logger
from app.prompts.chapter_prompts import (
    AGGREGATE_MEMORY_PROMPT, LIGHT_EXTRACT_PROMPT,
    GENERATE_CREATIVE_DIRECTION, GENERATE_WRITING_EXAMPLES, GENERATE_CREATIVE_BOUNDARIES,
    GENERATE_SYSTEM_PROMPT, GENERATE_CHAPTER_SETTING,
    REGENERATE_PROMPT, REGENERATE_SYSTEM_PROMPT,
    CONTINUE_PROMPT, CONTINUE_SYSTEM_PROMPT,
    EMOTIONAL_WRITING_GUIDE,
)

NOVEL_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "novel_structure_data")
os.makedirs(NOVEL_DATA_PATH, exist_ok=True)


def _redis():
    """获取Redis客户端实例"""
    return redis_mod.redis_client


class ChapterService:

    # ============================================================
    # 前文摘要 & 连续性检查
    # ============================================================

    @staticmethod
    def _parse_light_extract(ai_output: str) -> dict:
        """解析 LIGHT_EXTRACT_PROMPT 的 AI 返回结果 → dict"""
        result = {}
        current_key = ""
        for line in ai_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r'^[-—]{1,3}\s*(.+?)\s*[-—]{0,3}$', line)
            if not m:
                m = re.match(r'^【(.+?)】$', line)
            if not m:
                m = re.match(r'^\*\*(.+?)\*\*$', line)
            if not m:
                m = re.match(r'^([^\|]+)：$', line)
            if m:
                current_key = m.group(1).strip()
                if current_key not in result:
                    result[current_key] = []
            elif current_key:
                if line not in ("无", "无新增", "无新"):
                    result[current_key].append(line)
        # list → string
        for key in list(result.keys()):
            result[key] = "\n".join(result[key])
        return result

    @staticmethod
    def _detect_dead_characters(last_chapter_ending: str) -> str:
        """扫描上一章结尾，提取包含死亡/消散关键词的关键句子作为硬约束证据"""
        if not last_chapter_ending:
            return ""

        death_keywords = ["消散", "死了", "化作光点", "化成光点", "融进", "散尽",
                          "消失了", "散去了", "散成", "彻底散了", "身体已经散",
                          "再也分不出", "带走了", "不会回来了", "永远地闭上了"]

        evidence_lines = []
        lines = last_chapter_ending.split("\n")
        for i, line in enumerate(lines):
            for kw in death_keywords:
                if kw in line:
                    # 取当前行 + 前后各1行作为证据
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    evidence = "\n".join(lines[start:end]).strip()
                    if evidence not in evidence_lines:
                        evidence_lines.append(evidence)
                    break

        if evidence_lines:
            return "\n".join(f">>> {e}" for e in evidence_lines[:5])  # 最多5条证据
        return ""

    @staticmethod
    def _get_novel_settings(novel_unique_id: str) -> dict:
        """读取作品设定文件内容（含剧情发展路线）"""
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        settings_file = os.path.join(novel_dir, "作品设定.txt")
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                return {"content": f.read(), "path": settings_file}
        return {"content": "", "path": ""}


    # ==================== 记忆体系统（AI提取关键信息 → 向量数据库） ====================

    @staticmethod
    def _ensure_manager() -> bool:
        """确保 NovelMemoryStoreManager 已初始化"""
        import app.utils.chroma_client as mod_chroma
        if mod_chroma.novel_memory_manager is not None:
            return True
        try:
            from app.utils.chroma_client import NovelMemoryStoreManager
            persist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vector_db_data")
            mod_chroma.novel_memory_manager = NovelMemoryStoreManager(base_path=persist_path)
            system_logger.info("[记忆体] NovelMemoryStoreManager 懒加载成功")
            return True
        except Exception as e:
            system_logger.error(f"[记忆体] 管理器初始化失败: {e}")
            return False

    @staticmethod
    def _get_store(novel_unique_id: str):
        """获取指定书籍的独立 ChromaMemoryStore"""
        if not ChapterService._ensure_manager():
            return None
        import app.utils.chroma_client as mod_chroma
        return mod_chroma.novel_memory_manager.get_store(novel_unique_id)

    # ----------------------------------------------------------------
    #  记忆体存储：全量文档存储，不再按维度拆分
    # ----------------------------------------------------------------

    @staticmethod
    def _load_memory(novel_unique_id: str) -> str:
        """读取作品的完整记忆体，优先 ChromaDB，否则回退文件"""
        store = ChapterService._get_store(novel_unique_id)
        result_text = ""

        # 优先：读 ChromaDB 完整文档 memory:{novel_id}:full
        if store:
            try:
                results = store.collection.get(ids=[f"memory:{novel_unique_id}:full"])
                if results and results.get("documents") and results["documents"][0]:
                    result_text = results["documents"][0]
            except Exception:
                pass

        # 回退：读 记忆体.txt 文件
        if not result_text:
            novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
            memory_txt = os.path.join(novel_dir, "记忆体.txt")
            if os.path.exists(memory_txt):
                try:
                    with open(memory_txt, "r", encoding="utf-8") as f:
                        result_text = f.read()
                    system_logger.info(f"[记忆体] ChromaDB 为空，文件回退: {memory_txt} ({len(result_text)}字符)")
                except Exception as e:
                    system_logger.error(f"[记忆体] 文件回退失败: {e}")

        # 追加死亡角色警告
        if store:
            death_records = []
            try:
                all_data = store.collection.get()
                ids = all_data.get("ids") or []
                docs = all_data.get("documents") or []
                metas = all_data.get("metadatas") or []
                for i, doc_id in enumerate(ids):
                    if ":已死亡角色" in doc_id:
                        doc_text = docs[i] if i < len(docs) else ""
                        if doc_text:
                            ch = (metas[i] or {}).get("chapter_name", "") if i < len(metas) else ""
                            death_records.append(f"【{ch}】\n{doc_text}")
            except Exception:
                pass
            if death_records:
                dead_warning = ("🔴🔴🔴【以下角色已在之前章节中死亡/消散，绝不可让其活着出现！"
                                "只能以回忆/遗物方式写】\n\n" + "\n\n".join(death_records))
                result_text = dead_warning + "\n\n---\n\n" + (result_text or "")

        return result_text

    @staticmethod
    def _delete_chapter_memory(novel_unique_id: str, chapter_unique_id: str):
        """删除特定章节的记忆体数据，同时删除完整记忆体文档"""
        store = ChapterService._get_store(novel_unique_id)
        if not store:
            return
        try:
            prefix = f"memory:{novel_unique_id}:chapter:{chapter_unique_id}:"
            all_data = store.collection.get()
            to_delete = [id for id in (all_data.get("ids") or []) if id.startswith(prefix)]
            # 也删除完整记忆体文档，下次生成时自动重建
            full_id = f"memory:{novel_unique_id}:full"
            if full_id in (all_data.get("ids") or []):
                to_delete.append(full_id)
            if to_delete:
                store.collection.delete(ids=to_delete)
                system_logger.info(f"[记忆体] 已删除章节 {chapter_unique_id} 的 {len(to_delete)} 条记忆")
        except Exception as e:
            system_logger.error(f"[记忆体] 删除章节记忆失败: {e}")

    @staticmethod
    def _mark_dead_characters_in_memory(novel_unique_id: str, chapter_unique_id: str,
                                         chapter_name: str, actual_content: str):
        """扫描章节内容，将死亡证据永久写入记忆体，后续生成时自动加载为最醒目的警告"""
        if not actual_content:
            return
        death_evidence = ChapterService._detect_dead_characters(actual_content)
        if not death_evidence:
            return

        store = ChapterService._get_store(novel_unique_id)
        if not store:
            return

        death_doc_id = f"memory:{novel_unique_id}:chapter:{chapter_unique_id}:已死亡角色"
        try:
            store.collection.upsert(
                documents=[death_evidence],
                ids=[death_doc_id],
                metadatas=[{
                    "doc_type": "death_record",
                    "novel_unique_id": novel_unique_id,
                    "chapter_unique_id": chapter_unique_id,
                    "chapter_name": chapter_name,
                }]
            )
            system_logger.info(
                f"[记忆体] 已写入死亡记录: {chapter_name} ({death_doc_id})"
            )
        except Exception as e:
            system_logger.error(f"[记忆体] 写入死亡记录失败: {e}")

    # ================================================================
    # 记忆体完整性检查
    # ================================================================
    @staticmethod
    def _get_txt_chapter_set(novel_unique_id: str) -> set:
        """扫描 novel_structure_data 下所有有效的章节 txt 文件，返回 {章节名} 集合"""
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        if not os.path.isdir(novel_dir):
            return set()
        files = os.listdir(novel_dir)
        chapters = set()
        for f in files:
            if not f.endswith(".txt"):
                continue
            if f in ("作品设定.txt", "记忆体.txt"):
                continue
            name_part = f.rsplit("_", 1)[0] if "_" in f else f[:-4]
            chapters.add(name_part)
        return chapters

    @staticmethod
    def _parse_memory_chapter_count(memory_body: str) -> int:
        """从记忆体文本中解析已有章节数

        优先解析"当前已写N章"，否则数 === 第X章 === 的数量
        """
        if not memory_body:
            return 0
        import re
        match = re.search(r'当前已写(\d+)章', memory_body)
        if match:
            return int(match.group(1))
        count = len(re.findall(r'=== 第\d+章', memory_body))
        return count if count > 0 else 0

    @staticmethod
    def _check_memory_integrity(novel_unique_id: str, db: Session = None) -> dict:
        """三源完整性检查：MySQL章节数 == 本地txt数 == ChromaDB记忆体章节数

        三个数据源必须同时存在且数量一致，否则触发全量重建。

        返回值:
            {"ok": bool, "mysql": int, "txt": int, "chromadb": int,
             "missing": list, "detail": str}
        """
        # 1. MySQL 章节数
        mysql_count = 0
        if db:
            mysql_count = ChapterDAO.count_by_novel_id(db, novel_unique_id)

        # 2. 本地 txt 文件数
        txt_count = len(ChapterService._get_txt_chapter_set(novel_unique_id))

        # 3. ChromaDB 记忆体章节数
        chroma_count = 0
        store = ChapterService._get_store(novel_unique_id)
        if store:
            try:
                results = store.collection.get(ids=[f"memory:{novel_unique_id}:full"])
                if results and results.get("documents") and results["documents"][0]:
                    chroma_count = ChapterService._parse_memory_chapter_count(results["documents"][0])
            except Exception as e:
                system_logger.warning(f"[记忆体完整性] 读取 ChromaDB 失败: {e}")

        result = {
            "ok": True,
            "mysql": mysql_count,
            "txt": txt_count,
            "chromadb": chroma_count,
            "missing": [],
            "detail": ""
        }

        # 三源对比
        issues = []
        if mysql_count == 0 and txt_count == 0:
            result["ok"] = True
            result["detail"] = "全书无章节"
            system_logger.info(f"[记忆体完整性] 三源通过 ✓ (0章)")
            return result

        if mysql_count != txt_count:
            issues.append(f"MySQL({mysql_count}) ≠ 本地txt({txt_count})")
        if txt_count != chroma_count:
            issues.append(f"本地txt({txt_count}) ≠ ChromaDB({chroma_count})")
        if chroma_count == 0 and txt_count > 0:
            issues.append("ChromaDB记忆体为空")

        result["ok"] = len(issues) == 0
        result["detail"] = "; ".join(issues)
        result["missing"] = issues

        if result["ok"]:
            system_logger.info(f"[记忆体完整性] 三源一致通过 ✓ | MySQL={mysql_count} txt={txt_count} ChromaDB={chroma_count}")
        else:
            system_logger.warning(f"[记忆体完整性] 三源不一致 ✗ | MySQL={mysql_count} txt={txt_count} ChromaDB={chroma_count} | {result['detail']}")
        return result

    @staticmethod
    async def _ensure_memory_integrity(novel_unique_id: str, db) -> bool:
        """三源完整性检查 → 不一致则全量重建，一致则直接使用"""
        check = ChapterService._check_memory_integrity(novel_unique_id, db)
        if check["ok"]:
            return True

        system_logger.info(f"[记忆体重建] 三源不一致({check['detail']})，开始全量重建...")

        # 清空旧记忆体
        store = ChapterService._get_store(novel_unique_id)
        if store:
            try:
                full_id = f"memory:{novel_unique_id}:full"
                store.collection.delete(ids=[full_id])
                system_logger.info(f"[记忆体重建] 已删除旧记忆体")
            except Exception as e:
                system_logger.warning(f"[记忆体重建] 删除旧记忆体失败: {e}")

        result = await ChapterService._rebuild_memory_from_files(novel_unique_id, db)
        if result:
            # 重建后再次三源验证
            check2 = ChapterService._check_memory_integrity(novel_unique_id, db)
            if check2["ok"]:
                system_logger.info(f"[记忆体重建] 全量重建成功，三源一致")
                return True
            else:
                system_logger.warning(f"[记忆体重建] 重建后三源仍不一致: {check2['detail']}，继续使用")
                return True  # 有总比没有好
        else:
            system_logger.error("[记忆体重建] 全量重建失败")
            return False

    # ================================================================
    # 增量记忆体：单章保存后更新
    # ================================================================
    @staticmethod
    async def _append_chapter_to_memory(novel_unique_id: str, chapter_name: str, content: str) -> bool:
        """保存新章节后，增量更新 ChromaDB 中的完整记忆体

        1. 提取本章关键信息
        2. 读取现有完整记忆体
        3. 追加本章信息
        4. 写回 ChromaDB

        返回值: True=写入成功, False=写入失败
        """
        if not content or len(content) < 50:
            system_logger.warning(f"[记忆体增量] 跳过: {chapter_name} 内容太短({len(content) if content else 0}字)")
            return False

        store = ChapterService._get_store(novel_unique_id)
        if not store:
            system_logger.error(f"[记忆体增量] 跳过: {chapter_name} ChromaDB store 不可用")
            return False

        try:
            info = await ChapterService.extract_chapter_info(content, chapter_name)
            if not info.get("success") or not info.get("data"):
                system_logger.warning(f"[记忆体增量] 跳过: {chapter_name} AI提取失败: {info.get('error', 'unknown')}")
                return False
            data = info["data"]

            lines = [f"=== {chapter_name} ==="]
            for field in ["人物", "组织", "技能", "事件", "地点", "伏笔", "境界"]:
                val = data.get(field, "")
                if val and val != "无":
                    lines.append(f"  {field}: {val}")
            chapter_summary_text = "\n".join(lines)

            full_id = f"memory:{novel_unique_id}:full"
            existing = ""
            try:
                results = store.collection.get(ids=[full_id])
                if results and results.get("documents") and results["documents"][0]:
                    existing = results["documents"][0]
            except Exception:
                pass

            import re as _re
            old_count = 0
            if existing:
                match = _re.search(r'当前已写(\d+)章', existing)
                if match:
                    old_count = int(match.group(1))
            new_count = old_count + 1

            if _re.search(rf'=== {_re.escape(chapter_name)} ===', existing):
                existing = _re.sub(
                    rf'=== {_re.escape(chapter_name)} ===\n.*?(?=\n=== |\n【|$)',
                    chapter_summary_text,
                    existing,
                    flags=_re.DOTALL
                )
                updated = existing
                system_logger.info(f"[记忆体增量] 已替换章节: {chapter_name}")
            else:
                updated = existing + "\n\n" + chapter_summary_text if existing else chapter_summary_text
                system_logger.info(f"[记忆体增量] 已追加章节: {chapter_name}")

            if _re.search(r'当前已写\d+章', updated):
                updated = _re.sub(r'当前已写\d+章', f'当前已写{new_count}章', updated)
            else:
                updated += f"\n{new_count}.【章节数】当前已写{new_count}章"

            store.collection.upsert(
                documents=[updated],
                ids=[full_id],
                metadatas=[{
                    "doc_type": "full_memory",
                    "novel_unique_id": novel_unique_id,
                }]
            )
            system_logger.info(
                f"[记忆体增量] 完成: {chapter_name} → 共{new_count}章 ({len(updated)}字符)"
            )
            return True
        except Exception as e:
            system_logger.error(f"[记忆体增量] 失败 [{chapter_name}]: {e}")
            return False

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
        txt_files = [f for f in os.listdir(novel_dir)
                     if f.endswith(".txt") and f != "作品设定.txt" and f != "记忆体.txt"]
        txt_files.sort(key=lambda f: os.path.getmtime(os.path.join(novel_dir, f)))

        if not txt_files:
            memory = f"""【作品设定】\n{settings_text}"""
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

                if not ChapterService._is_valid_content(full_text):
                    return (idx, None)

                chapter_name = fname.rsplit("_", 1)[0] if "_" in fname else fname.replace(".txt", "")
                system_logger.info(f"[记忆体] 提取第{idx+1}/{total}章: {chapter_name}")


                info = await ChapterService.extract_chapter_info(full_text, chapter_name)

                if info.get("success") and info.get("data"):
                    data = info["data"]
                    lines = [f"=== 第{idx+1}章 {chapter_name} ==="]
                    for field in ["人物", "组织", "技能", "事件", "地点", "伏笔", "境界", "章节数"]:
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


        # 用聚合摘要发给AI合成最终记忆体
        prompt = AGGREGATE_MEMORY_PROMPT.replace(
            "{settings}", settings_text
        ).replace("{chapters_summary}", chapters_text)

        try:
            extracted = await ChapterService._call_ai_deepseek(
                system_prompt="你是一位资深小说编辑，擅长整理关键信息为结构化记忆体。尽可能详细，不要遗漏。",
                user_prompt=prompt,
                max_tokens=16384,
                temperature=0.3
            )
            if not extracted:
                system_logger.error("[记忆体] 聚合失败")
                extracted = ""
        except Exception as e:
            system_logger.error(f"[记忆体] 聚合异常: {e}")
            extracted = ""

        # 拼接完整的记忆体文本
        memory = f"""【作品设定】
{settings_text}

{extracted if extracted else 'AI聚合失败，请稍后重试'}

【章节数】当前已写{chapter_num}章"""

        # 日志
        log_len = len(memory)
        system_logger.info(
            f"[记忆体] 全量重建完成 | 书={novel_unique_id} | 章节数={chapter_num} | "
            f"总长度={log_len}字符"
        )
        if extracted:
            system_logger.info(f"[记忆体] 聚合内容预览:\n{extracted[:2000]}")

        # 保存一份文本文件（便于肉眼查看）
        memory_file = os.path.join(novel_dir, "记忆体.txt")
        try:
            with open(memory_file, "w", encoding="utf-8") as f:
                f.write(memory)
            system_logger.info(f"[记忆体] 文件保存: {memory_file} ({os.path.getsize(memory_file)}字节)")
        except Exception as e:
            system_logger.error(f"[记忆体] 文件保存失败: {e}")

        # 存入 ChromaDB：先清空旧文档，再写入完整记忆体
        store = ChapterService._get_store(novel_unique_id)
        if store:
            try:
                # 1. 清空该作品的所有旧文档（包括旧版 per-category 空文档）
                all_data = store.collection.get()
                old_ids = [id for id in (all_data.get("ids") or [])
                          if id.startswith(f"memory:{novel_unique_id}:")]
                if old_ids:
                    store.collection.delete(ids=old_ids)
                    system_logger.info(f"[记忆体] 清理旧文档 {len(old_ids)} 条")

                # 2. 写入新的完整记忆体
                store.collection.upsert(
                    documents=[memory],
                    ids=[f"memory:{novel_unique_id}:full"],
                    metadatas=[{"doc_type": "full_memory", "novel_unique_id": novel_unique_id}]
                )
                system_logger.info(f"[记忆体] ChromaDB 写入成功，{len(memory)} 字符")
            except Exception as e:
                system_logger.error(f"[记忆体] ChromaDB 写入失败（将使用文件回退）: {e}")
        else:
            system_logger.warning("[记忆体] ChromaDB store 不可用，仅保存到文件")
            # ChromaDB 不可用不是致命错误，文件还在

        return memory

    @staticmethod
    async def _ensure_memory(novel_unique_id: str, db: Session = None) -> str:
        """获取记忆体：向量库有则直接用，没有则从本地txt全量构建"""
        memory = ChapterService._load_memory(novel_unique_id)
        if memory:
            return memory
        return await ChapterService._rebuild_memory_from_files(novel_unique_id, db)

    @staticmethod
    async def extract_chapter_info(content: str, chapter_name: str = "") -> dict:
        """
        从章节内容中 AI 提取关键信息（轻量级，不存记忆体）
        返回结构化 dict 供前端展示
        """
        if not content or len(content) < 50:
            return {"success": True, "data": {"人物": "", "组织": "",
                     "事件": "", "地点": "", "伏笔": "",
                     "境界": "", "章节数": ""}}

        snippet = ChapterService._truncate_content(content)

        prompt = LIGHT_EXTRACT_PROMPT.replace("{content}", snippet)

        result = {}
        try:
            ai_output = await ChapterService._call_ai_deepseek(
                system_prompt="从小说章节中提取关键信息。只输出人物、组织、技能、事件、地点、伏笔、境界这几个字段。每个字段用20-50字概括。不要分析、不要举例、不要写无关内容。",
                user_prompt=prompt,
                max_tokens=1024,
                temperature=0.1
            )
            if ai_output:
                system_logger.info(f"[提取信息] AI返回长度={len(ai_output)}, 前200字: {ai_output[:200]}")
                # 解析 AI 返回
                parsed = ChapterService._parse_light_extract(ai_output)
                if not parsed:
                    return {"success": False, "error": "AI提取失败"}
                result = parsed

            # 确保所有字段存在
            for field in ["人物", "组织", "技能", "事件", "地点", "伏笔", "境界", "章节数"]:
                if field not in result:
                    result[field] = ""

            return {"success": True, "data": result}
        except Exception as e:
            system_logger.error(f"[提取信息] 异常: {e}")

            return {"success": False, "error": str(e)}

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
        novel_dir = ChapterService._ensure_novel_dir(novel_unique_id)
        chapter_file = os.path.join(novel_dir, f"{chapter_name}_{chapter_unique_id}.txt")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(chapter_data, ensure_ascii=False, indent=2))
        ChapterService._clear_redis_cache(f"chapters:novel:{novel_unique_id}:*")
        return success({"chapter_unique_id": chapter_unique_id, "chapter_name": chapter_name},
                       "章节创建成功，已保存到草稿列表")


    @staticmethod
    def _ensure_novel_dir(novel_unique_id: str) -> str:
        """确保小说数据目录存在，返回目录路径"""
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        os.makedirs(novel_dir, exist_ok=True)
        return novel_dir

    @staticmethod
    def _chapter_file_path(novel_unique_id: str, chapter_name: str, chapter_unique_id: str) -> str:
        """返回章节本地文件的完整路径"""
        return os.path.join(NOVEL_DATA_PATH, novel_unique_id, f"{chapter_name}_{chapter_unique_id}.txt")

    @staticmethod
    def _get_chapter_content(chapter, novel_unique_id: str) -> str:
        """获取章节真实内容：优先DB content字段 → 兜底本地txt文件"""
        content = chapter.content or ""
        if not content:
            filepath = ChapterService._chapter_file_path(novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
        return content

    @staticmethod
    def _get_prev_chapter_ending(db, novel_unique_id: str, chapter_id: int) -> str:
        """通过SQL直接查上一章标题+内容，返回最后500字"""
        from sqlalchemy import text as sql_text
        row = db.execute(sql_text(
            "SELECT content FROM chapters WHERE novel_unique_id=:nid AND id<:cid AND content IS NOT NULL AND content!='' ORDER BY id DESC LIMIT 1"
        ), {'nid': novel_unique_id, 'cid': chapter_id}).fetchone()
        if row and row[0]:
            return row[0][-500:]
        return ""

    @staticmethod
    def _is_valid_content(content: str) -> bool:
        """检查内容是否为有效文本（非JSON元数据）"""
        return bool(content) and not content.strip().startswith("{")

    @staticmethod
    def _truncate_memory(memory_body: str, max_chapters: int = 5, max_chars: int = 3000) -> str:
        """截断记忆体：只保留最后 max_chapters 章，且不超过 max_chars 字符

        记忆体格式：每章以 === 第X章 === 开头
        保留末尾最近的章节（AI 主要需要最新上下文）
        """
        if not memory_body or len(memory_body) <= max_chars:
            return memory_body

        # 按章节分割
        import re
        sections = re.split(r'(?=^=== )', memory_body, flags=re.MULTILINE)
        chapters = [s.strip() for s in sections if s.strip()]

        # 保留最后 max_chapters 章
        kept = chapters[-max_chapters:] if len(chapters) > max_chapters else chapters

        result = "\n\n".join(kept)
        if len(chapters) > max_chapters:
            result = f"（以下为最近{len(kept)}章记忆，早期{len(chapters)-max_chapters}章已省略）\n\n" + result

        # 如果还是超过 max_chars，从尾部截断
        if len(result) > max_chars:
            result = "...\n" + result[-max_chars:]

        system_logger.info(
            f"[记忆体截断] 从{len(memory_body)}字符({len(chapters)}章) "
            f"缩减为{len(result)}字符({len(kept)}章)"
        )
        return result

    @staticmethod
    def _truncate_content(content: str, head: int = 5000, tail: int = 3000, max_len: int = 8000) -> str:
        """截取章节内容：短章全取，超长取head+tail覆盖开头结尾关键事件"""
        if len(content) <= max_len:
            return content
        return content[:head] + "\n...\n" + content[-tail:]

    @staticmethod
    def _write_chapter_file(novel_unique_id: str, chapter_name: str, chapter_unique_id: str, content: str):
        """将章节内容写入本地文件"""
        filepath = ChapterService._chapter_file_path(novel_unique_id, chapter_name, chapter_unique_id)
        ChapterService._ensure_novel_dir(novel_unique_id)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _clear_redis_cache(*patterns: str):
        """清除Redis缓存（按pattern匹配）"""
        r = _redis()
        if r:
            for pattern in patterns:
                r.delete_pattern(pattern)

    @staticmethod
    def _run_async_in_thread(coro, log_label: str = ""):
        """在后台守护线程中执行异步协程，不阻塞主流程"""
        import asyncio
        import threading

        def _runner():
            try:
                asyncio.run(coro)
            except BaseException as e:
                system_logger.error(f"[后台任务] {log_label} 失败: {e}")

        t = threading.Thread(target=_runner, daemon=True)
        t.start()

    @staticmethod
    async def _call_ai_deepseek(system_prompt: str, user_prompt: str,
                                 max_tokens: int = 2048, temperature: float = 0.5,
                                 timeout: int = 120, **extra_params) -> str:
        """调用DeepSeek API，返回AI生成的文本内容"""
        async with httpx.AsyncClient(timeout=timeout) as client:
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
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **extra_params
                }
            )
            data = response.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
            return ""

    # ============================================================
    # 主生成函数（作家风格版）
    # ============================================================
    @staticmethod
    async def generate_with_ai(db: Session, novel_unique_id: str, user_id: int,
                               chapter_name: str, characters_involved: str = None,
                               organizations: str = None, locations: str = None,
                               skills: str = None, word_count: int = 2000,
                               chapter_summary: str = None,
                               created_by: str = None) -> dict:
        """调用DeepSeek AI生成章节正文内容（作家风格版）"""

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
        # 获取作品设定和风格
        # ============================================================
        novel_settings = ChapterService._get_novel_settings(novel_unique_id)
        settings_text = novel_settings.get('content', '无')

        # ============================================================
        # 获取前文章节（用于上下文）
        # ============================================================
        all_chapters = ChapterDAO.get_by_novel_id(db, novel_unique_id)
        sorted_chapters = sorted(all_chapters, key=lambda c: c.created_at or "")

        # 用SQL直接查最新一章的末尾500字（绕过ORM可能延迟加载content）
        last_chapter_ending = ChapterService._get_prev_chapter_ending(
            db, novel_unique_id, 999999999
        )

        # 日志记录：锚定的是哪一章
        if last_chapter_ending:
            prev_name = "未知"
            for c in reversed(sorted_chapters):
                if ChapterService._get_chapter_content(c, novel_unique_id):
                    prev_name = c.chapter_name
                    break
            system_logger.info(f"[章节生成] 续写锚点: {prev_name} 末尾500字")
            system_logger.info(f"[章节生成 截取内容] ---BEGIN---\n{last_chapter_ending}\n---END---")
        else:
            system_logger.warning(f"[章节生成] 未找到有内容的上一章，续写锚点为空")

        # 重复检测：最近3章
        previous_text_for_duplicate = ""
        recent_3 = sorted_chapters[-3:] if len(sorted_chapters) >= 3 else sorted_chapters
        for ch in recent_3:
            content = ChapterService._get_chapter_content(ch, novel_unique_id)
            if content:
                previous_text_for_duplicate += content + "\n"

        last_chapter_full = ""

        prev_chapters = sorted_chapters[:-1] if len(sorted_chapters) > 1 else []

        # ==== 死角色检测（需在概要扫毒之前）====
        living_ban = ChapterService._detect_dead_characters(last_chapter_ending)
        living_ban_header = ""
        if living_ban:
            system_logger.warning(f"[章节生成] {chapter_name} 检测到上一章死去的角色，将注入硬约束")

        # ============================================================
        # 构建章节概要（转换为自然语言叙述）
        # ============================================================
        summary_narrative = ""
        if chapter_summary:
            # 将概要转换得更像故事大纲而非任务清单
            sentences = re.split(r'[，,。.！!？?；;]', chapter_summary)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
            if sentences:
                summary_narrative = "本章要讲述：" + "；".join(sentences) + "。"
        
        # 检测概要中是否含有离别/献祭/牺牲场景
        farewell_trigger = False
        farewell_keywords = ["献祭", "牺牲", "封印", "消散", "离去", "最后一面", "永别", "化作光", "再也"]
        if chapter_summary:
            farewell_trigger = any(kw in chapter_summary for kw in farewell_keywords)

        # ============================================================
        # 构建prompt（使用模板填充）
        # ============================================================
        
        # 加载记忆体（人物、事件、世界观）
        # 三源完整性检查：MySQL章节数 == 本地txt数 == ChromaDB记忆体章节数
        # 三者必须同时存在且一致，否则触发全量重建
        memory_body = "（暂无历史记忆）"
        try:
            system_logger.info(f"[章节生成] {chapter_name} 正在核对记忆存储（MySQL / 本地txt / ChromaDB）...")
            integrity = ChapterService._check_memory_integrity(novel_unique_id, db)
            if integrity["ok"] and integrity["mysql"] > 0:
                # 三源一致 → 直接加载
                mem_body = ChapterService._load_memory(novel_unique_id)
                if mem_body:
                    memory_body = ChapterService._truncate_memory(mem_body)
                    system_logger.info(f"[章节生成] {chapter_name} 记忆体三源一致（MySQL={integrity['mysql']} txt={integrity['txt']} ChromaDB={integrity['chromadb']}），直接使用")
            if memory_body == "（暂无历史记忆）":
                # 三源不一致 或 记忆体为空 → 全量重建
                system_logger.info(f"[章节生成] {chapter_name} 记忆体需要重建: {integrity['detail']}")
                mem_body = await ChapterService._rebuild_memory_from_files(novel_unique_id, db)
                if mem_body:
                    memory_body = ChapterService._truncate_memory(mem_body)
                    check2 = ChapterService._check_memory_integrity(novel_unique_id, db)
                    system_logger.info(f"[章节生成] {chapter_name} 记忆体重建完成，三源={check2['mysql']}/{check2['txt']}/{check2['chromadb']}，{len(mem_body)}字符")
                else:
                    return fail("记忆体生成失败：AI提取完成但写入向量数据库失败，请查看日志排查后重试")
        except Exception as e:
            system_logger.error(f"[章节生成] 记忆体加载/重建异常: {e}")
            return fail(f"记忆体加载失败: {str(e)}")
        
        context_summary = ChapterService._build_context_summary(prev_chapters, last_chapter_ending)

        # 构建死亡角色硬约束文本（放在 prompt 最开头，最高注意力）
        if living_ban and not living_ban_header:
            living_ban_header = f"""🔴 上一章结尾已死亡的角色绝不可以活着出现。以下是原文证据：
{living_ban}
如果本章概要写了这些角色 → 忽略，他们死了。他们只能用回忆/幻觉来写。"""

        # ==== 构建接续自检：提取上一章结尾的属性，强制AI填空 ====
        continuity_check = ChapterService._build_continuity_gate(last_chapter_ending)

        # ==== 真相文件上下文（结构化记忆：角色状态/伏笔/章节摘要）====
        truth_context = ChapterService._build_truth_context(novel_unique_id)
        system_logger.info(f"[章节生成] {chapter_name} 真相文件加载完成")

        # ==== 结尾风格随机选定（21种统一池） ====
        ending = ChapterService._pick_ending_style()
        ending_instruction = ChapterService._build_ending_instruction(ending)
        ending_priority = f"本章必须使用 {ending['label']}。请参照 prompt 末尾 🔴 指令中的模板执行，不得自行换用其他风格。"
        system_logger.info(f"[章节生成] {chapter_name} 结尾选定: {ending['label']}")

        creative_direction = GENERATE_CREATIVE_DIRECTION.format(
            memory_body=ChapterService._esc(memory_body),
            settings_text=ChapterService._esc(settings_text),
            context_summary=ChapterService._esc(context_summary),
            summary_narrative=ChapterService._esc(summary_narrative) if summary_narrative else '根据前文自然推进剧情',
            ending_priority=ending_priority,
            event_checklist=ChapterService._esc(chapter_summary) if chapter_summary else '根据前文自然推进剧情',
            truth_context=ChapterService._esc(truth_context),
        )
        chapter_setting = GENERATE_CHAPTER_SETTING.format(
            chapter_name=ChapterService._esc(chapter_name),
            word_count=word_count,
            characters_involved=ChapterService._esc(characters_involved) if characters_involved else '继承前文',
            locations=ChapterService._esc(locations) if locations else '继承前文'
        )

        # ==== 组装 prompt ====
        prompt = f"""{GENERATE_CREATIVE_BOUNDARIES}

{living_ban_header}
{creative_direction}

{GENERATE_WRITING_EXAMPLES}

{EMOTIONAL_WRITING_GUIDE}

{chapter_setting}

{continuity_check}

===== 开始创作 =====

本章要做的事（写在清单里的，一件不落）：
{ChapterService._esc(chapter_summary) if chapter_summary else '（根据前文自然推进）'}

{ending_instruction}

{ChapterService._build_time_jump_check(last_chapter_ending)}"""

        system_prompt = GENERATE_SYSTEM_PROMPT
        
        # 离别/牺牲场景的强制情感要求
        if farewell_trigger:
            prompt += """
===== 本章含离别/牺牲场景，严格按上方【情感描写铁律】第十到十五条执行 =====
禁止写"对不起""永远爱你""好好活下去回来"——全是没内容的废话。
根据人物关系选择对应写法：恋人→写还没一起做的事/兄弟朋友→写约好一起做的事/
师徒→写还没教完的东西/父子→写成长陪伴/母子→写生活细节。
必须用遗憾清单写法，一件一件列出具体的遗憾，最少列5件以上。
"""
        
        # ============================================================
        # API调用 + 违规扫描回炉（最多3轮）
        # ============================================================
        MAX_RETRIES = 1  # 最多回炉1次（总共2次AI调用）
        generated_text = ""

        for attempt in range(MAX_RETRIES + 1):
            current_prompt = prompt

            try:
                generated_text = await ChapterService._call_ai_deepseek(
                    system_prompt=system_prompt,
                    user_prompt=current_prompt,
                    max_tokens=word_count * 3,
                    temperature=0.75,
                    top_p=0.9,
                    frequency_penalty=0.5,
                    presence_penalty=0.3
                )
                if not generated_text or len(generated_text) <= 100:
                    if attempt < MAX_RETRIES:
                        system_logger.warning(f"[重试 {attempt+1}] {chapter_name} 生成内容过短")
                        continue
                    else:
                        return fail("AI生成内容过短，请重试", code=500)

                # ============================================================
                # 违规扫描 → 定点修复（不改全章，只修违规段落）
                # ============================================================
                is_valid, violation_reasons = ChapterService._validate_chapter_rules(generated_text)
                if not is_valid:
                    if attempt < MAX_RETRIES:
                        violation_feedback = "；".join(violation_reasons)
                        system_logger.warning(f"[定点修复 {attempt+1}] {chapter_name}: {violation_feedback}")
                        generated_text = await ChapterService._spot_fix_chapter(
                            generated_text, violation_feedback, system_prompt, word_count
                        )
                        # 定点修复后直接通过，不再继续回炉
                        break
                    else:
                        system_logger.warning(f"[违规耗尽] {chapter_name} 已达最大重试次数，保留最后一次结果")
                        for v in violation_reasons:
                            system_logger.warning(f"  - 最终违规: {v}")

                break  # 通过验证 或 最后一次不拦

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

        # AI 不再生成标题，后端自动补上（防止 AI 误生成导致双标题）
        raw_content = generated_text.strip()
        # 去掉 AI 可能误生成的标题行（## 第X章 ...）
        raw_content = re.sub(r'^#+\s*第[一二三四五六七八九十百千\d]+章[^\n]*\n*', '', raw_content)
        # 去掉 AI 可能误生成的无序标题行（## ... 开头不带"第"）
        if raw_content.startswith('## ') and '第' not in raw_content[:20]:
            raw_content = re.sub(r'^## [^\n]*\n*', '', raw_content)
        # 拼接章节标题
        generated_text = f"## {chapter_name}\n\n{raw_content.strip()}"
        actual_word_count = len(generated_text)

        try:
            # 截断超长字段，防止 DB 溢出（String类型字段512字，Text无限制但有保护更安全）
            _safe_summary = (chapter_summary or "")[:5000]
            _safe_chapter_name = (chapter_name or "")[:256]
            chapter = ChapterDAO.create(
                db,
                novel_unique_id=novel_unique_id,
                user_id=user_id,
                chapter_unique_id=chapter_unique_id,
                chapter_name=_safe_chapter_name,
                characters_involved=characters_involved,
                organizations=organizations,
                locations=locations,
                skills=skills,
                word_count=actual_word_count,
                chapter_summary=_safe_summary,
                is_published=0,
                content=generated_text,
                created_by=created_by
            )
        except Exception as e:
            system_logger.error(f"保存章节到数据库失败: {e}")
            return fail(f"保存章节失败: {str(e)}", code=500)

        try:
            ChapterService._write_chapter_file(novel_unique_id, chapter_name, chapter_unique_id, generated_text)
        except Exception as e:
            system_logger.error(f"保存章节文件失败: {e}")

        # 更新真相文件（角色状态/伏笔/章节摘要）
        try:
            ChapterService._update_truth_files(
                novel_unique_id, chapter_unique_id, chapter_name,
                chapter_summary or "", generated_text,
                characters_involved
            )
        except Exception as e:
            system_logger.error(f"更新真相文件失败: {e}")

        ChapterService._clear_redis_cache(f"chapters:drafts:user:{user_id}")

        return success({
            "chapter_unique_id": chapter_unique_id,
            "chapter_name": chapter_name,
            "word_count": actual_word_count,
            "content": generated_text
        }, f"{chapter_name} 章节内容生成成功")

    # ============================================================
    # 辅助方法：章节内容规则校验（违规则回炉重试）
    # ============================================================
    @staticmethod
    def _validate_chapter_rules(text: str) -> tuple:
        """扫描生成内容，检查是否违反通用创作约束。
        注意：本方法不包含作品特定关键词，所有规则适用于任何类型。
        Returns: (is_valid: bool, violations: list[str])
        """
        violations = []

        # 1. 基调冲突扫描（喜庆文出现黑暗元素 / 温馨文出现诡异暗示）
        tone_clash = [
            "血色", "血腥", "诅咒", "不祥之兆", "不祥的预兆",
            "深渊般的", "蠕动的黑暗", "暗红色的", "血红色的",
            "暴风雨前的宁静", "诡异的光芒", "不详的气息",
            "来自地狱", "死一般的寂静", "令人窒息的恐惧",
            "莫名的恐惧", "一阵寒意从心底升起",
            "诡物", "吞噬", "陨落", "献祭", "封印",
            "天流血了", "天空突然暗了下来", "花草瞬间枯萎",
            "破壳而出", "化作金光", "灵魂深处", "黑暗的存在",
             "奇异的力量", "恐怖的气息", "心悸",
             "藏着什么东西", "护城大阵",
             "恐怖的力量", "一股让她", "都感到心悸",
             "如血", "像血"
        ]
        for kw in tone_clash:
            if kw in text:
                violations.append(f"基调冲突（可能混入黑暗暗示）：'{kw}'")
                break

        # 2. 场景扩散扫描（从指定地点扩展到全城/街道/周边）
        scene_sprawl = [
            "整座城池", "整个城市都", "全城百姓", "全城都在",
            "街道两旁", "街道上的", "街上的人", "街市上",
            "从城门口", "从街头到巷尾", "满城都是",
            "酒楼里也", "茶馆里也", "店铺也纷纷", "商铺都",
            "所有的街道", "每一条街道", "家家户户都"
        ]
        for kw in scene_sprawl:
            if kw in text:
                violations.append(f"场景扩散：'{kw}'")
                break

        # 3. 路人角色注入扫描（引入概要看之外的路人/围观者）
        crowd_injection = [
            "百姓们", "百姓都", "百姓在", "百姓也",
            "路人纷纷", "围观者", "围观群众",
            "街上的行人", "路过的", "附近的居民",
            "城中仙人", "城中的仙人们", "落空城的百姓",
            "全城的仙人们",
            "说书人放下", "说书人叹道", "茶楼里",
            "孩童指着", "孩童们", "娘亲快看",
            "妇人们紧紧", "酒楼茶馆",
            "百姓跪伏", "百姓欢呼", "百姓们惊慌",
        ]
        for kw in crowd_injection:
            if kw in text:
                violations.append(f"路人注入：'{kw}'")
                break

        # 4. 通用悬念句扫描（结尾强行加钩子 / 旁白式总结）
        generic_cliffhangers = [
            "他不知道的是，",
            "一场更大的风暴即将来临",
            "他没想到的是",
            "谁也不知道的是",
            "然而没有人注意到",
            "没有人注意到，就在",
            "没有人知道，",
            "正在悄然降临",
            "将迎来怎样的",
            "这一切，才刚刚开始",
            "就此陨落",
            "这一天之后",
            "破壳而出的那一天",
            "还在沉睡",
        ]
        for kw in generic_cliffhangers:
            if kw in text:
                violations.append(f"通用悬念句：'{kw}'")
                break

        # 5. 时间线跳越检测（粗略：搜索"生了"/"出生了"/"诞下"等词，仅用于日志提示）
        timeline_jump = ["婴儿啼哭", "一声婴儿", "生了！", "诞生了", "降生了",
                         "婴孩的啼哭", "孩子出生"]
        for kw in timeline_jump:
            if kw in text:
                violations.append(f"时间跳越：'{kw}'")
                break

        # ==== 以下为 XP3: 去 AI 味规则增强 ====

        # 6. 句尾补语（"他终于明白了""这一切意味着什么"）
        tail_padding = [
            "他终于明白", "他隐隐感觉", "这意味着",
            "一切都将改变", "一切才刚刚开始",
            "他不知道的是", "谁也不知道",
            "他并不知道", "没有注意到",
        ]
        for kw in tail_padding:
            if kw in text:
                violations.append(f"句尾补语：'{kw}'（删除，用动作暗示结果）")
                break

        # 7. 空洞过渡（"就在这时""突然""忽然"等词使用频率）
        empty_transitions = re.findall(r'(就在这时[，,]|突然[，,]|忽然[，,]|紧接着[，,])', text)
        if len(empty_transitions) > 3:
            violations.append(f"空洞过渡过多（{len(empty_transitions)}次），替换为具体触发事件")

        # 8. 二元描写（"仿佛""宛如""像是""如同"等比喻词过量）
        simile_words = re.findall(r'(仿佛|宛如|像是|如同|犹如|好似|恰似)', text)
        word_count_approx = len(text)
        if len(simile_words) > max(5, word_count_approx / 300):
            violations.append(f"比喻词过多（{len(simile_words)}次），替换为直接感官描写")

        # 9. 心理描写直白（"他心里想""他心想""他在心里说"）
        direct_psych = re.findall(r'(他心里想|他心想|他在心里说|他暗暗想)', text)
        if len(direct_psych) > 3:
            violations.append(f"直白心理描写过多（{len(direct_psych)}次），用动作/对话暗示心理")

        # 10. 节奏打断（"让我们把目光转向""话说""且说"等说书式过渡）
        narrator_break = [
            "让我们把", "话说", "且说",
            "镜头一转", "画面切到",
            "时间来到", "视线回到",
        ]
        for kw in narrator_break:
            if kw in text:
                violations.append(f"说书式过渡：'{kw}'")
                break

        return (len(violations) == 0, violations)

    # ============================================================
    # 辅助方法：构建上下文摘要
    # ============================================================
    @staticmethod
    def _build_context_summary(prev_chapters, last_chapter_ending: str) -> str:
        """构建自然的前文摘要，而非生硬的列表"""
        if not prev_chapters:
            return "这是故事的开篇。"
        
        recent = prev_chapters[-3:] if len(prev_chapters) > 3 else prev_chapters
        summaries = []
        for i, ch in enumerate(recent, len(prev_chapters) - len(recent) + 1):
            name = ch.chapter_name or f"第{i}章"
            summary = ch.chapter_summary or ""
            if summary:
                summaries.append(f"{name}讲了{summary[:100]}")
        
        context = "；".join(summaries) if summaries else "前文剧情已展开"
        
        if last_chapter_ending:
            context += f"""

===== 上一章结尾场景（本章必须从这里无缝接续） =====
{last_chapter_ending}

【人物状态接续铁律 —— 本章开头必须与上一章结尾严格一致】
1. 上一章结尾里每个角色的状态（活着/死了/消散/昏迷/离开/在场/位置） = 本章开头该角色的状态
2. 上一章结尾已消散/死去/离开/消失的角色，本章开头绝不可以重新出现、复活、回到原位
3. 如果上一章结尾某角色"化作光点消散" → 本章开头该角色就不存在了，不能写他还在场
4. 如果上一章结尾某角色"昏迷不醒" → 本章开头她可以还昏迷，但不能突然清醒地说话
5. 上一章结尾的视角、场景、在场人物，就是本章第一段承接的起点
6. 写完本章开头后自检：此刻在场的人物名单，和上一章结尾在场/能存在的人物名单，完全吻合吗？"""
        
        return context

    @staticmethod
    def _get_last_sentence(text: str) -> str:
        """提取文本的最后一句（用于时间跳跃检查）"""
        if not text:
            return "(无)"
        import re
        window = text[-400:]
        sentences = re.split(r'[。！？\n]+', window)
        sentences = [s.strip() for s in sentences if s.strip()]
        return sentences[-1][:120] if sentences else "(无法提取)"

    @staticmethod
    def _extract_characters_from_text(text: str) -> str:
        """从文本最后 500 字中提取在场人物名

        通过"角色名+动词后缀"的模式识别。例如"姑娘说""阿狗问""石头站"
        """
        if not text:
            return ""
        verb_suffixes = ['说', '站', '坐', '看', '走', '问', '笑', '蹲',
                         '回', '抬', '低', '叹', '点', '摇', '瞪', '皱', '转']
        stop_words = {'他', '她', '它', '我', '你', '他们', '她们', '它们',
                      '我们', '你们', '自己', '别人', '大家', '有人', '没有人'}
        import re
        window = text[-500:]
        pattern = r'([\u4e00-\u9fff]{2,4})(' + '|'.join(verb_suffixes) + r')'
        matches = re.findall(pattern, window)

        characters = set()
        for name, _ in matches:
            if name not in stop_words:
                characters.add(name)

        return "、".join(sorted(characters, key=lambda x: -len(x))) if characters else ""

    @staticmethod
    def _build_time_jump_check(last_chapter_ending: str) -> str:
        """生成续写锚点（放在 prompt 最末尾）

        直接把上一章末尾文本贴出来，让 AI 从同一位置续写。
        优先取 --- 分隔线之后的内容（梦境/幻觉标记后的真实场景）
        """
        if not last_chapter_ending or "无需承接" in last_chapter_ending or "第一章" in last_chapter_ending:
            return "这是第一章，无需接续检查。\n"
        raw = last_chapter_ending[-600:].strip()
        # 优先取最后一个 --- 之后的内容（防止 AI 锚定分隔线前的睡觉/闭眼等场景）
        import re
        parts = re.split(r'\n---+\n', raw)
        anchor = (parts[-1] if len(parts) > 1 else raw)[-400:].strip()
        if not anchor:
            anchor = raw[-400:].strip()
        system_logger.info(f"[续写锚点 截取] parts={len(parts)}, anchor=\n{anchor}")
        return f"""【续写锚点 —— 先接住这个画面再说】

你的事件清单里可能没有写这个场景的后续——但它必须发生。上一章结尾停在这里，你的第一句话就必须从这里继续。

上一章结尾停留的画面：
{anchor}

---
第一句话必须是这个画面的下一瞬。先写至少 2 句锚点场景的后续，再自然过渡到事件清单里的第一个事件。
即使事件清单里没有"喂药""接药碗"这类词——只要锚点画面停在"不用谢"，你就必须写完"她把碗端起来、喂药"这个画面，然后才能跳到下一个事件。"""

    @staticmethod
    def _build_continuity_gate(last_chapter_ending: str) -> str:
        """生成具体的接续自检块，强制 AI 在写作前先解释过渡方式"""
        if not last_chapter_ending:
            return "这是第一章，无需接续检查。\n"

        import re
        window = last_chapter_ending[-400:]

        # 取最后一句话
        sentences = re.split(r'[。！？\n]+', window)
        sentences = [s.strip() for s in sentences if s.strip()]
        last_sentence = sentences[-1][:120] if sentences else "(无法提取)"

        # 检测温度/天气关键词
        temp_found = []
        temp_map = {
            "冷": ["冷", "凉", "寒风", "冰凉", "寒意", "发凉"],
            "热/晒": ["热", "晒", "炎热", "滚烫", "灼热", "闷热"],
            "风": ["风吹", "刮风", "狂风", "微风", "风沙"],
            "雨": ["雨", "淋", "淅沥", "湿透"],
            "夜/暗": ["夜", "黑", "月光", "月亮", "漆黑", "暗暗"],
            "日/晴": ["阳光", "太阳", "日头", "白昼", "白天", "发白"],
        }
        for label, kws in temp_map.items():
            for kw in kws:
                if kw in window:
                    temp_found.append(label)
                    break
        temp_str = "、".join(temp_found) if temp_found else "(无法检测)"

        # 检测时间
        time_found = ""
        time_map = [
            ("清晨/天亮", ["清晨", "天亮", "黎明", "晨光", "天蒙蒙亮"]),
            ("上午", ["上午", "早上", "早晨"]),
            ("中午/正午", ["中午", "正午", "午时"]),
            ("下午", ["下午", "午后"]),
            ("傍晚/黄昏", ["傍晚", "黄昏", "日落", "天黑前", "暮色", "天慢慢暗"]),
            ("夜晚", ["夜里", "深夜", "半夜", "晚上", "入夜", "夜幕"]),
        ]
        for label, kws in time_map:
            for kw in kws:
                if kw in window:
                    time_found = label
                    break
            if time_found:
                break
        if not time_found:
            time_found = "(无法检测，请根据文意判断)"

        # 检测情绪
        emotion_found = []
        emotion_map = {
            "孤独/空落": ["孤独", "空荡", "空落落", "冷清", "一个人", "没有人", "空空的", "独自", "街上空"],
            "悲伤/痛": ["悲伤", "伤心", "泪", "哭", "痛", "疼", "难过"],
            "沉默": ["沉默", "安静", "静", "低着头", "不说", "不出声", "闷", "缩在"],
            "愤怒": ["愤怒", "恨", "咬牙", "攥紧", "怒"],
            "恐惧": ["怕", "恐惧", "害怕", "发抖", "颤"],
            "疲惫": ["疲惫", "累", "困", "倦", "无力"],
            "冷/漠然": ["冷", "没什么表情", "淡淡", "没看", "没理"],
        }
        for label, kws in emotion_map.items():
            for kw in kws:
                if kw in window:
                    emotion_found.append(label)
                    break
        emotion_str = "、".join(emotion_found[:3]) if emotion_found else "(无法检测)"

        # 检测在场人物（简单匹配 "人名+动作" 模式）
        char_pattern = r'([\u4e00-\u9fa5]{2,4})(?:站在|坐了|缩在|靠在|蹲在|趴|跑了|走了|离开|散了|晕了|倒了|推|拉|喊|叫|说|看|回头|抬头|低头|转身|爬起|躺|抱着|背着)'
        chars = list(set(re.findall(char_pattern, window)))
        # 过滤掉常见非人名（如"街上""门口""墙根"）
        not_person = {"街上", "门口", "墙根", "屋里", "外面", "地上", "心里", "手里", "旁边", "前面", "里面", "起来"}
        chars = [c for c in chars if c not in not_person]
        char_str = "、".join(chars[:8]) if chars else "(无法自动检测，请阅读上一章结尾自行判断)"

        gate = f"""【接续自检 —— 写第一句话之前必须完成这个填空】
上一章结尾最后一句话是：
　「{last_sentence}」

你本章的第一句话必须接住这句话。请先在脑子里回答：
① 两个句子之间过了多久？（写具体：第二天早上/一盏茶的功夫/同时/片刻之后/……）
② 地点变了吗？（没变 / 从___到了___）
③ 上一章结尾的温度/天气是：【{temp_str}】。你本章第一段的温度/天气是？如果不一致，必须在第2-3句话里交代变化（如"第二天早上……"）
④ 上一章结尾的情绪基调是：【{emotion_str}】。你本章第一句必须承接这个情绪，不能跳到另一个情绪。
⑤ 上一章结尾的时间是：【{time_found}】。你本章第一段的时间是？如果不一致，必须写清楚时间跳跃。
⑥ 上一章结尾在场的人物有：【{char_str}】。你本章开头时，每个人各自在哪里、什么状态？不能有人凭空消失或凭空出现。

接续正确示例：
  上一章结尾："风吹过来，有点冷。"（冷风、户外、孤独。在场：顾平安、乞丐、被欺负的孩子）
  本章开头："第二天早上，青石镇的街道上，顾平安低着头走着。阳光晒得地面发白……"
  → 时间从"夜晚/冷风"变成了"第二天早上/暴晒"，在第二句交代了时间变化。✅

接续错误示例：
  上一章结尾："风吹过来，有点冷。"（冷风、户外、孤独）
  本章开头："阳光晒得地面发白，他的影子缩在脚底下……"
  → 冷风直接变成了暴晒，没有交代时间变化。❌

人物断裂错误示例：
  上一章结尾：被欺负的孩子还趴在墙根下。
  本章开头：顾平安一个人走着。（那个被欺负的孩子去哪了？消失了？）
  → ❌ 必须交代："那个被欺负的孩子从地上爬起来，推开顾平安跑了。"

"""
        return gate

    # 结尾风格随机选定（21种风格统一池，一次随机选）
    # ============================================================

    @staticmethod
    def _pick_ending_style() -> dict:
        """让 AI 在对话结尾和旁白结尾之间自由选择，不限制具体风格"""
        return {"label": "对话式或旁白式", "example": ""}

    @staticmethod
    def _esc(s: str) -> str:
        """转义花括号，防止 .format() 将用户/AI内容中的 { } 误解析为占位符"""
        if not s:
            return s
        return s.replace('{', '{{').replace('}', '}}')

    # ================================================================
    # XP0: 定点修复 —— 只改违规段落，不重写全章
    # ================================================================
    @staticmethod
    async def _spot_fix_chapter(
        text: str,
        violations: str,
        system_prompt: str,
        max_tokens: int
    ) -> str:
        """只修改违规的段落，不重写其他内容"""
        fix_prompt = f"""以下是你上一轮输出的章节中存在问题：

{violations}

要求：只修改有问题的段落/句子，不要改动其他内容。输出完整章节。

章节内容：
{text}"""
        fixed = await ChapterService._call_ai_deepseek(
            system_prompt=system_prompt,
            user_prompt=fix_prompt,
            max_tokens=min(1800, max_tokens),
            temperature=0.7,
            top_p=0.85,
            frequency_penalty=0.3,
            presence_penalty=0.1
        )
        return fixed if fixed and len(fixed) > 50 else text

    # ================================================================
    # XP1: 真相文件 —— 结构化记忆（角色状态/伏笔/章节摘要）
    # ================================================================
    TRUTH_DIR_NAME = "_truth"

    @staticmethod
    def _truth_file_path(novel_unique_id: str, filename: str) -> str:
        novel_dir = ChapterService._ensure_novel_dir(novel_unique_id)
        truth_dir = os.path.join(novel_dir, "__truth")
        return os.path.join(truth_dir, filename)

    @staticmethod
    def _ensure_truth_dir(novel_unique_id: str):
        truth_dir = os.path.dirname(ChapterService._truth_file_path(novel_unique_id, "dummy"))
        os.makedirs(truth_dir, exist_ok=True)

    @staticmethod
    def _read_truth_file(novel_unique_id: str, filename: str, default: str = "") -> str:
        """读取真相文件"""
        filepath = ChapterService._truth_file_path(novel_unique_id, filename)
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            pass
        return default

    @staticmethod
    def _write_truth_file(novel_unique_id: str, filename: str, content: str):
        """写入真相文件"""
        import os
        filepath = ChapterService._truth_file_path(novel_unique_id, filename)
        ChapterService._ensure_truth_dir(novel_unique_id)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _update_truth_files(novel_unique_id: str, chapter_unique_id: str, chapter_name: str, summary: str, content: str, characters_involved: str = ""):
        """每章写入后更新真相文件

        更新内容：
        1. chapter_summaries.txt —— 追加本章摘要
        2. character_matrix.txt —— 最后状态
        3. pending_hooks.txt —— 伏笔清单
        """
        # 1. 追加章节摘要（每章 1-2 句）
        summaries = ChapterService._read_truth_file(novel_unique_id, "chapter_summaries.txt")
        if content:
            # 用 AI 快速提取摘要（非常轻量，用 content 前 200 字 + 后 200 字概括）
            first_200 = content[:200].replace('\n', ' ')
            last_200 = content[-200:].replace('\n', ' ')
            short_summary = f"{chapter_name}：{first_200}…{last_200}"
        else:
            short_summary = f"{chapter_name}：{summary[:100]}"
        summaries += f"\n{short_summary}"
        ChapterService._write_truth_file(novel_unique_id, "chapter_summaries.txt", summaries.strip())

        # 2. 更新角色状态（仅记录参与角色）—— 简单版
        if characters_involved and characters_involved != "继承前文":
            matrix = ChapterService._read_truth_file(novel_unique_id, "character_matrix.txt", default="# 角色状态追踪（自动更新）\n")
            matrix += f"\n## {chapter_name}\n参与角色：{characters_involved}"
            ChapterService._write_truth_file(novel_unique_id, "character_matrix.txt", matrix.strip())

        # 3. 更新伏笔清单（用于下一章生成时提醒回收）
        hooks = ChapterService._read_truth_file(novel_unique_id, "pending_hooks.txt", default="# 待回收伏笔\n")
        hooks += f"\n- [{chapter_name}]（待判定：本章是否埋伏笔？由下一章生成时的 AI 自行标记回收）"
        ChapterService._write_truth_file(novel_unique_id, "pending_hooks.txt", hooks.strip())

    @staticmethod
    def _build_truth_context(novel_unique_id: str) -> str:
        """组装真相文件上下文（用于注入 prompt）"""
        summaries = ChapterService._read_truth_file(novel_unique_id, "chapter_summaries.txt", default="（暂无）")
        matrix = ChapterService._read_truth_file(novel_unique_id, "character_matrix.txt", default="（暂无）")
        hooks = ChapterService._read_truth_file(novel_unique_id, "pending_hooks.txt", default="（暂无）")

        return f"""【角色当前状态】
{matrix[:1500]}

【未回收伏笔】
{hooks[:1000]}

【已写章节摘要】
{summaries[:2000]}"""

    @staticmethod
    def _build_ending_instruction(ending: dict) -> str:
        """构建结尾指令 —— 两层维度。AI 在对话结尾和旁白结尾之间自由选择。"""
        return """==============================
🔴【本章结尾指令 —— 两层维度，必须同时做到】

结尾风格：你可以选择对话结尾（用角色之间的对话收束本章）或旁白结尾（用叙述性的描写收束本章），风格自由决定。

【维度1：本章收束 —— 必须做到】
1. 先写完本章的最后一个事件。不能跳过事件直接跳到结尾。
2. 事件写完后，用对话或旁白自然地收束本章。
3. 结尾至少 3-5 句话。不能事件还没写完就突然结束。

【维度2：下一章起点 —— 必须做到】
你的结尾是下一章第一个画面。从这个结尾中，下一章必须能清楚地看出：
  - 现在谁在场？（把在场的每一个人都写出来，哪怕只是一个姿势）
  - 各自在什么位置/什么状态？（站着/缩着/躺着/走了/晕倒了）
  - 什么情绪？（冷/空/安静/疼/累/……）
  - 什么环境？（街/屋/山/庙/……）

维度2 反面示例（错的）：
  顾平安站在街上。风吹过来，有点冷。
  → 只写了顾平安一个人。乞丐呢？那群小孩呢？被欺负的孩子呢？
  → 读者不知道这些人去哪儿了，下一章无法从这个画面继续。

维度2 正确示例：
  胖墩带着小孩们走了。街上空荡荡的。
  顾平安从地上爬起来，膝盖上沾了灰。
  他回头看了一眼那个乞丐。乞丐缩在角落里，低着头，没看他。
  那个被欺负的孩子还趴在墙根下，没动。
  顾平安站在那里。风吹过来，有点冷。
  → 每个人（胖墩走了、乞丐缩着、孩子趴着、顾平安站着）都交代清楚了。
  → 下一章从"那个被欺负的孩子爬起来，推开了顾平安"开始，完全接得上。

【自我检查 —— 写结尾后】
□ 在场所有人，我都写了他们的状态了吗？（是 / 漏了谁？）
□ 下一章的第一句话能直接从我这个结尾里长出来吗？（能 / 为什么不能？）
=============================="""

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

        # 从 ChromaDB 加载记忆体（ch1 → current-1）
        memory_body = f"【作品设定】\n{settings_text}\n\n"
        try:
            mem_from_db = ChapterService._load_memory(novel_unique_id)
            if mem_from_db:
                memory_body += ChapterService._truncate_memory(mem_from_db)
                system_logger.info(f"[重新生成] ChromaDB 记忆体加载完成, {len(mem_from_db)}字符")
            else:
                # ChromaDB 无记忆 → 全量构建
                system_logger.info("[重新生成] 记忆体不存在，触发全量构建")
                await ChapterService._rebuild_memory_from_files(novel_unique_id, db)
                mem_from_db = ChapterService._load_memory(novel_unique_id)
                if mem_from_db:
                    memory_body += ChapterService._truncate_memory(mem_from_db)
                else:
                    return fail("记忆体生成失败：AI提取完成但写入向量数据库失败，请查看日志排查后重试")
        except Exception as e:
            system_logger.error(f"[重新生成] 记忆体加载/重建异常: {e}")
            return fail(f"记忆体加载失败: {str(e)}")

        last_chapter_content = ""
        if prev_chapters:
            # 从最近一章开始向前查找有内容的章节作为锚点
            for idx in range(len(prev_chapters) - 1, -1, -1):
                candidate = prev_chapters[idx]
                candidate_content = ChapterService._get_chapter_content(candidate, novel_unique_id)
                if candidate_content:
                    last_chapter_content = candidate_content
                    break

        chapter_setting = f"""本章设定：
章节名称：{chapter_name}
本章概要：{chapter_summary or '无'}
目标字数：{word_count}字"""

        last_ending = last_chapter_content[-2500:] if last_chapter_content else '这是第一章，无需承接'

        # ==== 构建接续自检 ====
        continuity_gate = ChapterService._build_continuity_gate(last_ending)

        # ==== 结尾风格随机选定 ====
        ending = ChapterService._pick_ending_style()
        ending_instruction = ChapterService._build_ending_instruction(ending)
        ending_priority = f"本章必须使用 {ending['label']}。参照末尾 🔴 指令中的模板执行，不得自行换风格。"
        system_logger.info(f"[重新生成] {chapter_name} 结尾选定: {ending['label']}（第{ending['number']}/21号）")

        # ==== 硬约束：检测上一章死去的角色 ====
        living_ban = ChapterService._detect_dead_characters(last_chapter_content)
        living_ban_text = ""
        if living_ban:
            living_ban_text = f"""
🔴🔴🔴【生死硬约束 —— 违反即不合格】
上一章结尾发生了死亡/消散事件（原文证据）：
{living_ban}

规则：这些角色已死，本章绝不可以让ta活着出现。
如果本章概要里写了这些角色 → 忽略概要中关于这些角色的内容，他们死了。
🔴🔴🔴"""

        prompt = REGENERATE_PROMPT.format(
            chapter_summary=ChapterService._esc(chapter_summary) if chapter_summary else '（无特定剧情要求，请根据前文自然推进）',
            memory_body=ChapterService._esc(memory_body),
            last_chapter_ending=ChapterService._esc(last_ending),
            chapter_setting=ChapterService._esc(chapter_setting),
            word_count=word_count,
            chapter_name=ChapterService._esc(chapter_name),
            ending_priority=ending_priority,
            ending_instruction=ending_instruction,
            living_ban_text=living_ban_text,
            time_jump_check=ChapterService._build_time_jump_check(last_ending),
        ) + "\n\n" + EMOTIONAL_WRITING_GUIDE

        try:
            generated_text = await ChapterService._call_ai_deepseek(
                system_prompt=REGENERATE_SYSTEM_PROMPT,
                user_prompt=prompt,
                max_tokens=word_count * 3,
                temperature=0.85,
                timeout=180
            )
            if not generated_text:
                return fail("AI重新生成失败", code=500)

            # 违规扫描 → 定点修复（只修违规段落，不重写全章）
            is_valid, violation_reasons = ChapterService._validate_chapter_rules(generated_text)
            if not is_valid:
                violation_feedback = "；".join(violation_reasons)
                system_logger.warning(f"[重新生成 定点修复] {chapter_name}: {violation_feedback}")
                fixed_text = await ChapterService._spot_fix_chapter(
                    generated_text, violation_feedback, REGENERATE_SYSTEM_PROMPT, word_count
                )
                if fixed_text and len(fixed_text) > 50:
                    generated_text = fixed_text

            actual_words = len(generated_text)
            system_logger.info(f"AI章节重新生成成功: {chapter_name} ({actual_words}字) novel={novel_unique_id}")

            # AI 不再生成标题，后端自动补上（防止 AI 误生成导致双标题）
            raw_content = generated_text.strip()
            raw_content = re.sub(r'^#+\s*第[一二三四五六七八九十百千\d]+章[^\n]*\n*', '', raw_content)
            if raw_content.startswith('## ') and '第' not in raw_content[:20]:
                raw_content = re.sub(r'^## [^\n]*\n*', '', raw_content)
            generated_text = f"## {chapter_name}\n\n{raw_content.strip()}"
            actual_words = len(generated_text)

            # 更新当前章节（覆盖内容，不新建）
            ChapterDAO.update(db, chapter,
                content=generated_text,
                word_count=actual_words
            )

            # 更新本地文件
            ChapterService._write_chapter_file(novel_unique_id, chapter_name, chapter_unique_id, generated_text)

            # 更新真相文件（角色状态/伏笔/章节摘要）
            try:
                ChapterService._update_truth_files(
                    novel_unique_id, chapter_unique_id, chapter_name,
                    chapter_summary or "", generated_text,
                    characters_involved
                )
            except Exception as e:
                system_logger.error(f"[重新生成] 更新真相文件失败: {e}")

            ChapterService._clear_redis_cache(f"chapters:drafts:user:{user_id}")

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
        chapter = ChapterDAO.get_by_unique_id(db, chapter_unique_id)
        if not chapter:
            return fail("章节不存在", code=404)

        # 读取当前章节已有内容
        existing_content = ChapterService._get_chapter_content(chapter, chapter.novel_unique_id)

        # 当前章节已写内容（取末尾部分作为上下文）
        context_content = existing_content[-2000:] if len(existing_content) > 2000 else existing_content

        # ===== 记忆体：一次加载 =====
        memory_body = await ChapterService._ensure_memory(chapter.novel_unique_id, db)
        memory_body = ChapterService._truncate_memory(memory_body)

        # ==== 结尾风格随机选定 ====
        ending = ChapterService._pick_ending_style()
        ending_instruction = ChapterService._build_ending_instruction(ending)
        ending_priority = f"本章必须使用 {ending['label']}。参照末尾 🔴 指令中的模板执行，不得自行换风格。"
        system_logger.info(f"[续写] {chapter_name} 结尾选定: {ending['label']}（第{ending['number']}/21号）")

        prompt = CONTINUE_PROMPT.format(
            memory_body=ChapterService._esc(memory_body),
            chapter_name=ChapterService._esc(chapter.chapter_name),
            chapter_summary=ChapterService._esc(chapter.chapter_summary) if chapter.chapter_summary else '无',
            context_content=ChapterService._esc(context_content),
            word_count=word_count,
            ending_priority=ending_priority,
            ending_instruction=ending_instruction,
            time_jump_check=ChapterService._build_time_jump_check(context_content),
        ) + "\n\n" + EMOTIONAL_WRITING_GUIDE

        try:
            generated_text = await ChapterService._call_ai_deepseek(
                system_prompt=CONTINUE_SYSTEM_PROMPT,
                user_prompt=prompt,
                max_tokens=word_count * 3,
                temperature=0.8
            )
            if not generated_text:
                return fail("AI续写失败", code=500)

            # 违规扫描 → 定点修复（只修违规段落，不重写全章）
            is_valid, violation_reasons = ChapterService._validate_chapter_rules(generated_text)
            if not is_valid:
                violation_feedback = "；".join(violation_reasons)
                system_logger.warning(f"[续写 定点修复] {chapter.chapter_name}: {violation_feedback}")
                fixed_text = await ChapterService._spot_fix_chapter(
                    generated_text, violation_feedback, CONTINUE_SYSTEM_PROMPT, word_count
                )
                if fixed_text and len(fixed_text) > 50:
                    generated_text = fixed_text

            system_logger.info(f"AI续写成功: {chapter.chapter_name} +{len(generated_text)}字")

            # 追加续写内容到文件和数据库
            new_content = existing_content + "\n\n" + generated_text
            ChapterService._write_chapter_file(
                chapter.novel_unique_id, chapter.chapter_name, chapter.chapter_unique_id, new_content
            )

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
            content = ChapterService._get_chapter_content(ch, ch.novel_unique_id)
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
            ChapterService._write_chapter_file(chapter.novel_unique_id, chapter.chapter_name, chapter_unique_id, content)
            update_data["word_count"] = len(content)
            update_data["content"] = content  # 同步更新数据库内容字段，确保 Reader 读到编辑后的内容
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
        ChapterService._clear_redis_cache("chapters:*", "interactions:*")

        # 发布后数据录入：txt → MySQL → ChromaDB（顺序写入，失败则回滚）
        actual_content = content if content else ChapterService._get_chapter_content(chapter, chapter.novel_unique_id)
        import asyncio
        system_logger.info(f"[发布-数据录入] {chapter.chapter_name} 开始数据录入（txt→MySQL→ChromaDB）...")
        try:
            mem_ok = asyncio.run(
                ChapterService._on_publish_update_memory(
                    chapter.novel_unique_id, chapter_unique_id, chapter.chapter_name, actual_content
                )
            )
        except Exception as e:
            system_logger.error(f"[发布-数据录入] {chapter.chapter_name} 异常: {e}")
            mem_ok = False

        if not mem_ok:
            system_logger.warning(f"[发布-数据录入] {chapter.chapter_name} 记忆体保存失败，回滚发布")
            # 回滚：移除已写入的 txt 文件、清除 DB 标记
            if content is not None:
                filepath = ChapterService._chapter_file_path(
                    chapter.novel_unique_id, chapter.chapter_name, chapter_unique_id
                )
                if os.path.exists(filepath):
                    os.remove(filepath)
            ChapterDAO.update(db, chapter, is_published=0)
            return fail("数据录入失败：记忆体保存异常，发布已取消。请稍后重试。", code=500)

        system_logger.info(f"[发布-数据录入] {chapter.chapter_name} 三源数据录入完成，发布成功")

        return success({
            "chapter_unique_id": chapter_unique_id,
            "chapter_name": chapter.chapter_name,
            "message": "章节发布成功，数据已同步至本地、数据库和记忆体"
        }, "章节发布成功，已同步到作品圈")

    @staticmethod
    async def _on_publish_update_memory(novel_unique_id: str, chapter_unique_id: str,
                                        chapter_name: str, actual_content: str) -> bool:
        """发布后增量写入：死亡标记 → 追加本章。不触发全量重建（重建只在生成时做）。

        返回值: True=成功, False=失败
        """
        # 1. 标记死亡角色
        ChapterService._mark_dead_characters_in_memory(
            novel_unique_id, chapter_unique_id, chapter_name, actual_content
        )
        system_logger.info(f"[发布-记忆体] ① 死亡标记完成: {chapter_name}")

        # 2. 增量追加本章到 ChromaDB（仅追加，不重建）
        appended = await ChapterService._append_chapter_to_memory(novel_unique_id, chapter_name, actual_content)
        if not appended:
            system_logger.error(f"[发布-记忆体] ② 增量追加失败: {chapter_name}")
            return False
        system_logger.info(f"[发布-记忆体] ② 增量追加完成: {chapter_name}")

        # 3. 快速验证（仅日志，不触发重建 —— 重建在下次生成时自动处理）
        from app.models.base import SessionLocal
        db = SessionLocal()
        try:
            check = ChapterService._check_memory_integrity(novel_unique_id, db)
            if check["ok"]:
                system_logger.info(f"[发布-记忆体] ③ 三源一致: {chapter_name}")
            else:
                system_logger.warning(f"[发布-记忆体] ③ 三源暂不一致({check['detail']})，下次生成时将自动重建")
            return True
        finally:
            db.close()

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
            ChapterService._write_chapter_file(chapter.novel_unique_id, chapter.chapter_name, chapter_unique_id, content)
            update_data["word_count"] = len(content)
            update_data["content"] = content  # 同步更新数据库内容字段
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
        ChapterService._clear_redis_cache("chapters:*")

        # 若章节已发布，内容修改后需更新记忆体（后台异步，不阻塞响应）
        if content is not None and chapter.is_published:
            _nid, _cid, _cn = chapter.novel_unique_id, chapter_unique_id, chapter.chapter_name
            ChapterService._run_async_in_thread(
                ChapterService._on_edit_update_memory(_nid, _cid, _cn, content),
                log_label=f"编辑后记忆体更新 | {_cn}"
            )

        return success(None, "章节更新成功")

    @staticmethod
    async def _on_edit_update_memory(novel_unique_id: str, chapter_unique_id: str,
                                     chapter_name: str, content: str):
        """编辑章节后：完整性检查 → 增量更新（替换旧章节记忆）"""
        system_logger.info(f"[记忆体编辑] 开始处理: {chapter_name}")
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            ok = await ChapterService._ensure_memory_integrity(novel_unique_id, db)
            if not ok:
                system_logger.error(f"[记忆体编辑] 完整性重建失败: {chapter_name}")
                return
            system_logger.info(f"[记忆体编辑] 完整性检查通过: {chapter_name}")

            # 死亡标记（编辑可能涉及角色复活/死亡）
            ChapterService._mark_dead_characters_in_memory(
                novel_unique_id, chapter_unique_id, chapter_name, content
            )

            # 增量更新（替换旧章节内容）
            await ChapterService._append_chapter_to_memory(novel_unique_id, chapter_name, content)
            system_logger.info(f"[记忆体编辑] 更新完成: {chapter_name}")
        finally:
            db.close()

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
        ChapterService._clear_redis_cache("chapters:*", "interactions:*")

        # 4. 删除该章节的记忆体（精确删除，非全量重建）
        ChapterService._delete_chapter_memory(novel_unique_id, chapter_unique_id)

        system_logger.info(f"[删除章节] {chapter_name} 已删除，记忆体已更新")

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
            content = ChapterService._get_chapter_content(ch, ch.novel_unique_id)
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
