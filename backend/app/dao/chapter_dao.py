from sqlalchemy.orm import Session
from app.models.chapter import Chapter
from typing import Optional, List
from sqlalchemy import desc


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
