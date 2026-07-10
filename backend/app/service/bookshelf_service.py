from sqlalchemy.orm import Session
from app.dao.bookshelf_dao import BookshelfDAO
from app.dao.interaction_dao import InteractionDAO
from app.dao.user_dao import UserDAO
from app.utils.response import success, fail


class BookshelfService:

    @staticmethod
    def add_to_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> dict:
        BookshelfDAO.add(db, user_id, novel_unique_id)
        return success(None, "已加入书架")

    @staticmethod
    def remove_from_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> dict:
        BookshelfDAO.remove(db, user_id, novel_unique_id)
        return success(None, "已移出书架")

    @staticmethod
    def is_in_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> dict:
        in_shelf = BookshelfDAO.is_in_bookshelf(db, user_id, novel_unique_id)
        return success({"in_bookshelf": in_shelf})

    @staticmethod
    def list_bookshelf(db: Session, user_id: int) -> dict:
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
        return success({"items": items, "total": len(items)})

    @staticmethod
    def save_progress(db: Session, user_id: int, novel_unique_id: str,
                      chapter_unique_id: str, chapter_name: str) -> dict:
        ok = BookshelfDAO.save_progress(db, user_id, novel_unique_id, chapter_unique_id, chapter_name)
        if ok:
            return success(None, "阅读进度已保存")
        return success(None, "未加入书架，跳过进度保存")


class ProfileService:

    @staticmethod
    def get_profile(db: Session, user_id: int) -> dict:
        user = UserDAO.get_by_id(db, user_id)
        if not user:
            return fail("用户不存在", code=404)

        bookmarked_novels = InteractionDAO.get_user_bookmarks(db, user_id)
        following_users = InteractionDAO.get_user_following(db, user_id)
        liked_novels = InteractionDAO.get_user_likes(db, user_id)
        followers_count = InteractionDAO.get_followers_count(db, user_id)
        following_count = len(following_users)
        bookshelf_count = len(BookshelfDAO.list_by_user(db, user_id))

        from datetime import datetime
        is_vip = user.is_super_admin == 1 or (user.vip_expire_at and user.vip_expire_at > datetime.now())

        return success({
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "is_vip": is_vip,
            "vip_expire_at": user.vip_expire_at.strftime('%Y-%m-%d %H:%M:%S') if user.vip_expire_at else None,
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
        })
