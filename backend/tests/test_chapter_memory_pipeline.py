# -*- coding: utf-8 -*-
"""章节记忆体链路 + 发布三源校验的回归测试。

覆盖本次优化修复的问题：
- 增量提取缺 ``[第N章]`` 标记 → 三源统计/章号过滤/重写清旧全部失效
- 按需检索在「概要为空」时绕过章号过滤 → 重写被旧版本带偏
- 重写（regenerate）先删本章旧记忆、AI 提取又没产出 → 记忆被清空且无替代
- 发布阶段 3 只看"记忆体 hash 非空"→ 只有前几章记忆时本章也能"三源通过"发布

本机/CI 常缺 sqlalchemy、redis、fastapi 等运行时依赖，这里用桩模块 + 内存版 Redis
直接驱动 ``ChapterService`` 的真实逻辑（不做网络/DB 访问）。
"""

import asyncio
import importlib
import os
import sys
import types
import unittest
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 运行时依赖桩：仅在缺少该依赖时安装，装了真实依赖的环境不受影响
# ============================================================

class _Any:
    """占位对象：属性/调用/作为基类都返回自身或 object。"""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return _Any()

    def __mro_entries__(self, bases):
        return (object,)

    def __getitem__(self, item):
        return _Any()


def _stub_module(name: str) -> None:
    module = types.ModuleType(name)
    module.__getattr__ = lambda key: _Any()
    module.__path__ = []
    sys.modules[name] = module


_OPTIONAL_DEPS = (
    "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.ext", "sqlalchemy.ext.declarative",
    "sqlalchemy.dialects", "sqlalchemy.dialects.mysql", "redis", "elasticsearch",
    "jieba", "hanlp", "fastapi", "fastapi.responses", "fastapi.security",
    "pydantic", "jose", "passlib", "passlib.context", "resend", "alipay",
)


def _install_stubs() -> None:
    for name in _OPTIONAL_DEPS:
        try:
            importlib.import_module(name)
        except Exception:
            _stub_module(name)


_install_stubs()

import app.utils.redis_cache as redis_mod              # noqa: E402
import app.service.chapter_service as chapter_service  # noqa: E402
from app.dao.chapter_dao import ChapterDAO             # noqa: E402
from app.service.chapter_gen_service import ChapterGenService  # noqa: E402


# ============================================================
# 内存版 Redis（对齐 RedisCache 被用到的接口）
# ============================================================

class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.kv = {}

    def ping(self):
        return True

    # --- hash ---
    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value
        return True

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    # --- kv ---
    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ttl=None):
        self.kv[key] = value
        return True

    def exists(self, key):
        return key in self.hashes or key in self.kv

    def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)
            self.kv.pop(key, None)

    def delete_pattern(self, pattern):
        prefix = pattern.rstrip("*")
        for store in (self.hashes, self.kv):
            for key in [k for k in store if k.startswith(prefix)]:
                store.pop(key, None)


class FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []


class FakeRow:
    def __init__(self, is_published, word_count):
        self._values = (is_published, word_count)

    def __getitem__(self, index):
        return self._values[index]


class FakeDB:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    def query(self, *args, **kwargs):
        return FakeQuery()

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return FakeRow(1, 1000)

    def flush(self):
        pass

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def add(self, obj):
        pass

    def refresh(self, obj):
        pass

    def close(self):
        pass


class FakeChapter:
    def __init__(self, novel_unique_id="novel-1", chapter_unique_id="chap-14",
                 chapter_name="第十四章 暗河尽头", chapter_number=14,
                 content="正文内容" * 60, is_published=0):
        self.novel_unique_id = novel_unique_id
        self.chapter_unique_id = chapter_unique_id
        self.chapter_name = chapter_name
        self.chapter_number = chapter_number
        self.chapter_summary = "沈缺被押送执法堂。"
        self.word_count = len(content)
        self.is_published = is_published
        self.user_id = 2
        self.created_by = "tester"
        self.content = content


# ============================================================
# 测试
# ============================================================

class ChapterMemoryPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data_path = self._tmp.name
        self._orig_data_path = chapter_service.NOVEL_DATA_PATH
        self._orig_redis = redis_mod.redis_client
        chapter_service.NOVEL_DATA_PATH = self.data_path
        self.redis = FakeRedis()
        redis_mod.redis_client = self.redis
        self.novel_id = "novel-1"
        self.memory_key = chapter_service.ChapterService._memory_key(self.novel_id)

    def tearDown(self):
        chapter_service.NOVEL_DATA_PATH = self._orig_data_path
        redis_mod.redis_client = self._orig_redis
        self._tmp.cleanup()

    # ---------- 1. [第N章] 标记兜底 ----------

    def test_ensure_chapter_markers_prefixes_lines_and_is_idempotent(self):
        CS = chapter_service.ChapterService
        text = "沈缺获得陨星。\n[第13章] 陆九渊登场。"
        marked = CS._ensure_chapter_markers(text, "[第14章] ")
        self.assertEqual(
            marked,
            "[第14章] 沈缺获得陨星。\n[第13章] 陆九渊登场。",
        )
        # 幂等：已有标记的行不被重复加前缀
        self.assertEqual(CS._ensure_chapter_markers(marked, "[第14章] "), marked)

    def test_incremental_markers_make_redis_chapter_counting_work(self):
        """增量提取的裸文本补标记后，Redis 三源统计能数到本章。"""
        CS = chapter_service.ChapterService
        raw = "沈缺获得陨星。\n陆九渊登场并提出交易。"
        CS._append_to_dimension(
            self.novel_id, "关键事件",
            CS._ensure_chapter_markers(raw, "[第14章] "))
        self.assertEqual(ChapterGenService._redis_chapter_nums(self.novel_id), {14})
        self.assertEqual(ChapterGenService.count_sources(self.novel_id, FakeDB())["redis"]["count"], 1)

    # ---------- 2. 按需检索的章号过滤 ----------

    def _seed_memory(self):
        return {
            "人物": (
                "【人物】\n"
                "[第1章] 沈缺 | 外门杂役\n"
                "[第14章] 旧版沈缺 | 上一版第十四章的记忆\n"
                "[第15章] 未来角色 | 本章还没写到\n"
            ),
            "关键事件": "【关键事件】\n[第1章] 沈缺触碰陨石\n[第14章] 旧版第十四章剧情\n",
        }

    def test_retrieve_memory_filters_current_chapter_with_summary(self):
        CS = chapter_service.ChapterService
        memory = "\n\n".join(self._seed_memory().values())
        out = CS._retrieve_relevant_memory(
            memory, "沈缺被押送执法堂，陆九渊出现。", max_chars=None, current_chapter_num=14)
        self.assertNotIn("[第14章]", out)
        self.assertNotIn("[第15章]", out)
        self.assertIn("[第1章]", out)

    def test_retrieve_memory_filters_current_chapter_without_summary(self):
        """概要为空（草稿章重写）时也必须过滤——历史 bug：这条捷径绕过了过滤。"""
        CS = chapter_service.ChapterService
        memory = "\n\n".join(self._seed_memory().values())
        out = CS._retrieve_relevant_memory(
            memory, "", max_chars=None, current_chapter_num=14)
        self.assertNotIn("[第14章]", out)
        self.assertIn("[第1章]", out)

    def test_retrieve_memory_filters_even_when_memory_is_small(self):
        """记忆体体积已达标（max_chars 命中）时同样要过滤。"""
        CS = chapter_service.ChapterService
        memory = "【关键事件】\n[第1章] 开端\n[第14章] 旧版本章剧情\n"
        out = CS._retrieve_relevant_memory(
            memory, "", max_chars=100000, current_chapter_num=14)
        self.assertNotIn("[第14章]", out)
        self.assertIn("[第1章]", out)

    # ---------- 3. 重写记忆体的快照回滚 ----------

    def test_regenerate_rolls_back_when_extraction_writes_nothing(self):
        CS = chapter_service.ChapterService
        CS._append_to_dimension(self.novel_id, "关键事件",
                                "[第14章] 旧版第十四章的关键事件")
        before = CS._load_memory(self.novel_id)
        self.assertIn("[第14章]", before)

        original = CS._incremental_memory_update

        async def _noop(*args, **kwargs):
            return None

        CS._incremental_memory_update = staticmethod(_noop)
        try:
            written = asyncio.run(CS._refresh_memory_after_generate(
                self.novel_id, None, "新的正文内容" * 50,
                "第十四章 暗河尽头", "概要", is_regenerate=True))
        finally:
            CS._incremental_memory_update = original

        self.assertFalse(written)
        # 旧记忆被回滚回来，本章不会"删了又没写"
        self.assertIn("[第14章]", CS._load_memory(self.novel_id))

    def test_regenerate_keeps_new_memory_when_extraction_writes(self):
        CS = chapter_service.ChapterService
        CS._append_to_dimension(self.novel_id, "关键事件", "[第14章] 旧版第十四章剧情")
        original = CS._incremental_memory_update

        async def _writes(novel_unique_id, db, chapter_content, chapter_name, chapter_summary=""):
            CS._append_to_dimension(novel_unique_id, "关键事件", "[第14章] 新版第十四章剧情")

        CS._incremental_memory_update = staticmethod(_writes)
        try:
            written = asyncio.run(CS._refresh_memory_after_generate(
                self.novel_id, None, "新的正文内容" * 50,
                "第十四章 暗河尽头", "概要", is_regenerate=True))
        finally:
            CS._incremental_memory_update = original

        self.assertTrue(written)
        memory = CS._load_memory(self.novel_id)
        self.assertIn("新版第十四章剧情", memory)
        self.assertNotIn("旧版第十四章剧情", memory)

    def test_new_chapter_reports_false_when_extraction_writes_nothing(self):
        """新章提取空 → 返回 False，调用方据此保留占位标记。"""
        CS = chapter_service.ChapterService
        original = CS._incremental_memory_update

        async def _noop(*args, **kwargs):
            return None

        CS._incremental_memory_update = staticmethod(_noop)
        try:
            written = asyncio.run(CS._refresh_memory_after_generate(
                self.novel_id, None, "正文" * 100, "第十四章 暗河尽头", "概要"))
        finally:
            CS._incremental_memory_update = original
        self.assertFalse(written)

    # ---------- 4. 发布三源校验 ----------

    def _patch_chapter(self, chapter):
        self._orig_get = ChapterDAO.get_by_unique_id
        self._orig_update = ChapterDAO.update
        ChapterDAO.get_by_unique_id = staticmethod(lambda db, uid: chapter)
        ChapterDAO.update = staticmethod(
            lambda db, obj, **kwargs: [setattr(obj, k, v) for k, v in kwargs.items()])
        self.addCleanup(self._restore_chapter_dao)

    def _restore_chapter_dao(self):
        ChapterDAO.get_by_unique_id = self._orig_get
        ChapterDAO.update = self._orig_update

    def test_publish_rejected_when_redis_only_has_other_chapters(self):
        """回归：Redis 里只有第 1 章记忆时，发布第 14 章必须被拒绝并回滚。"""
        CS = chapter_service.ChapterService
        self.redis.hset(self.memory_key, "关键事件", "[第1章] 第一阶段的关键事件")
        chapter = FakeChapter()
        self._patch_chapter(chapter)
        original_extract = CS._extract_and_append_to_memory

        async def _noop(*args, **kwargs):
            return None

        CS._extract_and_append_to_memory = staticmethod(_noop)
        try:
            result = CS.publish_chapter(FakeDB(), chapter.chapter_unique_id,
                                        content=chapter.content)
        finally:
            CS._extract_and_append_to_memory = original_extract

        self.assertEqual(result.get("状态码"), 500)
        self.assertIn("Redis", result.get("消息", ""))
        # 回滚：MySQL 发布标记复位、txt 删除
        self.assertEqual(chapter.is_published, 0)
        txt = CS._get_chapter_txt_path(self.novel_id, chapter.chapter_name,
                                       chapter.chapter_unique_id)
        self.assertFalse(os.path.exists(txt))

    def test_publish_succeeds_when_redis_has_this_chapter(self):
        CS = chapter_service.ChapterService
        self.redis.hset(self.memory_key, "关键事件", "[第14章] 本章的关键事件")
        chapter = FakeChapter()
        self._patch_chapter(chapter)
        result = CS.publish_chapter(FakeDB(), chapter.chapter_unique_id,
                                        content=chapter.content)
        self.assertEqual(result.get("状态码"), 200)


if __name__ == "__main__":
    unittest.main()
