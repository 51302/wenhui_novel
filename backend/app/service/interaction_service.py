"""
互动服务 — 优化版：修复 N+1 查询 + Redis 缓存动态流
"""
from sqlalchemy.orm import Session
from app.dao.interaction_dao import InteractionDAO
from app.utils.response import success, fail
import app.utils.redis_cache as redis_mod


def _redis():
    """获取Redis客户端实例"""
    return redis_mod.redis_client

# 动态流缓存 TTL：60秒（降低一点，允许实时性但大幅提升性能）
FEED_CACHE_TTL = 60
FEED_CACHE_PREFIX = "interactions:feed:"


class InteractionService:

    @staticmethod
    def comment(db: Session, novel_unique_id: str, user_id: int,
                interactor_id: int, interactor_name: str, comment_text: str) -> dict:
        """发表评论到指定作品的作品圈
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param user_id: 作品作者ID
        :param interactor_id: 评论者ID
        :param interactor_name: 评论者名称
        :param comment_text: 评论内容
        :return: 操作结果
        """
        if not comment_text or not comment_text.strip():
            return fail("评论内容不能为空", code=400)
        interaction = InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name,
            comment_text=comment_text
        )
        r = _redis()
        if r:
            r.delete_pattern(f"{FEED_CACHE_PREFIX}*")
            r.delete_pattern(f"interactions:*:{novel_unique_id}:*")
        return success({"id": interaction.id}, "评论成功")

    @staticmethod
    def like(db: Session, novel_unique_id: str, user_id: int,
             interactor_id: int, interactor_name: str) -> dict:
        """点赞指定作品的作品圈
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param user_id: 作品作者ID
        :param interactor_id: 点赞者ID
        :param interactor_name: 点赞者名称
        :return: 操作结果
        """
        InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name, is_like=1
        )
        r = _redis()
        if r:
            r.delete_pattern(f"{FEED_CACHE_PREFIX}*")
            r.delete_pattern(f"interactions:*:{novel_unique_id}:*")
        return success(None, "点赞成功")

    @staticmethod
    def follow(db: Session, novel_unique_id: str, user_id: int,
               interactor_id: int, interactor_name: str) -> dict:
        """关注指定作品的作品圈
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param user_id: 作品作者ID
        :param interactor_id: 关注者ID
        :param interactor_name: 关注者名称
        :return: 操作结果
        """
        InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name, is_follow=1
        )
        return success(None, "关注成功")

    @staticmethod
    def bookmark(db: Session, novel_unique_id: str, user_id: int,
                 interactor_id: int, interactor_name: str) -> dict:
        """收藏指定作品的作品圈
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param user_id: 作品作者ID
        :param interactor_id: 收藏者ID
        :param interactor_name: 收藏者名称
        :return: 操作结果
        """
        InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name, is_bookmark=1
        )
        r = _redis()
        if r:
            r.delete_pattern(f"{FEED_CACHE_PREFIX}*")
            r.delete_pattern(f"interactions:*:{novel_unique_id}:*")
        return success(None, "收藏成功")

    @staticmethod
    def get_comments(db: Session, novel_unique_id: str, page: int = 1, page_size: int = 20) -> dict:
        """分页查询指定作品的所有互动评论，带Redis缓存
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :param page: 页码
        :param page_size: 每页数量
        :return: 分页评论列表（含点赞数和收藏数）
        """
        cache_key = f"interactions:comments:{novel_unique_id}:p={page}:ps={page_size}"
        r = _redis()
        if r:
            cached = r.get(cache_key)
            if cached:
                return success(cached)
        interactions, total = InteractionDAO.get_by_novel_id(db, novel_unique_id, page, page_size)
        likes = InteractionDAO.get_likes_count(db, novel_unique_id)
        bookmarks = InteractionDAO.get_bookmarks_count(db, novel_unique_id)
        result = {
            "items": [{
                "id": i.id,
                "interactor_id": i.interactor_id,
                "interactor_name": i.interactor_name,
                "comment_text": i.comment_text,
                "is_like": i.is_like,
                "is_follow": i.is_follow,
                "is_bookmark": i.is_bookmark,
                "created_at": i.created_at.isoformat() if i.created_at else None
            } for i in interactions],
            "total": total, "page": page, "page_size": page_size,
            "likes_count": likes, "bookmarks_count": bookmarks
        }
        if r:
            r.set(cache_key, result)
        return success(result)

    @staticmethod
    def get_feed(db: Session, page: int = 1, page_size: int = 20, current_user: dict = None) -> dict:
        """获取互动动态流（优化版：Redis缓存 + 批量获取章节避免N+1）"""
        from app.dao.chapter_dao import ChapterDAO
        from app.models.chapter import Chapter
        from sqlalchemy import desc

        # 尝试 Redis 缓存
        r = _redis()
        cache_key = f"{FEED_CACHE_PREFIX}p={page}:ps={page_size}"
        if r:
            cached = r.get(cache_key)
            if cached:
                # 缓存命中后仍需补充当前用户的互动状态（实时性要求）
                current_user_id = current_user.get("user_id") if current_user else None
                if current_user_id:
                    items = cached.get("items", [])
                    # 批量查询用户对这批作品的所有互动
                    nids = [item.get("novel_unique_id") for item in items if item.get("novel_unique_id")]
                    if nids:
                        user_interactions = InteractionDAO.get_user_interactions_batch(db, nids, current_user_id)
                        for item in items:
                            nid = item.get("novel_unique_id")
                            ui = user_interactions.get(nid)
                            item["user_is_like"] = ui.is_like if ui else 0
                            item["user_is_bookmark"] = ui.is_bookmark if ui else 0
                            item["user_is_follow"] = ui.is_follow if ui else 0
                    cached["items"] = items
                return success(cached)

        current_user_id = current_user.get("user_id") if current_user else None
        feed, total = InteractionDAO.get_feed(db, page, page_size)

        # ====== 优化：批量获取所有涉及作品的章节（替代逐个N+1查询） ======
        novel_ids_in_feed = [i[1].novel_unique_id for i in feed if i[1]]
        batch_chapters = {}
        if novel_ids_in_feed:
            batch_chapters = ChapterDAO.get_latest_published_batch(db, novel_ids_in_feed)

        # 批量查询当前用户对所有展示作品的互动状态
        user_interactions = {}
        if current_user_id and novel_ids_in_feed:
            user_interactions = InteractionDAO.get_user_interactions_batch(db, novel_ids_in_feed, current_user_id)

        # 批量获取点赞数和收藏数
        likes_map = {}
        bookmarks_map = {}
        if novel_ids_in_feed:
            counts = InteractionDAO.get_likes_bookmarks_batch(db, novel_ids_in_feed)
            likes_map = counts.get("likes", {})
            bookmarks_map = counts.get("bookmarks", {})

        items = []
        for i in feed:
            interaction = i[0]
            novel = i[1]
            nid = interaction.novel_unique_id
            latest_chapter = batch_chapters.get(nid)
            ui = user_interactions.get(nid)

            items.append({
                "id": interaction.id,
                "user_id": interaction.user_id,
                "novel_unique_id": nid,
                "interactor_id": interaction.interactor_id,
                "interactor_name": interaction.interactor_name,
                "comment_text": interaction.comment_text,
                "is_like": interaction.is_like,
                "is_follow": interaction.is_follow,
                "is_bookmark": interaction.is_bookmark,
                "created_at": interaction.created_at.isoformat() if interaction.created_at else None,
                "novel": {
                    "title": novel.title,
                    "cover_image": novel.cover_image,
                    "author_name": novel.author_name
                } if novel else None,
                "latest_chapter": {
                    "chapter_unique_id": latest_chapter.chapter_unique_id,
                    "chapter_name": latest_chapter.chapter_name,
                    "chapter_summary": latest_chapter.chapter_summary
                } if latest_chapter else None,
                "user_is_like": ui.is_like if ui else 0,
                "user_is_bookmark": ui.is_bookmark if ui else 0,
                "user_is_follow": ui.is_follow if ui else 0,
                "likes_count": likes_map.get(nid, 0),
                "bookmarks_count": bookmarks_map.get(nid, 0)
            })

        result = {
            "items": items,
            "total": total, "page": page, "page_size": page_size
        }

        # 写入 Redis 缓存（不含用户互动状态，因为那是实时数据）
        # 存储时不带 user_is_xxx 字段，每次取时单独注入
        cache_data = {
            "items": [{k: v for k, v in item.items() if k not in ("user_is_like", "user_is_bookmark", "user_is_follow")} for item in items],
            "total": total, "page": page, "page_size": page_size
        }
        if r:
            r.set(cache_key, cache_data, ttl=FEED_CACHE_TTL)

        return success(result)
