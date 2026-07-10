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
                "added_at": bs.created_at.isoformat() if bs.created_at else None
            })
        return success({"items": items, "total": len(items)})


class ProfileService:

    @staticmethod
    def get_profile(db: Session, user_id: int) -> dict:
        user = UserDAO.get_by_id(db, user_id)
        if not user:
            return fail("用户不存在", code=404)

        # 我收藏的作品
        bookmarked_novels = InteractionDAO.get_user_bookmarks(db, user_id)

        # 我关注的人
        following_users = InteractionDAO.get_user_following(db, user_id)

        # 我点赞的作品
        liked_novels = InteractionDAO.get_user_likes(db, user_id)

        # 粉丝数量（关注我的人）
        followers_count = InteractionDAO.get_followers_count(db, user_id)

        # 关注数量
        following_count = len(following_users)

        # 书架数量
        from app.dao.bookshelf_dao import BookshelfDAO
        bookshelf_count = len(BookshelfDAO.list_by_user(db, user_id))

        return success({
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "is_vip": user.is_super_admin == 1 or (user.vip_expire_at and user.vip_expire_at.strftime('%Y-%m-%d %H:%M:%S') > __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
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
