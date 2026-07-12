import jwt
from datetime import datetime, timedelta
from app.config import jwt_secret, jwt_algorithm, jwt_expire_minutes


def create_token(user_id: int, username: str, is_super_admin: int = 0) -> str:
    """生成 JWT 访问令牌
    :param user_id: 用户 ID
    :param username: 用户名
    :param is_super_admin: 是否超级管理员，0=否 1=是
    :return: 编码后的 JWT 令牌字符串
    """
    payload = {
        "user_id": user_id,
        "username": username,
        "is_super_admin": is_super_admin,
        "exp": datetime.utcnow() + timedelta(minutes=jwt_expire_minutes()),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, jwt_secret(), algorithm=jwt_algorithm())


def verify_token(token: str) -> dict:
    """验证并解码 JWT 令牌
    :param token: JWT 令牌字符串
    :return: 解码后的 payload 字典
    :raises ValueError: Token 过期或无效时抛出
    """
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[jwt_algorithm()])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token已过期")
    except jwt.InvalidTokenError:
        raise ValueError("无效的Token")
