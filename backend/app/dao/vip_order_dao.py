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
        plan_type: str = "monthly",
        duration_days: int = 30,
    ) -> VIPOrder:
        order = VIPOrder(
            user_id=user_id,
            username=username,
            out_trade_no=out_trade_no,
            total_amount=total_amount,
            plan_type=plan_type,
            duration_days=duration_days,
            status=0,  # 0=待支付
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_by_out_trade_no(db: Session, out_trade_no: str) -> VIPOrder:
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
        order.status = 1  # 1=已支付
        order.trade_no = trade_no
        order.total_amount = total_amount
        db.commit()
