from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.user import User
from typing import Optional


# 各会员等级每日 AI 生成配额上限
DAILY_QUOTA_MAP = {
    0: 6,   # 免费用户: 6章/天（免费体验）
    1: 10,  # VIP: 10章/天
    2: 50,  # SVIP: 50章/天
}


class UserDAO:

    @staticmethod
    def _reset_daily_quota(user: User):
        """
        如果 quota_date 不是今天，则重置为对应等级的每日配额
        :param user: 用户对象（会直接修改属性，外部需要 commit）
        """
        today = datetime.utcnow().date()
        quota_today = user.quota_date.date() if user.quota_date else None
        if quota_today != today:
            user.quota_date = datetime.utcnow()
            user.free_generate_quota = DAILY_QUOTA_MAP.get(user.vip_level, 3)

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> Optional[User]:
        """根据用户ID查询用户
        :param db: 数据库会话
        :param user_id: 用户主键ID
        :return: 用户对象或None
        """
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_username(db: Session, username: str) -> Optional[User]:
        """根据用户名查询用户
        :param db: 数据库会话
        :param username: 用户名
        :return: 用户对象或None
        """
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[User]:
        """根据邮箱查询用户
        :param db: 数据库会话
        :param email: 邮箱地址
        :return: 用户对象或None
        """
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def create(db: Session, username: str, hashed_password: str,
               email: str = None, phone: str = None, is_super_admin: int = 0) -> User:
        """创建新用户
        :param db: 数据库会话
        :param username: 用户名
        :param hashed_password: bcrypt加密后的密码
        :param email: 邮箱（可选）
        :param phone: 手机号（可选）
        :param is_super_admin: 是否VIP会员，0=否
        :return: 新创建的用户对象
        """
        user = User(
            username=username,
            password=hashed_password,
            email=email,
            phone=phone,
            is_super_admin=is_super_admin,
            vip_level=0,
            free_generate_quota=6,
            quota_date=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def update_token(db: Session, user: User, token: str):
        """更新用户的JWT Token
        :param db: 数据库会话
        :param user: 用户对象
        :param token: 新的JWT Token
        """
        user.jwt_token = token
        db.commit()

    @staticmethod
    def upgrade_to_vip(db: Session, user_id: int, duration_days: int = 30, vip_level: int = 1):
        """升级用户为 VIP/SVIP，设置等级和过期时间
        :param db: 数据库会话
        :param user_id: 用户ID
        :param duration_days: 会员有效天数
        :param vip_level: 会员等级: 1=VIP(10章/天), 2=SVIP(50章/天)
        """
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.is_super_admin = 1  # 保留兼容
            user.vip_level = vip_level
            user.vip_expire_at = datetime.utcnow() + timedelta(days=duration_days)
            db.commit()

    @staticmethod
    def check_and_downgrade_expired(db: Session, user_id: int):
        """检查 VIP/SVIP 是否过期，过期则降级为免费用户(vip_level=0)，配额重置为免费额度
        :param db: 数据库会话
        :param user_id: 用户ID
        :return: True=已降级, False=未过期
        """
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.vip_level > 0 and user.vip_expire_at:
            if datetime.utcnow() > user.vip_expire_at:
                user.is_super_admin = 0
                user.vip_level = 0
                user.vip_expire_at = None
                user.free_generate_quota = 3  # 降级后重置为免费配额
                db.commit()
                return True
        return False

    @staticmethod
    def decrement_generate_quota(db: Session, user_id: int) -> int:
        """
        扣减1次 AI 生成次数（含每日自动重置）
        免费=3次/天, VIP=10次/天, SVIP=50次/天
        :param db: 数据库会话
        :param user_id: 用户ID
        :return: 剩余次数；-1表示配额不足
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return -1
        # 跨天自动重置配额
        UserDAO._reset_daily_quota(user)
        if user.free_generate_quota <= 0:
            return -1
        user.free_generate_quota -= 1
        db.commit()
        return user.free_generate_quota

    @staticmethod
    def get_max_daily_quota(vip_level: int) -> int:
        """获取对应会员等级的每日最大生成次数
        :param vip_level: 0=免费, 1=VIP, 2=SVIP
        :return: 每日最大生成次数
        """
        return DAILY_QUOTA_MAP.get(vip_level, 3)
