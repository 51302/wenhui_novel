from sqlalchemy.orm import Session
from app.models.bookshelf import Bookshelf
from app.models.novel import Novel
from typing import List
from sqlalchemy import desc
from datetime import datetime


class BookshelfDAO:

    @staticmethod
    def add(db: Session, user_id: int, novel_unique_id: str) -> Bookshelf:
        existing = db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id,
            Bookshelf.novel_unique_id == novel_unique_id
        ).first()
        if existing:
            return existing
        item = Bookshelf(user_id=user_id, novel_unique_id=novel_unique_id)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def remove(db: Session, user_id: int, novel_unique_id: str) -> bool:
        deleted = db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id,
            Bookshelf.novel_unique_id == novel_unique_id
        ).delete(synchronize_session=False)
        db.commit()
        return deleted > 0

    @staticmethod
    def is_in_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> bool:
        return db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id,
            Bookshelf.novel_unique_id == novel_unique_id
        ).count() > 0

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> List[Bookshelf]:
        return db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id
        ).order_by(desc(Bookshelf.updated_at)).all()

    @staticmethod
    def list_with_novels(db: Session, user_id: int):
        return db.query(Bookshelf, Novel).join(
            Novel, Bookshelf.novel_unique_id == Novel.novel_unique_id
        ).filter(
            Bookshelf.user_id == user_id
        ).order_by(desc(Bookshelf.updated_at)).all()

    @staticmethod
    def save_progress(db: Session, user_id: int, novel_unique_id: str,
                      chapter_unique_id: str, chapter_name: str) -> bool:
        item = db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id,
            Bookshelf.novel_unique_id == novel_unique_id
        ).first()
        if not item:
            return False
        item.last_chapter_unique_id = chapter_unique_id
        item.last_chapter_name = chapter_name
        item.updated_at = datetime.now()
        db.commit()
        return True
