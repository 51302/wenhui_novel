"""
VIP 订单 DAO
"""
from sqlalchemy.orm import Session
from app.models.vip_order import VIPOrder


class VIPOrderDAO:

    @staticmethod
    def create(
        db: Session,
        user_id: int,
        username: str,
        out_trade_no: str,
        total_amount: str,
        plan_type: str = "vip_monthly",
        duration_days: int = 30,
        vip_level: int = 1,
    ) -> VIPOrder:
        """创建VIP/SVIP支付订单（状态为待支付）
        :param db: 数据库会话
        :param user_id: 用户ID
        :param username: 用户名
        :param out_trade_no: 商户唯一订单号
        :param total_amount: 支付金额
        :param plan_type: 套餐类型 vip_monthly/vip_quarterly/vip_yearly/svip_monthly/svip_quarterly/svip_yearly
        :param duration_days: 有效天数 30/90/365
        :param vip_level: 会员等级: 1=VIP, 2=SVIP
        :return: 新创建的订单对象
        """
        order = VIPOrder(
            user_id=user_id,
            username=username,
            out_trade_no=out_trade_no,
            total_amount=total_amount,
            plan_type=plan_type,
            duration_days=duration_days,
            vip_level=vip_level,
            status=0,  # 0=待支付
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_by_out_trade_no(db: Session, out_trade_no: str) -> VIPOrder:
        """根据商户订单号查询订单
        :param db: 数据库会话
        :param out_trade_no: 商户唯一订单号
        :return: 订单对象或None
        """
        return db.query(VIPOrder).filter(
            VIPOrder.out_trade_no == out_trade_no
        ).first()

    @staticmethod
    def mark_paid(
        db: Session,
        order: VIPOrder,
        trade_no: str,
        total_amount: str,
    ):
        """标记订单为已支付状态
        :param db: 数据库会话
        :param order: 订单对象
        :param trade_no: 支付宝交易号
        :param total_amount: 实际支付金额
        """
        order.status = 1  # 1=已支付
        order.trade_no = trade_no
        order.total_amount = total_amount
        db.commit()
