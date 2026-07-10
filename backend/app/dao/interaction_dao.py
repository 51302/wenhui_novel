from sqlalchemy.orm import Session
from app.models.interaction import WorkInteraction
from app.models.novel import Novel
from typing import Optional, List
from sqlalchemy import desc


class InteractionDAO:

    @staticmethod
    def create_or_update(db: Session, user_id: int, novel_unique_id: str,
                         interactor_id: int, interactor_name: str = None,
                         comment_text: str = None, is_like: int = 0,
                         is_follow: int = 0, is_bookmark: int = 0) -> WorkInteraction:
        # 评论每次都创建新记录（同一人可以多次评论同一作品）
        if comment_text is not None:
            interaction = WorkInteraction(
                user_id=user_id,
                novel_unique_id=novel_unique_id,
                comment_text=comment_text,
                is_like=0,
                is_follow=0,
                is_bookmark=0,
                interactor_id=interactor_id,
                interactor_name=interactor_name
            )
            db.add(interaction)
            db.commit()
            db.refresh(interaction)
            return interaction

        # 喜欢/关注/收藏：同一人对同一作品只留一条，更新已有记录
        existing = db.query(WorkInteraction).filter(
            WorkInteraction.novel_unique_id == novel_unique_id,
            WorkInteraction.interactor_id == interactor_id,
            WorkInteraction.comment_text == None
        ).first()
        if existing:
            if is_like:
                existing.is_like = 1
            if is_follow:
                existing.is_follow = 1
            if is_bookmark:
                existing.is_bookmark = 1
            db.commit()
            return existing

        interaction = WorkInteraction(
            user_id=user_id,
            novel_unique_id=novel_unique_id,
            comment_text=None,
            is_like=is_like,
            is_follow=is_follow,
            is_bookmark=is_bookmark,
            interactor_id=interactor_id,
            interactor_name=interactor_name
        )
        db.add(interaction)
        db.commit()
        db.refresh(interaction)
        return interaction

    @staticmethod
    def get_by_novel_id(db: Session, novel_unique_id: str, page: int = 1, page_size: int = 20) -> tuple:
        query = db.query(WorkInteraction).filter(
            WorkInteraction.novel_unique_id == novel_unique_id,
            WorkInteraction.comment_text.isnot(None),
            WorkInteraction.comment_text != ""
        )
        total = query.count()
        interactions = query.order_by(desc(WorkInteraction.created_at)).offset(
            (page - 1) * page_size).limit(page_size).all()
        return interactions, total

    @staticmethod
    def get_likes_count(db: Session, novel_unique_id: str) -> int:
        return db.query(WorkInteraction).filter(
            WorkInteraction.novel_unique_id == novel_unique_id,
            WorkInteraction.is_like == 1
        ).count()

    @staticmethod
    def get_bookmarks_count(db: Session, novel_unique_id: str) -> int:
        return db.query(WorkInteraction).filter(
            WorkInteraction.novel_unique_id == novel_unique_id,
            WorkInteraction.is_bookmark == 1
        ).count()

    @staticmethod
    def get_user_interaction(db: Session, novel_unique_id: str, interactor_id: int) -> Optional[WorkInteraction]:
        return db.query(WorkInteraction).filter(
            WorkInteraction.novel_unique_id == novel_unique_id,
            WorkInteraction.interactor_id == interactor_id
        ).first()

    @staticmethod
    def get_feed(db: Session, page: int = 1, page_size: int = 20) -> tuple:
        query = db.query(WorkInteraction, Novel).join(
            Novel, WorkInteraction.novel_unique_id == Novel.novel_unique_id
        )
        total = query.count()
        feed = query.order_by(desc(WorkInteraction.created_at)).offset(
            (page - 1) * page_size).limit(page_size).all()
        return feed, total

    @staticmethod
    def delete_interaction(db: Session, interaction_id: int):
        interaction = db.query(WorkInteraction).filter(WorkInteraction.id == interaction_id).first()
        if interaction:
            db.delete(interaction)
            db.commit()

    @staticmethod
    def delete_by_novel_id(db: Session, novel_unique_id: str):
        """删除该作品在作品圈中的所有互动记录"""
        deleted = db.query(WorkInteraction).filter(
            WorkInteraction.novel_unique_id == novel_unique_id
        ).delete(synchronize_session=False)
        db.commit()
        return deleted

    # ---------- "我的" 聚合查询 ----------
    @staticmethod
    def get_user_bookmarks(db: Session, user_id: int) -> list:
        """我收藏的作品列表"""
        rows = db.query(WorkInteraction, Novel).join(
            Novel, WorkInteraction.novel_unique_id == Novel.novel_unique_id
        ).filter(
            WorkInteraction.interactor_id == user_id,
            WorkInteraction.is_bookmark == 1
        ).order_by(desc(WorkInteraction.created_at)).all()
        return [{
            "novel_unique_id": n.novel_unique_id,
            "title": n.title,
            "cover_image": n.cover_image,
            "author_name": n.author_name,
            "genre": n.genre,
        } for _, n in rows]

    @staticmethod
    def get_user_following(db: Session, user_id: int) -> list:
        """我关注的人列表"""
        from app.models.user import User
        rows = db.query(WorkInteraction, User).join(
            User, WorkInteraction.user_id == User.id
        ).filter(
            WorkInteraction.interactor_id == user_id,
            WorkInteraction.is_follow == 1
        ).order_by(desc(WorkInteraction.created_at)).all()
        seen = set()
        result = []
        for _, u in rows:
            if u.id not in seen:
                seen.add(u.id)
                result.append({
                    "user_id": u.id,
                    "username": u.username,
                })
        return result

    @staticmethod
    def get_user_likes(db: Session, user_id: int) -> list:
        """我点赞的作品列表"""
        rows = db.query(WorkInteraction, Novel).join(
            Novel, WorkInteraction.novel_unique_id == Novel.novel_unique_id
        ).filter(
            WorkInteraction.interactor_id == user_id,
            WorkInteraction.is_like == 1
        ).order_by(desc(WorkInteraction.created_at)).all()
        return [{
            "novel_unique_id": n.novel_unique_id,
            "title": n.title,
            "cover_image": n.cover_image,
            "author_name": n.author_name,
            "genre": n.genre,
        } for _, n in rows]

    @staticmethod
    def get_followers_count(db: Session, user_id: int) -> int:
        """关注我的人数（粉丝）"""
        return db.query(WorkInteraction).filter(
            WorkInteraction.user_id == user_id,
            WorkInteraction.is_follow == 1
        ).count()
