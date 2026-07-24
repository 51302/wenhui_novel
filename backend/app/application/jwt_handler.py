import jwt
from datetime import datetime, timedelta
from app.config import jwt_secret, jwt_algorithm, jwt_expire_minutes


def create_token(user_id: int, username: str, vip_level: int = 0) -> str:
    """
    生成JWT访问令牌，包含用户ID、用户名、VIP等级等
    :param user_id: 用户ID
    :param username: 用户名
    :param vip_level: 会员等级: 0=免费, 1=VIP(10章/天), 2=SVIP(50章/天)
    :return: JWT Token 字符串
    """
    payload = {
        "exp": datetime.utcnow() + timedelta(minutes=jwt_expire_minutes()),
        "iat": datetime.utcnow(),
        "user_id": user_id,
        "username": username,
        "vip_level": vip_level,
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
