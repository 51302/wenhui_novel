from sqlalchemy import Column, Integer, String, DateTime, Text, func, SmallInteger, Index
from app.models.base import Base


class Chapter(Base):
    """章节表，存储章节正文内容"""
    __tablename__ = "chapters"

    __table_args__ = (
        Index("idx_ch_novel_id", "novel_unique_id"),
        Index("idx_ch_novel_published", "novel_unique_id", "is_published", "created_at"),
        Index("idx_ch_user_published", "user_id", "is_published", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="章节自增ID")
    novel_unique_id = Column(String(64), nullable=False, comment="作品唯一ID")
    user_id = Column(Integer, nullable=False, comment="用户ID")
    chapter_unique_id = Column(String(64), unique=True, nullable=False, comment="章节唯一ID")
    chapter_name = Column(String(256), nullable=False, comment="章节名称")
    chapter_number = Column(Integer, default=0, comment="章节序号(如1,2,3...)")
    chapter_summary = Column(Text, nullable=True, comment="本章概要")
    word_count = Column(Integer, default=0, comment="本章字数")
    is_published = Column(SmallInteger, default=0, comment="是否发布: 0=草稿, 1=已发布")
    created_by = Column(String(64), nullable=True, comment="创建人")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
