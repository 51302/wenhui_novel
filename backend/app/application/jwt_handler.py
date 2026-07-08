import jwt
from datetime import datetime, timedelta
from app.config import jwt_secret, jwt_algorithm, jwt_expire_minutes


def create_token(user_id: int, username: str, is_super_admin: int = 0) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "is_super_admin": is_super_admin,
        "exp": datetime.utcnow() + timedelta(minutes=jwt_expire_minutes()),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, jwt_secret(), algorithm=jwt_algorithm())


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[jwt_algorithm()])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token已过期")
    except jwt.InvalidTokenError:
        raise ValueError("无效的Token")
