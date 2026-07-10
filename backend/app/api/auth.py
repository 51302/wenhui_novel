from fastapi import APIRouter, Depends, Response, Body
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
    is_super_admin: int = 0

    @field_validator("password")
    @classmethod
    def password_length(cls, v):
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
    result = AuthService.register(
        db, req.username, req.password,
        req.email, req.phone,
        req.email_code,
        req.is_super_admin
    )
    if result.get("状态码") == 200:
        _set_token_cookie(response, result["数据"]["token"])
    return result


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    result = AuthService.login(db, req.username, req.password, req.captcha_id, req.captcha_x)
    if result.get("状态码") == 200:
        _set_token_cookie(response, result["数据"]["token"])
    return result


@router.get("/captcha")
def get_captcha():
    """获取滑动验证码"""
    return AuthService.generate_captcha()


@router.post("/send-email-code")
def send_email_code(req: SendCodeRequest = Body(...)):
    """发送邮箱验证码"""
    return AuthService.send_email_code(req.target)


@router.post("/logout")
def logout(response: Response):
    """清除登录 cookie"""
    response.delete_cookie("novel_token", path="/")
    return success(None, "已退出登录")


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前登录用户信息（从 cookie 或 header）"""
    from app.dao.user_dao import UserDAO
    user = UserDAO.get_by_id(db, current_user["user_id"])
    vip_expire_at = None
    if user and user.vip_expire_at:
        vip_expire_at = user.vip_expire_at.strftime("%Y-%m-%d %H:%M:%S")
    return success({
        **current_user,
        "vip_expire_at": vip_expire_at,
    }, "已登录")


@router.get("/my-profile")
def my_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取「我的」页面聚合数据：收藏/关注/点赞列表 + 粉丝数"""
    from app.service.bookshelf_service import ProfileService
    return ProfileService.get_profile(db, current_user["user_id"])
