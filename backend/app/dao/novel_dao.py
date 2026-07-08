from sqlalchemy.orm import Session
from app.models.novel import Novel
from typing import Optional, List
from sqlalchemy import desc


class NovelDAO:

    @staticmethod
    def create(db: Session, **kwargs) -> Novel:
        novel = Novel(**kwargs)
        db.add(novel)
        db.commit()
        db.refresh(novel)
        return novel

    @staticmethod
    def get_by_unique_id(db: Session, novel_unique_id: str) -> Optional[Novel]:
        return db.query(Novel).filter(Novel.novel_unique_id == novel_unique_id).first()

    @staticmethod
    def get_by_id(db: Session, novel_id: int) -> Optional[Novel]:
        return db.query(Novel).filter(Novel.id == novel_id).first()

    @staticmethod
    def list_novels(db: Session, target_reader: str = None, genre: str = None,
                    page: int = 1, page_size: int = 12) -> tuple:
        query = db.query(Novel)
        if target_reader:
            query = query.filter(Novel.target_reader == target_reader)
        if genre:
            query = query.filter(Novel.genre == genre)
        total = query.count()
        novels = query.order_by(desc(Novel.created_at)).offset(
            (page - 1) * page_size).limit(page_size).all()
        return novels, total

    @staticmethod
    def search_novels(db: Session, keyword: str, page: int = 1, page_size: int = 12) -> tuple:
        query = db.query(Novel).filter(
            (Novel.title.like(f"%{keyword}%")) | (Novel.author_name.like(f"%{keyword}%"))
        )
        total = query.count()
        novels = query.order_by(desc(Novel.created_at)).offset(
            (page - 1) * page_size).limit(page_size).all()
        return novels, total

    @staticmethod
    def get_by_user_id(db: Session, user_id: int) -> List[Novel]:
        return db.query(Novel).filter(Novel.author_user_id == user_id).order_by(desc(Novel.created_at)).all()

    @staticmethod
    def delete_by_unique_id(db: Session, novel_unique_id: str) -> bool:
        novel = db.query(Novel).filter(Novel.novel_unique_id == novel_unique_id).first()
        if novel:
            db.delete(novel)
            db.commit()
            return True
        return False
