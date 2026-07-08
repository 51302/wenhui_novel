from sqlalchemy import Column, Integer, String, DateTime, Text, func
from app.models.base import Base


class Novel(Base):
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="作品自增ID")
    novel_unique_id = Column(String(64), unique=True, nullable=False, comment="作品唯一ID")
    author_user_id = Column(Integer, nullable=False, comment="作者用户ID")
    author_name = Column(String(64), nullable=False, comment="作者用户名/作者别名")
    title = Column(String(256), nullable=False, comment="书名/作品名称")
    target_reader = Column(String(16), nullable=False, comment="男频/女频")
    genre = Column(String(64), nullable=True, comment="题材/标签")
    description = Column(Text, comment="作品简介")
    story_background = Column(Text, comment="故事背景")
    world_setting = Column(Text, comment="世界观设定")
    realm_setting = Column(Text, comment="境界设定(JSON)")
    characters = Column(Text, comment="角色设定(JSON)")
    cover_image = Column(String(512), nullable=True, comment="封面图片")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    created_by = Column(String(64), nullable=True, comment="创建人")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
