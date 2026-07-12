from sqlalchemy.orm import Session
from app.models.bookshelf import Bookshelf
from app.models.novel import Novel
from typing import List
from sqlalchemy import desc
from datetime import datetime


class BookshelfDAO:

    @staticmethod
    def add(db: Session, user_id: int, novel_unique_id: str) -> Bookshelf:
        """将作品加入用户书架（已存在则直接返回）
        :param db: 数据库会话
        :param user_id: 用户ID
        :param novel_unique_id: 作品唯一ID
        :return: 书架记录对象
        """
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
        """将作品从用户书架移除
        :param db: 数据库会话
        :param user_id: 用户ID
        :param novel_unique_id: 作品唯一ID
        :return: 是否成功移除
        """
        deleted = db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id,
            Bookshelf.novel_unique_id == novel_unique_id
        ).delete(synchronize_session=False)
        db.commit()
        return deleted > 0

    @staticmethod
    def is_in_bookshelf(db: Session, user_id: int, novel_unique_id: str) -> bool:
        """判断某作品是否在用户书架中
        :param db: 数据库会话
        :param user_id: 用户ID
        :param novel_unique_id: 作品唯一ID
        :return: 是否在书架中
        """
        return db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id,
            Bookshelf.novel_unique_id == novel_unique_id
        ).count() > 0

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> List[Bookshelf]:
        """查询用户书架中的所有记录（按更新时间降序）
        :param db: 数据库会话
        :param user_id: 用户ID
        :return: 书架记录列表
        """
        return db.query(Bookshelf).filter(
            Bookshelf.user_id == user_id
        ).order_by(desc(Bookshelf.updated_at)).all()

    @staticmethod
    def list_with_novels(db: Session, user_id: int):
        """查询用户书架并关联作品详情（按更新时间降序）
        :param db: 数据库会话
        :param user_id: 用户ID
        :return: (书架记录, 作品对象) 元组列表
        """
        return db.query(Bookshelf, Novel).join(
            Novel, Bookshelf.novel_unique_id == Novel.novel_unique_id
        ).filter(
            Bookshelf.user_id == user_id
        ).order_by(desc(Bookshelf.updated_at)).all()

    @staticmethod
    def save_progress(db: Session, user_id: int, novel_unique_id: str,
                      chapter_unique_id: str, chapter_name: str) -> bool:
        """保存用户对某作品的阅读进度（最后阅读的章节）
        :param db: 数据库会话
        :param user_id: 用户ID
        :param novel_unique_id: 作品唯一ID
        :param chapter_unique_id: 最后阅读章节ID
        :param chapter_name: 最后阅读章节名称
        :return: 是否保存成功（书架中无此作品时返回False）
        """
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
