from sqlalchemy import Column, Integer, String, DateTime, func, SmallInteger
from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username = Column(String(64), unique=True, nullable=False, comment="用户名")
    password = Column(String(256), nullable=False, comment="密码(bcrypt加密)")
    jwt_token = Column(String(512), nullable=True, comment="当前JWT Token")
    status = Column(SmallInteger, default=1, comment="状态: 0=禁用, 1=正常")
    email = Column(String(128), nullable=True, comment="邮箱")
    phone = Column(String(20), nullable=True, comment="手机号")
    is_super_admin = Column(SmallInteger, default=0, comment="VIP会员: 0=普通用户, 1=VIP会员")
    vip_expire_at = Column(DateTime, nullable=True, comment="VIP到期时间，过期自动降级")
    free_generate_quota = Column(Integer, default=10, comment="免费AI生成剩余次数，新用户默认10次")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
