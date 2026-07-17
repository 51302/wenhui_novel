from sqlalchemy import Column, Integer, String, DateTime, Text, func, SmallInteger
from app.models.base import Base


class Chapter(Base):
    """章节表，存储章节正文内容与节点/人物/事件等AI提取的元数据"""
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="章节自增ID")
    novel_unique_id = Column(String(64), nullable=False, comment="作品唯一ID")
    user_id = Column(Integer, nullable=False, comment="用户ID")
    chapter_unique_id = Column(String(64), unique=True, nullable=False, comment="章节唯一ID")
    chapter_name = Column(String(256), nullable=False, comment="章节名称")
    characters_involved = Column(Text, comment="涉及人物(JSON)")
    organizations = Column(Text, comment="涉及组织(JSON)")
    locations = Column(Text, comment="涉及地点(JSON)")
    skills = Column(Text, comment="涉及技能(JSON)")
    events = Column(Text, nullable=True, comment="关键事件")
    time_info = Column(String(256), nullable=True, comment="时间信息")
    key_items = Column(Text, nullable=True, comment="关键物品")
    power_changes = Column(Text, nullable=True, comment="实力变化")
    foreshadowing = Column(Text, nullable=True, comment="伏笔/悬念")
    word_count = Column(Integer, default=0, comment="章节字数")
    chapter_summary = Column(Text, nullable=True, comment="本章概要")
    is_published = Column(SmallInteger, default=0, comment="是否发布: 0=草稿, 1=已发布")
    content = Column(Text, nullable=True, comment="章节正文内容")
    created_by = Column(String(64), nullable=True, comment="创建人")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
