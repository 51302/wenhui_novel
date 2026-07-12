"""
VIP 订单模型
"""
from sqlalchemy import Column, Integer, String, DateTime, func
from app.models.base import Base


class VIPOrder(Base):
    """VIP订单表，记录用户购买VIP套餐的支付订单信息与支付状态"""
    __tablename__ = "vip_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True, comment="用户ID")
    username = Column(String(64), nullable=False, comment="用户名")
    out_trade_no = Column(String(64), unique=True, nullable=False, index=True, comment="商户订单号")
    trade_no = Column(String(64), nullable=True, comment="支付宝交易号")
    total_amount = Column(String(16), nullable=False, comment="支付金额")
    plan_type = Column(String(16), default="vip_monthly", comment="套餐: vip_monthly/vip_quarterly/vip_yearly/svip_monthly/svip_quarterly/svip_yearly")
    vip_level = Column(Integer, default=1, comment="会员等级: 1=VIP, 2=SVIP")
    duration_days = Column(Integer, default=30, comment="有效天数: 30/90/365")
    status = Column(Integer, default=0, comment="0=待支付 1=已支付")
    created_at = Column(DateTime, server_default=func.now())
    paid_at = Column(DateTime, nullable=True)
