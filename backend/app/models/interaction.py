from sqlalchemy import Column, Integer, String, DateTime, Text, func, SmallInteger
from app.models.base import Base


class WorkInteraction(Base):
    """作品互动表，记录用户对作品的点赞、关注、收藏与评论"""
    __tablename__ = "work_interactions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增ID")
    user_id = Column(Integer, nullable=False, comment="用户ID(被互动者)")
    novel_unique_id = Column(String(64), nullable=False, comment="作品唯一ID")
    comment_text = Column(Text, nullable=True, comment="评论内容")
    is_like = Column(SmallInteger, default=0, comment="是否点赞: 0=否, 1=是")
    is_follow = Column(SmallInteger, default=0, comment="是否关注: 0=否, 1=是")
    is_bookmark = Column(SmallInteger, default=0, comment="是否收藏: 0=否, 1=是")
    interactor_id = Column(Integer, nullable=False, comment="互动者ID")
    interactor_name = Column(String(64), nullable=True, comment="互动者用户名")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
