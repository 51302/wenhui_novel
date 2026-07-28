import json
import os
import uuid
import shutil
import threading
from sqlalchemy.orm import Session
from app.dao.novel_dao import NovelDAO
from app.utils.response import success, fail
import app.utils.redis_cache as redis_mod
from app.service.es_service import es_service

NOVEL_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "novel_structure_data")

# ====== 缓存击穿保护：每个 cache_key 一个锁，并发时只有第一个请求去 DB ======
_cache_locks: dict = {}
_cache_locks_lock = threading.Lock()


def _get_cache_lock(key: str) -> threading.Lock:
    """获取指定缓存键对应的互斥锁，用于缓存击穿保护"""
    with _cache_locks_lock:
        if key not in _cache_locks:
            _cache_locks[key] = threading.Lock()
        return _cache_locks[key]


def _redis():
    """获取Redis客户端实例"""
    return redis_mod.redis_client


class NovelService:

    @staticmethod
    def create_novel(db: Session, author_user_id: int, author_name: str,
                     title: str, target_reader: str, description: str = "",
                     story_background: str = "", world_setting: str = "",
                     realm_setting: str = None, characters: str = None,
                     genre: str = None, cover_image: str = None,
                     plot_development: str = None, created_by: str = None,
                     sign_type: str = "non_exclusive") -> dict:
        """创建新作品，保存设定文件并同步到ES索引
        :param db: 数据库会话
        :param author_user_id: 作者用户ID
        :param author_name: 作者名称
        :param title: 作品名称
        :param target_reader: 目标读者类型（男频/女频）
        :param description: 作品简介（不超过600字）
        :param story_background: 故事背景
        :param world_setting: 世界观设定
        :param realm_setting: 境界设定
        :param characters: 角色设定
        :param genre: 题材标签
        :param cover_image: 封面图URL
        :param created_by: 创建者名称
        :return: 创建结果（含novel_unique_id）
        """
        if description and len(description) > 600:
            return fail("作品简介不能超过600字", code=400)
        novel_unique_id = uuid.uuid4().hex
        novel = NovelDAO.create(
            db,
            novel_unique_id=novel_unique_id,
            author_user_id=author_user_id,
            author_name=author_name,
            title=title,
            target_reader=target_reader,
            description=description,
            story_background=story_background,
            world_setting=world_setting,
            realm_setting=realm_setting,
            characters=characters,
            genre=genre,
            cover_image=cover_image,
            plot_development=plot_development,
            created_by=created_by,
            sign_type=sign_type
        )
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        os.makedirs(novel_dir, exist_ok=True)
        settings_content = f"""作品名称：{title}
目标读者类型：{target_reader}
作品简介：{description}
故事背景：{story_background}
世界观设定：{world_setting}
境界设定：{realm_setting or '无'}
标签：{genre or '无'}
角色设定：{characters or '无'}
剧情发展路线：{plot_development or '无'}"""
        with open(os.path.join(novel_dir, "作品设定.txt"), "w", encoding="utf-8") as f:
            f.write(settings_content)
        es_doc = {
            "novel_unique_id": novel_unique_id,
            "title": title,
            "author_name": author_name,
            "target_reader": target_reader,
            "genre": genre or "",
            "description": description,
            "cover_image": cover_image or "",
            "created_at": novel.created_at.isoformat() if novel.created_at else ""
        }
        es_service.index_novel(es_doc)
        r = _redis()
        if r:
            r.delete_pattern("novels:list:*")
            r.delete_pattern("novels:search:*")
        return success({"novel_unique_id": novel_unique_id, "title": title}, "作品创建成功")

    @staticmethod
    def list_novels(db: Session, target_reader: str = None, genre: str = None,
                    page: int = 1, page_size: int = 12,
                    author_user_id: int = None, exclude_exclusive: bool = False) -> dict:
        """分页查询作品列表，支持按受众和题材筛选，带Redis缓存
        :param db: 数据库会话
        :param target_reader: 受众筛选（男频/女频）
        :param genre: 题材筛选
        :param page: 页码
        :param page_size: 每页数量
        :param author_user_id: 按作者ID筛选，可选
        :return: 分页作品列表
        """
        cache_key = f"novels:list:tr={target_reader}:g={genre}:p={page}:ps={page_size}:uid={author_user_id}:ex={exclude_exclusive}"
        # 按用户筛选时不走缓存（每人数据不同，且可能频繁变化）
        r = _redis() if not author_user_id else None
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)

        # 缓存击穿保护：并发时只有第一个请求去 DB
        lock = _get_cache_lock(cache_key)
        with lock:
            # 双重检查：等锁期间可能已有其他线程写入了缓存
            if r:
                cached = r.get(cache_key)
                if cached:
                    return success(cached)

            novels, total = NovelDAO.list_novels(db, target_reader, genre, page, page_size, author_user_id=author_user_id, exclude_exclusive=exclude_exclusive)
            result = {
                "items": [{
                "novel_unique_id": n.novel_unique_id,
                "title": n.title,
                "author_name": n.author_name,
                "target_reader": n.target_reader,
                "genre": n.genre,
                "description": n.description[:100] if n.description else "",
                "cover_image": n.cover_image,
                "created_at": n.created_at.isoformat() if n.created_at else None
            } for n in novels],
            "total": total,
            "page": page,
            "page_size": page_size
        }
        if r:
            r.set(cache_key, result, ttl=30)
        return success(result)

    @staticmethod
    def search_novels(db: Session, keyword: str, page: int = 1, page_size: int = 12, exclude_exclusive: bool = False) -> dict:
        """按关键词搜索作品，优先走ES搜索引擎，兜底数据库模糊查询
        :param db: 数据库会话
        :param keyword: 搜索关键词
        :param page: 页码
        :param page_size: 每页数量
        :return: 搜索结果列表
        """
        cache_key = f"novels:search:kw={keyword}:p={page}:ps={page_size}:ex={exclude_exclusive}"
        r = _redis()
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)

        # 缓存击穿保护：并发时只有第一个请求去 ES/DB
        lock = _get_cache_lock(cache_key)
        with lock:
            if r:
                cached = r.get(cache_key)
                if cached:
                    return success(cached)

            es_results = es_service.search_novels(keyword, page, page_size)
            if es_results and es_results.get("hits", {}).get("total", {}).get("value", 0) > 0:
                items = []
                for hit in es_results["hits"]["hits"]:
                    src = hit["_source"]
                    items.append({
                        "novel_unique_id": src.get("novel_unique_id"),
                        "title": src.get("title"),
                        "author_name": src.get("author_name"),
                        "target_reader": src.get("target_reader"),
                        "genre": src.get("genre"),
                        "description": src.get("description", "")[:100],
                        "cover_image": src.get("cover_image", ""),
                    })
                result = {"items": items, "total": es_results["hits"]["total"]["value"], "page": page, "page_size": page_size}
            else:
                novels, total = NovelDAO.search_novels(db, keyword, page, page_size, exclude_exclusive=exclude_exclusive)
                result = {
                    "items": [{
                        "novel_unique_id": n.novel_unique_id,
                        "title": n.title,
                        "author_name": n.author_name,
                        "target_reader": n.target_reader,
                        "genre": n.genre,
                        "description": n.description[:100] if n.description else "",
                        "cover_image": n.cover_image,
                    } for n in novels],
                    "total": total, "page": page, "page_size": page_size
                }

            if r:
                r.set(cache_key, result)
            return success(result)

    @staticmethod
    def get_novel_detail(db: Session, novel_unique_id: str) -> dict:
        """查询单个作品的详细信息，带Redis缓存
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :return: 作品详情（含设定、角色等完整字段）
        """
        cache_key = f"novels:detail:{novel_unique_id}"
        r = _redis()
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)
        novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
        if not novel:
            return fail("作品不存在", code=404)
        result = {
            "novel_unique_id": novel.novel_unique_id,
            "title": novel.title,
            "author_name": novel.author_name,
            "author_user_id": novel.author_user_id,
            "target_reader": novel.target_reader,
            "genre": novel.genre,
            "description": novel.description,
            "story_background": novel.story_background,
            "world_setting": novel.world_setting,
            "realm_setting": novel.realm_setting,
            "characters": novel.characters,
            "plot_development": novel.plot_development,
            "cover_image": novel.cover_image,
            "sign_type": novel.sign_type,
            "created_at": novel.created_at.isoformat() if novel.created_at else None
        }
        if r:
            r.set(cache_key, result)
        return success(result)

    @staticmethod
    def get_user_novels(db: Session, user_id: int) -> dict:
        """获取当前用户创建的所有作品列表
        :param db: 数据库会话
        :param user_id: 用户ID
        :return: 作品列表
        """
        novels = NovelDAO.get_by_user_id(db, user_id)
        return success([{
            "novel_unique_id": n.novel_unique_id,
            "title": n.title,
            "target_reader": n.target_reader,
            "genre": n.genre,
            "description": n.description[:100] if n.description else "",
            "cover_image": n.cover_image,
            "created_at": n.created_at.isoformat() if n.created_at else None
        } for n in novels])

    @staticmethod
    def delete_novel(db: Session, novel_unique_id: str) -> dict:
        """删除作品及其所有关联数据（章节、互动、ES索引、向量数据库）
        核心删除（DB）同步完成，耗时操作（文件/ES/向量库）后台执行
        """
        import shutil, threading, asyncio
        from app.dao.chapter_dao import ChapterDAO
        from app.dao.interaction_dao import InteractionDAO
        novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
        if not novel:
            return fail("作品不存在", code=404)
        # 删除数据库中的章节记录
        ChapterDAO.delete_by_novel_id(db, novel_unique_id)
        # 删除作品圈互动（评论/点赞/收藏/关注）
        InteractionDAO.delete_by_novel_id(db, novel_unique_id)
        # 删除数据库作品记录
        NovelDAO.delete_by_unique_id(db, novel_unique_id)
        db.commit()
        # 清除 Redis 缓存
        r = _redis()
        if r:
            r.delete_pattern("novels:*")
            r.delete_pattern("chapters:*")

        # 耗时操作放到后台线程
        _nid = novel_unique_id
        _novel_dir = os.path.join(NOVEL_DATA_PATH, _nid)
        def _cleanup():
            try:
                # 删除本地文件
                if os.path.exists(_novel_dir):
                    shutil.rmtree(_novel_dir)
                # 删除 ES 索引
                es_service.delete_novel(_nid)
                # 清除 Redis 记忆体
                import app.utils.redis_cache as redis_mod
                r = redis_mod.redis_client
                if r and r.ping():
                    r.delete(f"memory:{_nid}")
            except BaseException as e:
                from app.utils.logger import system_logger
                system_logger.error(f"小说删除后台清理失败: {_nid} -> {e}")
        t = threading.Thread(target=_cleanup, daemon=True)
        t.start()

        return success(None, "作品已删除")

    @staticmethod
    def update_novel(db: Session, novel_unique_id: str, title: str = None,
                     target_reader: str = None, description: str = None,
                     story_background: str = None, world_setting: str = None,
                     realm_setting: str = None, characters: str = None,
                     genre: str = None, cover_image: str = None,
                     plot_development: str = None, sign_type: str = None) -> dict:
        """局部更新作品信息，只更新提供的字段并刷新ES索引
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param title: 新标题
        :param target_reader: 新受众类型
        :param description: 新简介（不超过600字）
        :param story_background: 新故事背景
        :param world_setting: 新世界观设定
        :param genre: 新题材标签
        :param cover_image: 新封面图URL
        :return: 更新结果
        """
        novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
        if not novel:
            return fail("作品不存在", code=404)
        
        if description and len(description) > 600:
            return fail("作品简介不能超过600字", code=400)
        
        # 只更新提供的字段
        if title is not None:
            novel.title = title
        if target_reader is not None:
            novel.target_reader = target_reader
        if description is not None:
            novel.description = description
        if story_background is not None:
            novel.story_background = story_background
        if world_setting is not None:
            novel.world_setting = world_setting
        if genre is not None:
            novel.genre = genre
        if cover_image is not None:
            novel.cover_image = cover_image
        if realm_setting is not None:
            novel.realm_setting = realm_setting
        if characters is not None:
            novel.characters = characters
        if plot_development is not None:
            novel.plot_development = plot_development
        if sign_type is not None:
            novel.sign_type = sign_type

        db.commit()

        # 更新作品设定.txt（同步 plot_development 到文件，供 AI 生成使用）
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        settings_file = os.path.join(novel_dir, "作品设定.txt")
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                txt_content = f.read()
            # 替换或追加 plot_development 行
            if "\n剧情发展路线：" in txt_content:
                txt_content = txt_content[:txt_content.rfind("\n剧情发展路线：")]
            if plot_development is not None or novel.plot_development:
                txt_content += f"\n剧情发展路线：{novel.plot_development or '无'}"
            with open(settings_file, "w", encoding="utf-8") as f:
                f.write(txt_content)
        
        # 更新 ES 索引
        es_doc = {
            "novel_unique_id": novel_unique_id,
            "title": novel.title,
            "author_name": novel.author_name,
            "target_reader": novel.target_reader,
            "genre": novel.genre or "",
            "description": novel.description,
            "cover_image": novel.cover_image or "",
            "created_at": novel.created_at.isoformat() if novel.created_at else ""
        }
        es_service.index_novel(es_doc)
        
        # 清除 Redis 缓存
        r = _redis()
        if r:
            r.delete_pattern("novels:*")
        
        return success({"novel_unique_id": novel_unique_id, "title": novel.title}, "作品更新成功")
