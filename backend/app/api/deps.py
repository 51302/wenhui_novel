"""
认证依赖 — 优化版：Redis 缓存用户身份，减少数据库查询
"""
from fastapi import Depends, HTTPException, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.application.jwt_handler import verify_token
from app.models.base import get_db
from app.dao.user_dao import UserDAO, DAILY_QUOTA_MAP
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
            vip_level = user.vip_level if user else 0
            is_vip = vip_level >= 1 and (
                user and user.vip_expire_at and user.vip_expire_at > datetime.now()
            )
        finally:
            db.close()

        result = {
            "user_id": user_id,
            "username": username,
            "vip_level": vip_level,
            "is_vip": is_vip,
            "is_svip": vip_level >= 2,
            "free_generate_quota": user.free_generate_quota if user else 0,
            "vip_expire_at": user.vip_expire_at.strftime("%Y-%m-%d %H:%M:%S") if user and user.vip_expire_at else None,
        }

        # 写入 Redis 缓存
        if r:
            r.set(cache_key, result, ttl=_USER_CACHE_TTL)

        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def get_optional_current_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    novel_token: Optional[str] = Cookie(None)
) -> Optional[dict]:
    """获取当前登录用户身份（可选版），未登录返回 None 而不是 401
    :param request: FastAPI请求对象
    :param credentials: HTTP Bearer令牌凭据
    :param novel_token: Cookie中的令牌
    :return: 用户身份字典或None
    """
    try:
        return get_current_user(request, credentials, novel_token)
    except HTTPException:
        return None


def invalidate_user_cache(user_id: int):
    """当用户 VIP 状态变更时，清除缓存"""
    r = _redis()
    if r:
        r.delete(f"{_USER_CACHE_PREFIX}{user_id}")


def require_vip(current_user: dict = Depends(get_current_user)):
    """要求当前用户必须是VIP或SVIP，否则返回403
    :param current_user: 当前登录用户信息
    :return: 当前用户信息
    :raises HTTPException: 免费用户抛出403
    """
    if current_user.get("vip_level", 0) < 1:
        raise HTTPException(status_code=403, detail="仅 VIP/SVIP 用户可操作")
    return current_user


def check_creation_access(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创作权限检查：检查各等级每日配额是否用完（不扣减，仅检查）
    VIP=10章/天, SVIP=50章/天, 免费=6章/天
    """
    user = UserDAO.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # 检查会员过期
    UserDAO.check_and_downgrade_expired(db, current_user["user_id"])
    # 跨天重置配额
    UserDAO._reset_daily_quota(user)
    db.commit()
    # 获取当前等级并更新 current_user
    vip_level = user.vip_level
    current_user["vip_level"] = vip_level
    current_user["is_vip"] = vip_level >= 1
    current_user["is_svip"] = vip_level >= 2
    quota = user.free_generate_quota
    if quota <= 0:
        max_quota = DAILY_QUOTA_MAP.get(vip_level, 6)
        level_name = "SVIP" if vip_level >= 2 else ("VIP" if vip_level >= 1 else "免费")
        raise HTTPException(status_code=403, detail=f"今日{level_name}发布次数已用完({max_quota}次)，请明天再试")
    current_user["free_generate_quota"] = quota
    return current_user


def check_generate_permission(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """发布权限检查：检查各等级每日发布配额并扣减1次
    VIP=10章/天, SVIP=50章/天, 免费=6章/天
    """
    user = UserDAO.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # 检查会员过期
    UserDAO.check_and_downgrade_expired(db, current_user["user_id"])
    # 扣减配额（内部会自动跨天重置）
    remaining = UserDAO.decrement_generate_quota(db, current_user["user_id"])
    if remaining < 0:
        vip_level = user.vip_level
        max_quota = DAILY_QUOTA_MAP.get(vip_level, 6)
        level_name = "SVIP" if vip_level >= 2 else ("VIP" if vip_level >= 1 else "免费")
        raise HTTPException(status_code=403, detail=f"今日{level_name}发布次数已用完({max_quota}次)，请明天再试")
    # 更新 current_user 中的信息
    current_user["free_generate_quota"] = remaining
    current_user["vip_level"] = user.vip_level
    current_user["is_vip"] = user.vip_level >= 1
    current_user["is_svip"] = user.vip_level >= 2
    current_user["generated_as_guest"] = True
    return current_user
