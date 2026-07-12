"""
认证依赖 — 优化版：Redis 缓存用户身份，减少数据库查询
"""
from fastapi import Depends, HTTPException, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.application.jwt_handler import verify_token
from app.models.base import get_db
from app.dao.user_dao import UserDAO
import app.utils.redis_cache as redis_mod
from app.utils.redis_cache import RedisCache
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.base import get_db

security = HTTPBearer(auto_error=False)

# 用户信息缓存 TTL：5分钟
_USER_CACHE_TTL = 300
_USER_CACHE_PREFIX = "user:cache:"


def _redis() -> Optional[RedisCache]:
    return redis_mod.redis_client


def get_current_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    novel_token: Optional[str] = Cookie(None)
):
    """从请求中获取当前登录用户身份，优先读取Redis缓存
    :param request: FastAPI请求对象
    :param credentials: HTTP Bearer令牌凭据
    :param novel_token: Cookie中的令牌
    :return: 用户身份字典
    :raises HTTPException: 认证失败时抛出401
    """
    token = None
    if credentials:
        token = credentials.credentials
    elif novel_token:
        token = novel_token

    if not token:
        raise HTTPException(status_code=401, detail="未提供认证凭证")

    try:
        payload = verify_token(token)
        user_id = payload["user_id"]
        username = payload["username"]

        # 优先从 Redis 读取用户缓存
        r = _redis()
        cache_key = f"{_USER_CACHE_PREFIX}{user_id}"
        if r:
            cached = r.get(cache_key)
            if cached:
                return cached

        # 缓存未命中，查询数据库
        db = next(get_db())
        try:
            UserDAO.check_and_downgrade_expired(db, user_id)
            user = UserDAO.get_by_id(db, user_id)
            is_super_admin = user.is_super_admin if user else 0
            is_vip = is_super_admin == 1 or (
                user and user.vip_expire_at and user.vip_expire_at > datetime.now()
            )
        finally:
            db.close()

        result = {
            "user_id": user_id,
            "username": username,
            "is_super_admin": is_super_admin,
            "is_vip": is_vip,
            "free_generate_quota": user.free_generate_quota if user else 0,
        }

        # 写入 Redis 缓存
        if r:
            r.set(cache_key, result, ttl=_USER_CACHE_TTL)

        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def invalidate_user_cache(user_id: int):
    """当用户 VIP 状态变更时，清除缓存"""
    r = _redis()
    if r:
        r.delete(f"{_USER_CACHE_PREFIX}{user_id}")


def require_vip(current_user: dict = Depends(get_current_user)):
    """要求当前用户必须是VIP，否则返回403禁止访问
    :param current_user: 当前登录用户信息
    :return: 当前用户信息
    :raises HTTPException: 非VIP用户抛出403
    """
    if not current_user.get("is_vip"):
        raise HTTPException(status_code=403, detail="仅 VIP 用户可操作")
    return current_user


def check_creation_access(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创作权限检查：VIP直接通过，非VIP检查是否有剩余免费次数(不扣减)"""
    if current_user.get("is_vip"):
        return current_user
    user = UserDAO.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.free_generate_quota > 0:
        current_user["free_generate_quota"] = user.free_generate_quota
        return current_user
    raise HTTPException(status_code=403, detail="免费次数已用完，请开通VIP继续使用")


def check_generate_permission(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """AI生成权限检查：VIP直接通过，非VIP检查免费次数并扣减"""
    if current_user.get("is_vip"):
        return current_user
    user = UserDAO.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.free_generate_quota > 0:
        remaining = UserDAO.decrement_generate_quota(db, current_user["user_id"])
        # 更新 current_user 中的 quota 信息
        current_user["free_generate_quota"] = remaining
        current_user["generated_as_guest"] = True
        return current_user
    raise HTTPException(status_code=403, detail="免费次数已用完，请开通VIP继续使用")
