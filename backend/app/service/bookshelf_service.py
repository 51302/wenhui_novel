"""
书架/个人主页服务 — 优化版：Redis 缓存
"""
from sqlalchemy.orm import Session
from app.dao.bookshelf_dao import BookshelfDAO
from app.dao.interaction_dao import InteractionDAO
from app.dao.user_dao import UserDAO
from app.utils.response import success, fail
import app.utils.redis_cache as redis_mod
from datetime import datetime

# 缓存 TTL
_PROFILE_CACHE_TTL = 60       # 个人主页缓存 60秒
_BOOKSHELF_CACHE_TTL = 30     # 书架缓存 30秒
_PROFILE_CACHE_PREFIX = "profile:"
_BOOKSHELF_CACHE_PREFIX = "bookshelf:list:"


def _redis():
    return redis_mod.redis_client


class BookshelfService:

    @staticmethod
    def add_to_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> dict:
        BookshelfDAO.add(db, user_id, novel_unique_id)
        # 清除书架缓存和个人主页缓存
        r = _redis()
        if r:
            r.delete(f"{_BOOKSHELF_CACHE_PREFIX}{user_id}", f"{_PROFILE_CACHE_PREFIX}{user_id}")
        return success(None, "已加入书架")

    @staticmethod
    def remove_from_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> dict:
        BookshelfDAO.remove(db, user_id, novel_unique_id)
        r = _redis()
        if r:
            r.delete(f"{_BOOKSHELF_CACHE_PREFIX}{user_id}", f"{_PROFILE_CACHE_PREFIX}{user_id}")
        return success(None, "已移出书架")

    @staticmethod
    def is_in_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> dict:
        in_shelf = BookshelfDAO.is_in_bookshelf(db, user_id, novel_unique_id)
        return success({"in_bookshelf": in_shelf})

    @staticmethod
    def list_bookshelf(db: Session, user_id: int) -> dict:
        # 优先从 Redis 读取
        r = _redis()
        cache_key = f"{_BOOKSHELF_CACHE_PREFIX}{user_id}"
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)

        rows = BookshelfDAO.list_with_novels(db, user_id)
        items = []
        for bs, novel in rows:
            items.append({
                "novel_unique_id": novel.novel_unique_id,
                "title": novel.title,
                "author_name": novel.author_name,
                "cover_image": novel.cover_image,
                "description": (novel.description or "")[:100],
                "genre": novel.genre,
                "target_reader": novel.target_reader,
                "last_chapter_unique_id": bs.last_chapter_unique_id,
                "last_chapter_name": bs.last_chapter_name,
                "added_at": bs.created_at.isoformat() if bs.created_at else None
            })
        result = {"items": items, "total": len(items)}

        # 写入缓存
        if r:
            r.set(cache_key, result, ttl=_BOOKSHELF_CACHE_TTL)

        return success(result)

    @staticmethod
    def save_progress(db: Session, user_id: int, novel_unique_id: str,
                      chapter_unique_id: str, chapter_name: str) -> dict:
        ok = BookshelfDAO.save_progress(db, user_id, novel_unique_id, chapter_unique_id, chapter_name)
        # 更新进度也刷新书架缓存
        r = _redis()
        if r:
            r.delete(f"{_BOOKSHELF_CACHE_PREFIX}{user_id}")
        if ok:
            return success(None, "阅读进度已保存")
        return success(None, "未加入书架，跳过进度保存")


class ProfileService:

    @staticmethod
    def get_profile(db: Session, user_id: int) -> dict:
        # 优先从 Redis 读取
        r = _redis()
        cache_key = f"{_PROFILE_CACHE_PREFIX}{user_id}"
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)

        user = UserDAO.get_by_id(db, user_id)
        if not user:
            return fail("用户不存在", code=404)

        # 以下 6 个查询合并为批量方式
        bookmarked_novels = InteractionDAO.get_user_bookmarks(db, user_id)
        following_users = InteractionDAO.get_user_following(db, user_id)
        liked_novels = InteractionDAO.get_user_likes(db, user_id)
        followers_count = InteractionDAO.get_followers_count(db, user_id)
        following_count = len(following_users)
        bookshelf_count = len(BookshelfDAO.list_by_user(db, user_id))

        is_vip = user.is_super_admin == 1 or (user.vip_expire_at and user.vip_expire_at > datetime.now())

        result = {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "is_vip": is_vip,
            "vip_expire_at": user.vip_expire_at.strftime('%Y-%m-%d %H:%M:%S') if user.vip_expire_at else None,
            "free_generate_quota": user.free_generate_quota or 0,
            "stats": {
                "bookshelf": bookshelf_count,
                "followers": followers_count,
                "following": following_count,
                "likes": len(liked_novels),
                "bookmarks": len(bookmarked_novels)
            },
            "bookmarks": bookmarked_novels,
            "following": following_users,
            "likes": liked_novels,
        }

        # 写入缓存
        if r:
            r.set(cache_key, result, ttl=_PROFILE_CACHE_TTL)

        return success(result)
