from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.user import User
from typing import Optional


class UserDAO:

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_username(db: Session, username: str) -> Optional[User]:
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[User]:
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def create(db: Session, username: str, hashed_password: str,
               email: str = None, phone: str = None, is_super_admin: int = 0) -> User:
        user = User(
            username=username,
            password=hashed_password,
            email=email,
            phone=phone,
            is_super_admin=is_super_admin,
            free_generate_quota=10
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def update_token(db: Session, user: User, token: str):
        user.jwt_token = token
        db.commit()

    @staticmethod
    def upgrade_to_vip(db: Session, user_id: int, duration_days: int = 30):
        """升级用户为 VIP，设置过期时间"""
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.is_super_admin = 1
            user.vip_expire_at = datetime.utcnow() + timedelta(days=duration_days)
            db.commit()

    @staticmethod
    def check_and_downgrade_expired(db: Session, user_id: int):
        """检查 VIP 是否过期，过期则自动降级为普通用户"""
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.is_super_admin == 1 and user.vip_expire_at:
            if datetime.utcnow() > user.vip_expire_at:
                user.is_super_admin = 0
                user.vip_expire_at = None
                db.commit()
                return True  # 已降级
        return False

    @staticmethod
    def decrement_generate_quota(db: Session, user_id: int) -> int:
        """扣减1次免费生成次数，返回剩余次数；-1表示失败"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return -1
        if user.free_generate_quota <= 0:
            return -1
        user.free_generate_quota -= 1
        db.commit()
        return user.free_generate_quota
