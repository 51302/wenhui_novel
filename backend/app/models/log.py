from sqlalchemy import Column, Integer, String, Text, DateTime, func
from app.models.base import Base


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(16), nullable=False, default="INFO", comment="日志级别: INFO/WARNING/ERROR")
    source = Column(String(32), nullable=False, default="system", comment="来源: api/user/system")
    message = Column(Text, nullable=False, comment="日志内容")
    path = Column(String(256), nullable=True, comment="请求路径")
    method = Column(String(16), nullable=True, comment="请求方法")
    status_code = Column(Integer, nullable=True, comment="HTTP 状态码")
    user_id = Column(Integer, nullable=True, comment="用户ID")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
