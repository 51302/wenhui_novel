from sqlalchemy.orm import Session
from app.models.novel import Novel
from typing import Optional, List
from sqlalchemy import desc, text


class NovelDAO:

    @staticmethod
    def create(db: Session, **kwargs) -> Novel:
        """创建一部新作品
        :param db: 数据库会话
        :param kwargs: 作品字段键值对
        :return: 新创建的作品对象
        """
        novel = Novel(**kwargs)
        db.add(novel)
        db.commit()
        db.refresh(novel)
        return novel

    @staticmethod
    def get_by_unique_id(db: Session, novel_unique_id: str) -> Optional[Novel]:
        """根据作品唯一ID查询作品
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :return: 作品对象或None
        """
        return db.query(Novel).filter(Novel.novel_unique_id == novel_unique_id).first()

    @staticmethod
    def get_by_id(db: Session, novel_id: int) -> Optional[Novel]:
        """根据自增主键ID查询作品
        :param db: 数据库会话
        :param novel_id: 作品自增ID
        :return: 作品对象或None
        """
        return db.query(Novel).filter(Novel.id == novel_id).first()

    @staticmethod
    def list_novels(db: Session, target_reader: str = None, genre: str = None,
                    page: int = 1, page_size: int = 12, fast_total: bool = True) -> tuple:
        """分页查询作品列表，支持按频道/题材筛选
        :param db: 数据库会话
        :param target_reader: 目标读者频道（男频/女频），可选
        :param genre: 题材标签，可选
        :param page: 页码
        :param page_size: 每页数量
        :param fast_total: 是否用information_schema快速估算总数
        :return: (作品列表, 总数)
        """
        query = db.query(Novel)
        if target_reader:
            query = query.filter(Novel.target_reader == target_reader)
        if genre:
            query = query.filter(Novel.genre == genre)
        # 优化: 用 information_schema 估算行数(毫秒级) 替代 COUNT(*)(全表扫描)
        if fast_total:
            total = db.execute(text("SELECT AUTO_INCREMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='novels'")).scalar() or 0
        else:
            total = query.count()
        novels = query.order_by(desc(Novel.created_at)).offset(
            (page - 1) * page_size).limit(page_size).all()
        return novels, int(total)

    @staticmethod
    def search_novels(db: Session, keyword: str, page: int = 1, page_size: int = 12) -> tuple:
        """按关键词搜索作品（匹配标题或作者名）
        :param db: 数据库会话
        :param keyword: 搜索关键词
        :param page: 页码
        :param page_size: 每页数量
        :return: (作品列表, 总数)
        """
        query = db.query(Novel).filter(
            (Novel.title.like(f"%{keyword}%")) | (Novel.author_name.like(f"%{keyword}%"))
        )
        total = query.count()
        novels = query.order_by(desc(Novel.created_at)).offset(
            (page - 1) * page_size).limit(page_size).all()
        return novels, total

    @staticmethod
    def get_by_user_id(db: Session, user_id: int) -> List[Novel]:
        """查询某作者的全部作品
        :param db: 数据库会话
        :param user_id: 作者用户ID
        :return: 作品列表（按创建时间降序）
        """
        return db.query(Novel).filter(Novel.author_user_id == user_id).order_by(desc(Novel.created_at)).all()

    @staticmethod
    def delete_by_unique_id(db: Session, novel_unique_id: str) -> bool:
        """根据唯一ID删除作品
        :param db: 数据库会话
        :param novel_unique_id: 作品唯一ID
        :return: 是否删除成功
        """
        novel = db.query(Novel).filter(Novel.novel_unique_id == novel_unique_id).first()
        if novel:
            db.delete(novel)
            db.commit()
            return True
        return False
