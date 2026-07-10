from sqlalchemy.orm import Session
from app.models.chapter import Chapter
from typing import Optional, List, Dict
from sqlalchemy import desc, and_, func


class ChapterDAO:

    @staticmethod
    def create(db: Session, **kwargs) -> Chapter:
        chapter = Chapter(**kwargs)
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        return chapter

    @staticmethod
    def get_by_unique_id(db: Session, chapter_unique_id: str) -> Optional[Chapter]:
        return db.query(Chapter).filter(Chapter.chapter_unique_id == chapter_unique_id).first()

    @staticmethod
    def get_by_novel_id(db: Session, novel_unique_id: str) -> List[Chapter]:
        return db.query(Chapter).filter(
            Chapter.novel_unique_id == novel_unique_id
        ).order_by(Chapter.created_at.asc()).all()

    @staticmethod
    def count_by_novel_id(db: Session, novel_unique_id: str) -> int:
        return db.query(Chapter).filter(
            Chapter.novel_unique_id == novel_unique_id
        ).count()

    @staticmethod
    def get_drafts(db: Session, user_id: int) -> List[Chapter]:
        return db.query(Chapter).filter(
            Chapter.user_id == user_id,
            Chapter.is_published == 0
        ).order_by(desc(Chapter.created_at)).all()

    @staticmethod
    def update(db: Session, chapter: Chapter, **kwargs):
        for key, value in kwargs.items():
            if hasattr(chapter, key):
                setattr(chapter, key, value)
        db.commit()

    @staticmethod
    def delete(db: Session, chapter_unique_id: str):
        chapter = db.query(Chapter).filter(Chapter.chapter_unique_id == chapter_unique_id).first()
        if chapter:
            db.delete(chapter)
            db.commit()

    @staticmethod
    def delete_by_novel_id(db: Session, novel_unique_id: str):
        db.query(Chapter).filter(Chapter.novel_unique_id == novel_unique_id).delete()
        db.commit()

    @staticmethod
    def get_latest_published_batch(db: Session, novel_ids: List[str]) -> Dict[str, Optional[Chapter]]:
        """批量获取每个作品的最新已发布章节（一条 JOIN 子查询替代 N 次查询）"""
        if not novel_ids:
            return {}
        # 子查询：每个 novel 的最新 published 章节 ID
        sub = (
            db.query(
                Chapter.novel_unique_id,
                func.max(Chapter.created_at).label("max_created")
            )
            .filter(Chapter.novel_unique_id.in_(novel_ids), Chapter.is_published == 1)
            .group_by(Chapter.novel_unique_id)
            .subquery()
        )
        chapters = (
            db.query(Chapter)
            .join(sub, and_(
                Chapter.novel_unique_id == sub.c.novel_unique_id,
                Chapter.created_at == sub.c.max_created
            ))
            .all()
        )
        return {c.novel_unique_id: c for c in chapters}
