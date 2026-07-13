"""
VIP 会员 API  — 支持月度 / 季度 / 年度套餐
"""
import logging
from datetime import datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request, Response, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.service.alipay_service import (
    create_page_pay, verify_notify, generate_out_trade_no, query_order, VIP_PLANS,
)
from app.dao.user_dao import UserDAO
from app.dao.vip_order_dao import VIPOrderDAO
from app.api.deps import get_current_user, invalidate_user_cache
from app.utils.response import success, fail
from app.config import vip_default_plan

router = APIRouter(prefix="/api/vip", tags=["VIP会员"])
logger = logging.getLogger(__name__)


# ============ 请求模型 ============
class CreateOrderRequest(BaseModel):
    plan_type: str = None  # monthly / quarterly / yearly, 不填则用 config 默认值


@router.post("/create-order")
def create_order(
    req: CreateOrderRequest = Body(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建 VIP 支付订单，返回跳转支付宝收银台的链接
    请求体 JSON: {"plan_type": "monthly|quarterly|yearly"}
    """
    plan_type = req.plan_type or vip_default_plan()
    if plan_type not in VIP_PLANS:
        return fail(f"无效的套餐类型: {plan_type}", code=400)

    plan = VIP_PLANS[plan_type]
    vip_level = plan.get("vip_level", 1)  # 从套餐中取 vip_level
    user_id = current_user["user_id"]
    username = current_user["username"]

    user = UserDAO.get_by_id(db, user_id)
    # 已开通的同级或更高级会员不允许再购买；但低等级允许升级（VIP→SVIP）
    if user and user.vip_expire_at and user.vip_expire_at > datetime.utcnow():
        if user.vip_level >= vip_level:
            level_name = "SVIP" if user.vip_level >= 2 else "VIP"
            return fail(f"您已是 {level_name} 会员，到期时间 {user.vip_expire_at.strftime('%Y-%m-%d')}", code=400)

    out_trade_no = generate_out_trade_no(user_id)
    VIPOrderDAO.create(
        db, user_id, username, out_trade_no,
        total_amount=plan["price"],
        plan_type=plan_type,
        duration_days=plan["days"],
        vip_level=vip_level,
    )

    return success({
        "pay_url": f"/api/vip/pay/{out_trade_no}",
        "out_trade_no": out_trade_no,
        "plan_name": plan["name"],
        "amount": plan["price"],
    }, "订单创建成功")


@router.get("/pay/{out_trade_no}", response_class=HTMLResponse)
def pay_page(
    out_trade_no: str,
    db: Session = Depends(get_db),
):
    """
    跳转支付宝收银台（电脑网站支付）。
    浏览器访问 → 自动POST到支付宝 → 支付宝页面显示二维码 →
    用沙箱版支付宝App扫码支付 → 支付完成跳转回 return_url
    """
    order = VIPOrderDAO.get_by_out_trade_no(db, out_trade_no)
    if not order:
        return HTMLResponse("<h3>订单不存在</h3>", status_code=404)

    plan = VIP_PLANS.get(order.plan_type, VIP_PLANS.get("monthly", {}))
    html = create_page_pay(
        subject=f"文辉小说 VIP {plan.get('name', '会员')} - {plan.get('desc', '')}",
        out_trade_no=out_trade_no,
        total_amount=order.total_amount,
    )
    return HTMLResponse(html)


@router.post("/confirm/{out_trade_no}")
def confirm_payment(
    out_trade_no: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    支付宝支付完成后，前端调用此接口确认订单状态并开通 VIP
    """
    order = VIPOrderDAO.get_by_out_trade_no(db, out_trade_no)
    if not order:
        return fail("订单不存在", code=404)

    if order.status == 1:
        # 已经支付过了
        return success(None, "支付成功，VIP 已开通！")

    # 向支付宝查询
    result = query_order(out_trade_no)
    if result.get("success") and result.get("trade_status") in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        VIPOrderDAO.mark_paid(db, order, order.out_trade_no, order.total_amount)
        UserDAO.upgrade_to_vip(db, order.user_id, duration_days=order.duration_days, vip_level=order.vip_level)
        invalidate_user_cache(order.user_id)
        level_name = "SVIP" if order.vip_level >= 2 else "VIP"
        logger.info(f"用户 {order.user_id} ({order.username}) 支付确认成功, 开通 {order.plan_type} {level_name}")
        return success(None, f"支付成功，{level_name} 已开通！")
    else:
        logger.info(f"订单 {out_trade_no} 尚未支付: {result.get('trade_status', '')}")
        return fail("尚未收到支付，请确认已完成支付后再试", code=402)


@router.post("/notify")
async def alipay_notify(request: Request, db: Session = Depends(get_db)):
    """支付宝异步通知回调"""
    body = await request.body()
    params = {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}

    is_valid, out_trade_no, trade_no, total_amount, trade_status, _seller_id = verify_notify(params)
    if not is_valid:
        logger.error("支付宝异步通知验签失败")
        return Response(content="failure", media_type="text/plain")

    if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        order = VIPOrderDAO.get_by_out_trade_no(db, out_trade_no)
        if order:
            VIPOrderDAO.mark_paid(db, order, trade_no, total_amount)
            UserDAO.upgrade_to_vip(db, order.user_id, duration_days=order.duration_days, vip_level=order.vip_level)
            invalidate_user_cache(order.user_id)
            level_name = "SVIP" if order.vip_level >= 2 else "VIP"
            logger.info(f"用户 {order.user_id} ({order.username}) 开通 {order.plan_type} {level_name}, 订单: {out_trade_no}")
        else:
            logger.error(f"未找到订单: {out_trade_no}")

    return Response(content="success", media_type="text/plain")


@router.post("/demo-notify")
async def demo_notify(request: Request, db: Session = Depends(get_db)):
    """Demo 模式：模拟支付宝异步通知，直接升级 VIP"""
    body = await request.body()
    params = {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}

    out_trade_no = params.get("out_trade_no", "")
    trade_status = params.get("trade_status", "")

    if trade_status == "TRADE_SUCCESS":
        order = VIPOrderDAO.get_by_out_trade_no(db, out_trade_no)
        if order:
            VIPOrderDAO.mark_paid(db, order, params.get("trade_no", ""), params.get("total_amount", ""))
            UserDAO.upgrade_to_vip(db, order.user_id, duration_days=order.duration_days, vip_level=order.vip_level)
            invalidate_user_cache(order.user_id)
            level_name = "SVIP" if order.vip_level >= 2 else "VIP"
            logger.info(f"Demo 模式: 用户 {order.user_id} 开通 {order.plan_type} {level_name}")
        else:
            logger.error(f"Demo 通知未找到订单: {out_trade_no}")

    return {"code": "success"}


@router.get("/status")
def vip_status(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询当前用户 VIP 状态（含过期时间和套餐类型，直接查DB确保最新）"""
    from app.dao.user_dao import UserDAO
    from app.models.vip_order import VIPOrder
    user = UserDAO.get_by_id(db, current_user["user_id"])
    vip_expire_at = None
    plan_type = ""
    vip_level = 0
    if user:
        vip_level = user.vip_level
        if user.vip_expire_at:
            vip_expire_at = user.vip_expire_at.strftime("%Y-%m-%d %H:%M:%S")
            # 查最新已支付订单获取套餐类型
            order = db.query(VIPOrder).filter(
                VIPOrder.user_id == current_user["user_id"],
                VIPOrder.status == 1,
            ).order_by(VIPOrder.created_at.desc()).first()
            if order:
                plan_type = order.plan_type
    return success({
        "is_vip": vip_level >= 1,
        "is_svip": vip_level >= 2,
        "vip_level": vip_level,
        "vip_expire_at": vip_expire_at,
        "plan_type": plan_type,
        "username": current_user["username"],
    }, "查询成功")


@router.get("/plans")
def get_plans():
    """获取所有套餐信息"""
    return success(VIP_PLANS, "查询成功")


@router.get("/query/{out_trade_no}")
def query_payment(
    out_trade_no: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询订单支付状态"""
    order = VIPOrderDAO.get_by_out_trade_no(db, out_trade_no)
    if order:
        return success({
            "out_trade_no": order.out_trade_no,
            "status": "已支付" if order.status == 1 else "待支付",
            "plan_type": order.plan_type,
            "total_amount": order.total_amount,
        }, "查询成功")
    return success(None, "未找到订单")
