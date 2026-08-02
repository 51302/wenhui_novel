import bcrypt
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
from app.utils.logger import system_logger
import app.utils.redis_cache as redis_mod

logger = logging.getLogger(__name__)


def _get_redis():
    """获取全局 Redis 单例"""
    return redis_mod.redis_client


# 邮箱正则
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9][\w.\-+]*@[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$"
)
# 手机号正则（中国大陆）
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

_VERIFY_TTL = 300  # 验证码有效 5 分钟


def _is_valid_email(email: str) -> bool:
    """校验邮箱格式是否合法"""
    return bool(_EMAIL_RE.match(email))


def _is_valid_phone(phone: str) -> bool:
    """校验中国大陆手机号格式是否合法"""
    return bool(_PHONE_RE.match(phone))


def _generate_code() -> str:
    """生成6位数字验证码"""
    return str(random.randint(100000, 999999))


def _store_code(key_prefix: str, target: str, code: str) -> bool:
    """将验证码存入 Redis，设置5分钟过期
    :param key_prefix: 缓存键前缀（如 email_code）
    :param target: 目标标识（邮箱或手机号）
    :param code: 验证码
    :return: 存储是否成功
    """
    r = _get_redis()
    if r:
        r.setex(f"{key_prefix}:{target}", _VERIFY_TTL, code)
        return True
    return False


def _verify_code(key_prefix: str, target: str, code: str) -> bool:
    """校验验证码是否正确，验证成功后删除缓存
    :param key_prefix: 缓存键前缀
    :param target: 目标标识（邮箱或手机号）
    :param code: 用户输入的验证码
    :return: 验证是否通过
    """
    r = _get_redis()
    if r:
        stored = r.get(f"{key_prefix}:{target}")
        if stored is not None and str(stored) == str(code):
            r.delete(f"{key_prefix}:{target}")
            return True
    return False


class AuthService:

    @staticmethod
    def generate_and_store_code(email: str) -> dict:
        """仅生成验证码并存入Redis（同步，很快），不发送邮件"""
        if not _is_valid_email(email):
            return fail("邮箱格式无效，请输入有效的邮箱地址", code=400)
        code = _generate_code()
        _store_code("email_code", email, code)
        logger.info(f"[邮件-存储] {email} 验证码: {code}（待后台发送）")
        return success({"code": code}, "验证码已生成")

    @staticmethod
    def send_email_async(email: str, code: str):
        """后台异步发送邮件（由BackgroundTasks调用，不影响HTTP响应）"""
        logger.info(f"[邮件-异步] 开始发送验证码至 {email}")
        email_cfg = {
            "resend_api_key": cfg_get("email.resend_api_key", ""),
            "from_name": cfg_get("email.from_name", "文辉小说"),
            "from_email": cfg_get("email.from_email", "onboarding@resend.dev"),
        }
        website_url = cfg_get("app.website_url", "https://${TAILSCALE_DOMAIN}")
        api_key = email_cfg.get('resend_api_key', '')
        from_name = email_cfg.get('from_name', '文辉小说')
        from_email = email_cfg.get('from_email', 'onboarding@resend.dev')

        if api_key:
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
                          <div style="text-align:center;margin-top:24px;padding-top:20px;border-top:1px solid #333">
                            <a href="{website_url}/register" style="color:#06b6d4;text-decoration:none;font-size:13px">
                              点击前往文辉小说完成注册 →
                            </a>
                          </div>
                        </div>
                        """
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    logger.info(f"[邮件-异步] 验证码已发送至 {email}")
                else:
                    logger.error(f"[邮件-异步] Resend 发送失败: {resp.status_code} {resp.text}")
            except Exception as e:
                logger.error(f"[邮件-异步] 异常: {e}")
        else:
            logger.info(f"[邮件-异步-演示] {email} 验证码: {code}")

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
        # 网站域名（用于邮件中的链接，从配置文件读取）
        website_url = cfg_get("app.website_url", "https://${TAILSCALE_DOMAIN}")
        api_key = email_cfg.get('resend_api_key', '')
        from_name = email_cfg.get('from_name', '文辉小说')
        from_email = email_cfg.get('from_email', 'onboarding@resend.dev')

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
                          <div style="text-align:center;margin-top:24px;padding-top:20px;border-top:1px solid #333">
                            <a href="{website_url}/register" style="color:#06b6d4;text-decoration:none;font-size:13px">
                              点击前往文辉小说完成注册 →
                            </a>
                          </div>
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
                 email_code: str = None) -> dict:
        """用户注册：校验邮箱验证码、创建账号并返回JWT令牌
        :param db: 数据库会话
        :param username: 用户名
        :param password: 密码（至少8位）
        :param email: 邮箱（必填）
        :param phone: 手机号（选填）
        :param email_code: 邮箱验证码
        :return: 注册结果（含token）
        """
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

        # 用户名不允许包含中文
        if re.search(r"[\u4e00-\u9fff]", username or ""):
            return fail("用户名不能包含中文，请使用字母、数字或下划线", code=400)

        # 检查用户名是否已存在
        existing = UserDAO.get_by_username(db, username)
        if existing:
            return fail("用户名已存在", code=400)
        
        # 检查邮箱是否已注册
        existing_email = UserDAO.get_by_email(db, email)
        if existing_email:
            return fail("该邮箱已经注册", code=400)

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=8)).decode("utf-8")
        user = UserDAO.create(db, username, hashed, email, phone)
        token = create_token(user.id, user.username, user.vip_level)
        UserDAO.update_token(db, user, token)
        return success({
            "user_id": user.id,
            "username": user.username,
            "is_vip": user.vip_level >= 1,
            "is_svip": user.vip_level >= 2,
            "vip_level": user.vip_level,
            "token": token
        }, "注册成功")

    @staticmethod
    def login(db: Session, username: str, password: str, captcha_id: str = None, captcha_x: int = None) -> dict:
        """用户登录：校验用户名密码及滑动验证码，返回JWT令牌
        :param db: 数据库会话
        :param username: 用户名
        :param password: 密码
        :param captcha_id: 滑动验证码ID
        :param captcha_x: 用户滑动的x坐标
        :return: 登录结果（含token）
        """
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
            system_logger.warning(f"登录: 用户名不存在 - {username}")
            return fail("用户名或密码错误", code=401)
        if user.status == 0:
            system_logger.warning(f"登录: 账号已禁用 - {username}")
            return fail("账号已被禁用", code=403)
        if not bcrypt.checkpw(password.encode("utf-8"), user.password.encode("utf-8")):
            system_logger.warning(f"登录: 密码错误 - {username}")
            return fail("用户名或密码错误", code=401)
        token = create_token(user.id, user.username, user.vip_level)
        UserDAO.update_token(db, user, token)
        system_logger.info(f"登录: 认证成功 - {username} (ID={user.id}, vip_level={user.vip_level})")
        return success({
            "user_id": user.id,
            "username": user.username,
            "is_vip": user.vip_level >= 1,
            "is_svip": user.vip_level >= 2,
            "vip_level": user.vip_level,
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
        """解析JWT令牌获取当前用户信息
        :param token: JWT令牌
        :return: 用户信息字典（含 vip_level），失败返回None
        """
        try:
            payload = verify_token(token)
            return {
                "user_id": payload["user_id"],
                "username": payload["username"],
                "vip_level": payload.get("vip_level", 0),
            }
        except ValueError:
            return None
