from fastapi import Depends, HTTPException, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.application.jwt_handler import verify_token
from app.models.base import get_db
from app.dao.user_dao import UserDAO
from typing import Optional
from datetime import datetime

security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    novel_token: Optional[str] = Cookie(None)
):
    token = None
    # 优先从 Authorization header 取，其次从 cookie
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

        # 从数据库读取真实的 VIP 状态
        db = next(get_db())
        try:
            UserDAO.check_and_downgrade_expired(db, user_id)
            user = UserDAO.get_by_id(db, user_id)
            is_super_admin = user.is_super_admin if user else 0
            # VIP 用户 = 超管 或 有效期内 VIP
            is_vip = is_super_admin == 1 or (
                user and user.vip_expire_at and user.vip_expire_at > datetime.now()
            )
        finally:
            db.close()

        return {
            "user_id": user_id,
            "username": username,
            "is_super_admin": is_super_admin,
            "is_vip": is_vip,
        }
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def require_vip(current_user: dict = Depends(get_current_user)):
    """
    仅 VIP 用户或超管可访问，否则返回 403。
    用法: def some_api(..., _vip=Depends(require_vip)):
    """
    if not current_user.get("is_vip"):
        raise HTTPException(status_code=403, detail="仅 VIP 用户可操作")
    return current_user
