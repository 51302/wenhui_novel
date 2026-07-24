from fastapi import APIRouter, Depends, Response, Body, BackgroundTasks
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.auth_service import AuthService
from app.api.deps import get_current_user
from app.utils.response import success

router = APIRouter(prefix="/api/auth", tags=["认证"])


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str                                           # 必填
    phone: str = None                                    # 选填
    email_code: str                                      # 邮箱验证码（必填）

    @field_validator("password")
    @classmethod
    def password_length(cls, v):
        """校验密码长度不少于8位"""
        if len(v) < 8:
            raise ValueError("密码必须超过8位数")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str
    captcha_id: str = None
    captcha_x: int = None


class SendCodeRequest(BaseModel):
    target: str  # 邮箱或手机号


def _set_token_cookie(response: Response, token: str):
    """设置 httpOnly cookie，30天过期"""
    response.set_cookie(
        key="novel_token",
        value=token,
        max_age=30 * 24 * 3600,  # 30天
        httponly=True,
        samesite="lax",
        path="/"
    )


@router.post("/register")
def register(req: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    """
    用户注册：邮箱 + 验证码 + 用户名 + 密码
    注册成功后自动登录，设置 HttpOnly cookie
    """
    from app.utils.logger import system_logger
    result = AuthService.register(
        db, req.username, req.password,
        req.email, req.phone,
        req.email_code
    )
    if result.get("状态码") == 200:
        system_logger.info(f"用户注册成功: {req.username} (邮箱={req.email})")
        _set_token_cookie(response, result["数据"]["token"])
    else:
        system_logger.warning(f"用户注册失败: {req.username} → {result.get('消息', '')}")
    return result


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    result = AuthService.login(db, req.username, req.password, req.captcha_id, req.captcha_x)
    from app.utils.logger import system_logger
    if result.get("状态码") == 200:
        system_logger.info(f"用户登录成功: {req.username}")
        _set_token_cookie(response, result["数据"]["token"])
    else:
        system_logger.warning(f"用户登录失败: {req.username} → {result.get('消息', '')}")
    return result


@router.get("/captcha")
def get_captcha():
    """获取滑动验证码"""
    return AuthService.generate_captcha()


@router.post("/send-email-code")
def send_email_code(req: SendCodeRequest = Body(...), background_tasks: BackgroundTasks = None):
    """发送邮箱验证码（后台异步发送，立即返回）"""
    from app.utils.logger import system_logger

    # 先生成验证码并存入Redis（同步，很快）
    result = AuthService.generate_and_store_code(req.target)
    if result.get("状态码") != 200:
        return result

    # 后台异步发送邮件
    if background_tasks:
        code = result.get("数据", {}).get("code", "")
        background_tasks.add_task(AuthService.send_email_async, req.target, code)
        system_logger.info(f"[邮件] 已加入后台任务: {req.target}")
    else:
        # 无BackgroundTasks时走同步
        return AuthService.send_email_code(req.target)

    return success(None, "验证码已发送至您的邮箱，请查收")


@router.post("/logout")
def logout(response: Response):
    """清除登录 cookie"""
    response.delete_cookie("novel_token", path="/")
    return success(None, "已退出登录")


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息（从缓存读取，无需查DB）"""
    return success(current_user, "已登录")


@router.get("/my-profile")
def my_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取「我的」页面聚合数据：收藏/关注/点赞列表 + 粉丝数"""
    from app.service.bookshelf_service import ProfileService
    return ProfileService.get_profile(db, current_user["user_id"])
