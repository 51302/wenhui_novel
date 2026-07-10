from sqlalchemy import Column, Integer, String, DateTime, func
from app.models.base import Base


class Bookshelf(Base):
    __tablename__ = "bookshelf"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增ID")
    user_id = Column(Integer, nullable=False, comment="用户ID")
    novel_unique_id = Column(String(64), nullable=False, comment="作品唯一ID")
    created_at = Column(DateTime, default=func.now(), comment="加入时间")
