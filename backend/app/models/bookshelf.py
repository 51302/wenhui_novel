from sqlalchemy import Column, Integer, String, DateTime, func
from app.models.base import Base


class Bookshelf(Base):
    """书架表，记录用户加入书架的作品与阅读进度"""
    __tablename__ = "bookshelf"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增ID")
    user_id = Column(Integer, nullable=False, comment="用户ID")
    novel_unique_id = Column(String(64), nullable=False, comment="作品唯一ID")
    last_chapter_unique_id = Column(String(64), nullable=True, comment="最后阅读章节ID")
    last_chapter_name = Column(String(256), nullable=True, comment="最后阅读章节名称")
    created_at = Column(DateTime, default=func.now(), comment="加入时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
