from sqlalchemy.orm import Session
from app.models.chapter import Chapter
from typing import Optional, List, Dict
from sqlalchemy import desc, and_, func


class ChapterDAO:

    @staticmethod
    def create(db: Session, **kwargs) -> Chapter:
        """创建新章节
        :param db: 数据库会话
        :param kwargs: 章节字段键值对
        :return: 新创建的章节对象
        """
        chapter = Chapter(**kwargs)
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        return chapter

    @staticmethod
    def get_by_unique_id(db: Session, chapter_unique_id: str) -> Optional[Chapter]:
        """根据章节唯一ID查询章节
        :param db: 数据库会话
        :param chapter_unique_id: 章节唯一ID
        :return: 章节对象或None
        """
        return db.query(Chapter).filter(Chapter.chapter_unique_id == chapter_unique_id).first()

    @staticmethod
    def get_by_novel_id(db: Session, novel_unique_id: str) -> List[Chapter]:
        """查询某作品的全部章节（按创建时间升序）
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :return: 章节列表
        """
        return db.query(Chapter).filter(
            Chapter.novel_unique_id == novel_unique_id
        ).order_by(Chapter.created_at.asc()).all()

    @staticmethod
    def count_by_novel_id(db: Session, novel_unique_id: str) -> int:
        """统计某作品的章节总数
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :return: 章节数量
        """
        return db.query(Chapter).filter(
            Chapter.novel_unique_id == novel_unique_id
        ).count()

    @staticmethod
    def get_drafts(db: Session, user_id: int) -> List[Chapter]:
        """查询某用户的所有草稿章节
        :param db: 数据库会话
        :param user_id: 用户ID
        :return: 草稿章节列表（按创建时间降序）
        """
        return db.query(Chapter).filter(
            Chapter.user_id == user_id,
            Chapter.is_published == 0
        ).order_by(desc(Chapter.created_at)).all()

    @staticmethod
    def update(db: Session, chapter: Chapter, **kwargs):
        """更新章节字段
        :param db: 数据库会话
        :param chapter: 章节对象
        :param kwargs: 要更新的字段键值对
        """
        for key, value in kwargs.items():
            if hasattr(chapter, key):
                setattr(chapter, key, value)
        db.commit()

    @staticmethod
    def delete(db: Session, chapter_unique_id: str):
        """根据唯一ID删除单个章节
        :param db: 数据库会话
        :param chapter_unique_id: 章节唯一ID
        """
        chapter = db.query(Chapter).filter(Chapter.chapter_unique_id == chapter_unique_id).first()
        if chapter:
            db.delete(chapter)
            db.commit()

    @staticmethod
    def delete_by_novel_id(db: Session, novel_unique_id: str):
        """批量删除某作品下的所有章节
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        """
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
