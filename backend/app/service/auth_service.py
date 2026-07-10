import bcrypt
import redis
import os
import re
import random
import logging
import requests
from sqlalchemy.orm import Session
from app.dao.user_dao import UserDAO
from app.application.jwt_handler import create_token, verify_token
from app.utils.response import success, fail
from app.config import get as cfg_get

logger = logging.getLogger(__name__)


def _get_redis():
    """获取 Redis 连接"""
    try:
        cfg_password = cfg_get("redis.password", "")
        r = redis.Redis(
            host=os.environ.get('REDIS_HOST', cfg_get("redis.host", "localhost")),
            port=int(os.environ.get('REDIS_PORT', cfg_get("redis.port", 6379))),
            password=os.environ.get('REDIS_PASSWORD', cfg_password),
            db=cfg_get("redis.db", 0), decode_responses=True,
            socket_connect_timeout=3
        )
        r.ping()
        return r
    except Exception:
        return None


# 邮箱正则
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9][\w.\-+]*@[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$"
)
# 手机号正则（中国大陆）
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

_VERIFY_TTL = 300  # 验证码有效 5 分钟


def _is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def _is_valid_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match(phone))


def _generate_code() -> str:
    return str(random.randint(100000, 999999))


def _store_code(key_prefix: str, target: str, code: str) -> bool:
    r = _get_redis()
    if r:
        r.setex(f"{key_prefix}:{target}", _VERIFY_TTL, code)
        return True
    return False


def _verify_code(key_prefix: str, target: str, code: str) -> bool:
    r = _get_redis()
    if r:
        stored = r.get(f"{key_prefix}:{target}")
        if stored and stored == code:
            r.delete(f"{key_prefix}:{target}")
            return True
    return False


class AuthService:

    @staticmethod
    def send_email_code(email: str) -> dict:
        """发送邮箱验证码（通过 Resend API）"""
        if not _is_valid_email(email):
            return fail("邮箱格式无效，请输入有效的邮箱地址", code=400)
        code = _generate_code()
        _store_code("email_code", email, code)

        email_cfg = {
            "resend_api_key": cfg_get("email.resend_api_key", ""),
            "from_name": cfg_get("email.from_name", "文辉小说"),
            "from_email": cfg_get("email.from_email", "onboarding@resend.dev"),
        }
        api_key = email_cfg.get('resend_api_key', '')
        from_name = email_cfg.get('from_name', '文辉小说')
        from_email = email_cfg.get('from_email', 'noreply@wenhuixs.com')

        if api_key:
            # 通过 Resend 发真实邮件
            try:
                resp = requests.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "from": f"{from_name} <{from_email}>",
                        "to": [email],
                        "subject": "文辉小说 - 邮箱验证码",
                        "html": f"""
                        <div style="max-width:480px;margin:0 auto;font-family:Arial,sans-serif;
                                    background:#1a1a2e;color:#e0e0e0;padding:32px;border-radius:12px">
                          <h2 style="color:#06b6d4;text-align:center">文辉小说 ✦ 邮箱验证</h2>
                          <p>您正在进行账号注册验证，验证码如下：</p>
                          <div style="background:#0f0f28;text-align:center;padding:20px;border-radius:8px;
                                      margin:16px 0;font-size:32px;letter-spacing:8px;color:#06b6d4;font-weight:700">
                            {code}
                          </div>
                          <p style="color:#8892b0;font-size:13px">验证码 5 分钟内有效，请勿透露给他人。</p>
                        </div>
                        """
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    logger.info(f"[邮件] 验证码已发送至 {email}")
                    return success(None, "验证码已发送至您的邮箱，请查收")
                else:
                    logger.error(f"[邮件] Resend 发送失败: {resp.status_code} {resp.text}")
                    # Resend 发送失败时，仍然返回验证码到日志（演示模式降级）
                    logger.info(f"[邮件-降级] {email} 验证码: {code}")
                    return success(None, "验证码已发送至您的邮箱，请查收")
            except Exception as e:
                logger.error(f"[邮件] 异常: {e}")
                logger.info(f"[邮件-降级] {email} 验证码: {code}")
                return success(None, "验证码已发送至您的邮箱，请查收")
        else:
            # 未配置 API Key，演示模式
            logger.info(f"[邮件-演示] {email} 验证码: {code}")
            return success(None, "验证码已发送至您的邮箱，请查收")

    @staticmethod
    def register(db: Session, username: str, password: str,
                 email: str = None, phone: str = None,
                 email_code: str = None,
                 is_super_admin: int = 0) -> dict:
        # 邮箱必填
        if not email:
            return fail("邮箱为必填项", code=400)
        if not _is_valid_email(email):
            return fail("邮箱格式无效，请输入有效的邮箱地址", code=400)

        # 手机号选填：填了才校验格式
        if phone and not _is_valid_phone(phone):
            return fail("手机号格式无效，请输入有效的11位手机号", code=400)

        # 验证邮箱验证码
        if not email_code:
            return fail("请输入邮箱验证码", code=400)
        if not _verify_code("email_code", email, email_code):
            return fail("邮箱验证码错误或已过期，请重新获取", code=400)

        if len(password) < 8:
            return fail("密码必须超过8位数", code=400)
        
        # 检查用户名是否已存在
        existing = UserDAO.get_by_username(db, username)
        if existing:
            return fail("用户名已存在", code=400)
        
        # 检查邮箱是否已注册
        existing_email = UserDAO.get_by_email(db, email)
        if existing_email:
            return fail("该邮箱已经注册", code=400)

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=8)).decode("utf-8")
        user = UserDAO.create(db, username, hashed, email, phone, is_super_admin)
        token = create_token(user.id, user.username, user.is_super_admin)
        UserDAO.update_token(db, user, token)
        return success({
            "user_id": user.id,
            "username": user.username,
            "is_super_admin": user.is_super_admin,
            "is_vip": user.is_super_admin == 1,
            "token": token
        }, "注册成功")

    @staticmethod
    def login(db: Session, username: str, password: str, captcha_id: str = None, captcha_x: int = None) -> dict:
        # 验证滑动验证码
        if captcha_id and captcha_x is not None:
            r = _get_redis()
            if r:
                key = f"captcha:{captcha_id}"
                stored_x = r.get(key)
                if stored_x is None:
                    return fail("验证码已过期，请刷新重试", code=400)
                stored_x = int(stored_x)
                r.delete(key)
                if abs(captcha_x - stored_x) > 10:
                    return fail("验证失败，请重试", code=400)
            else:
                # Redis 不可用时，跳过验证码校验
                pass

        user = UserDAO.get_by_username(db, username)
        if not user:
            return fail("用户名或密码错误", code=401)
        if user.status == 0:
            return fail("账号已被禁用", code=403)
        if not bcrypt.checkpw(password.encode("utf-8"), user.password.encode("utf-8")):
            return fail("用户名或密码错误", code=401)
        token = create_token(user.id, user.username, user.is_super_admin)
        UserDAO.update_token(db, user, token)
        return success({
            "user_id": user.id,
            "username": user.username,
            "is_super_admin": user.is_super_admin,
            "is_vip": user.is_super_admin == 1,
            "token": token
        }, "登录成功")

    @staticmethod
    def generate_captcha() -> dict:
        """生成滑动验证码，返回 captcha_id 和正确答案的 x 坐标"""
        import random, uuid
        captcha_id = uuid.uuid4().hex[:16]
        target_x = random.randint(100, 300)
        r = _get_redis()
        if r:
            r.setex(f"captcha:{captcha_id}", 300, str(target_x))
        return success({
            "captcha_id": captcha_id,
            "target_x": target_x
        }, "验证码生成成功")

    @staticmethod
    def get_current_user(token: str) -> dict:
        try:
            payload = verify_token(token)
            return {
                "user_id": payload["user_id"],
                "username": payload["username"],
                "is_super_admin": payload.get("is_super_admin", 0)
            }
        except ValueError:
            return None
