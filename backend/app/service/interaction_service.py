from sqlalchemy.orm import Session
from app.dao.interaction_dao import InteractionDAO
from app.utils.response import success, fail
import app.utils.redis_cache as redis_mod


def _redis():
    return redis_mod.redis_client


class InteractionService:

    @staticmethod
    def comment(db: Session, novel_unique_id: str, user_id: int,
                interactor_id: int, interactor_name: str, comment_text: str) -> dict:
        if not comment_text or not comment_text.strip():
            return fail("评论内容不能为空", code=400)
        interaction = InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name,
            comment_text=comment_text
        )
        r = _redis()
        if r:
            r.delete_pattern(f"interactions:*:{novel_unique_id}:*")
        return success({"id": interaction.id}, "评论成功")

    @staticmethod
    def like(db: Session, novel_unique_id: str, user_id: int,
             interactor_id: int, interactor_name: str) -> dict:
        InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name, is_like=1
        )
        r = _redis()
        if r:
            r.delete_pattern(f"interactions:*:{novel_unique_id}:*")
        return success(None, "点赞成功")

    @staticmethod
    def follow(db: Session, novel_unique_id: str, user_id: int,
               interactor_id: int, interactor_name: str) -> dict:
        InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name, is_follow=1
        )
        return success(None, "关注成功")

    @staticmethod
    def bookmark(db: Session, novel_unique_id: str, user_id: int,
                 interactor_id: int, interactor_name: str) -> dict:
        InteractionDAO.create_or_update(
            db, user_id=user_id, novel_unique_id=novel_unique_id,
            interactor_id=interactor_id, interactor_name=interactor_name, is_bookmark=1
        )
        r = _redis()
        if r:
            r.delete_pattern(f"interactions:*:{novel_unique_id}:*")
        return success(None, "收藏成功")

    @staticmethod
    def get_comments(db: Session, novel_unique_id: str, page: int = 1, page_size: int = 20) -> dict:
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
        from app.dao.chapter_dao import ChapterDAO
        feed, total = InteractionDAO.get_feed(db, page, page_size)
        items = []
        
        # 获取当前用户ID
        current_user_id = current_user.get("user_id") if current_user else None
        
        for i in feed:
            interaction = i[0]
            novel = i[1]
            # 查找该作品最新已发布章节
            latest_chapter = None
            if novel:
                chapters = ChapterDAO.get_by_novel_id(db, interaction.novel_unique_id)
                published = [c for c in chapters if c.is_published == 1]
                published.sort(key=lambda c: c.created_at, reverse=True)
                if published:
                    latest_chapter = published[0]

            # 查询当前用户对该作品的互动状态
            user_interaction = None
            if current_user_id and novel:
                user_interaction = InteractionDAO.get_user_interaction(
                    db, interaction.novel_unique_id, current_user_id
                )

            items.append({
                "id": interaction.id,
                "user_id": interaction.user_id,
                "novel_unique_id": interaction.novel_unique_id,
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
                # 当前用户的互动状态
                "user_is_like": user_interaction.is_like if user_interaction else 0,
                "user_is_bookmark": user_interaction.is_bookmark if user_interaction else 0,
                "user_is_follow": user_interaction.is_follow if user_interaction else 0,
                "likes_count": InteractionDAO.get_likes_count(db, interaction.novel_unique_id),
                "bookmarks_count": InteractionDAO.get_bookmarks_count(db, interaction.novel_unique_id)
            })
        return success({
            "items": items,
            "total": total, "page": page, "page_size": page_size
        })
