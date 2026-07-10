import json
import os
import uuid
import shutil
from sqlalchemy.orm import Session
from app.dao.novel_dao import NovelDAO
from app.utils.response import success, fail
import app.utils.redis_cache as redis_mod
from app.service.es_service import es_service

NOVEL_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "novel_structure_data")


def _redis():
    return redis_mod.redis_client


class NovelService:

    @staticmethod
    def create_novel(db: Session, author_user_id: int, author_name: str,
                     title: str, target_reader: str, description: str = "",
                     story_background: str = "", world_setting: str = "",
                     realm_setting: str = None, characters: str = None,
                     genre: str = None, cover_image: str = None, created_by: str = None) -> dict:
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
            created_by=created_by
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
角色设定：{characters or '无'}"""
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
                    page: int = 1, page_size: int = 12) -> dict:
        cache_key = f"novels:list:tr={target_reader}:g={genre}:p={page}:ps={page_size}"
        r = _redis()
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)
        novels, total = NovelDAO.list_novels(db, target_reader, genre, page, page_size)
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
            r.set(cache_key, result)
        return success(result)

    @staticmethod
    def search_novels(db: Session, keyword: str, page: int = 1, page_size: int = 12) -> dict:
        cache_key = f"novels:search:kw={keyword}:p={page}:ps={page_size}"
        r = _redis()
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
            novels, total = NovelDAO.search_novels(db, keyword, page, page_size)
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
            "cover_image": novel.cover_image,
            "created_at": novel.created_at.isoformat() if novel.created_at else None
        }
        if r:
            r.set(cache_key, result)
        return success(result)

    @staticmethod
    def get_user_novels(db: Session, user_id: int) -> dict:
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
        import shutil
        from app.dao.chapter_dao import ChapterDAO
        from app.dao.interaction_dao import InteractionDAO
        novel = NovelDAO.get_by_unique_id(db, novel_unique_id)
        if not novel:
            return fail("作品不存在", code=404)
        # 删除数据库中的章节记录
        ChapterDAO.delete_by_novel_id(db, novel_unique_id)
        # 删除作品圈互动（评论/点赞/收藏/关注）
        InteractionDAO.delete_by_novel_id(db, novel_unique_id)
        # 删除 novel_structure_data 下对应文件夹（含作品设定.txt 和所有章节.txt）
        novel_dir = os.path.join(NOVEL_DATA_PATH, novel_unique_id)
        if os.path.exists(novel_dir):
            shutil.rmtree(novel_dir)
        # 删除 ES 索引
        es_service.delete_novel(novel_unique_id)
        # 删除数据库作品记录
        NovelDAO.delete_by_unique_id(db, novel_unique_id)
        # 清除 Redis 缓存
        r = _redis()
        if r:
            r.delete_pattern("novels:*")
            r.delete_pattern("chapters:*")

        # 清除向量数据库中该作品的所有记录
        from app.utils.chroma_client import chroma_memory
        if chroma_memory:
            chroma_memory.delete_by_prefix(f"{novel_unique_id}_")

        return success(None, "作品及所有章节已删除")

    @staticmethod
    def update_novel(db: Session, novel_unique_id: str, title: str = None,
                     target_reader: str = None, description: str = None,
                     story_background: str = None, world_setting: str = None,
                     genre: str = None, cover_image: str = None) -> dict:
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
        
        db.commit()
        
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
