from sqlalchemy import Column, Integer, String, DateTime, func, SmallInteger
from app.models.base import Base


class User(Base):
    """用户表，存储账户信息、VIP状态与免费生成配额"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username = Column(String(64), unique=True, nullable=False, comment="用户名")
    password = Column(String(256), nullable=False, comment="密码(bcrypt加密)")
    jwt_token = Column(String(512), nullable=True, comment="当前JWT Token")
    status = Column(SmallInteger, default=1, comment="状态: 0=禁用, 1=正常")
    email = Column(String(128), nullable=True, comment="邮箱")
    phone = Column(String(20), nullable=True, comment="手机号")
    is_super_admin = Column(SmallInteger, default=0, comment="弃用-保留兼容, 用 vip_level 替代")
    vip_level = Column(Integer, default=0, comment="会员等级: 0=免费用户, 1=VIP(10章/天), 2=SVIP(50章/天)")
    vip_expire_at = Column(DateTime, nullable=True, comment="会员到期时间，过期自动降级为免费用户")
    free_generate_quota = Column(Integer, default=6, comment="当日剩余AI生成次数，免费=6, VIP=10, SVIP=50")
    quota_date = Column(DateTime, nullable=True, comment="配额日期，跨天自动重置为对应等级的每日额度")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
