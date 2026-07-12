from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from typing import List, Optional, Tuple
from app.models.log import SystemLog


class LogDAO:

    @staticmethod
    def create(db: Session, **kwargs) -> SystemLog:
        log = SystemLog(**kwargs)
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    @staticmethod
    def query_logs(
        db: Session,
        level: Optional[str] = None,
        source: Optional[str] = None,
        keyword: Optional[str] = None,
        since_id: int = 0,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[SystemLog], int]:
        """分页查询日志，since_id>0 表示轮询增量"""
        q = db.query(SystemLog)
        if since_id > 0:
            q = q.filter(SystemLog.id > since_id)
        if level and level != "ALL":
            q = q.filter(SystemLog.level == level)
        if source:
            q = q.filter(SystemLog.source == source)
        if keyword:
            q = q.filter(SystemLog.message.contains(keyword))

        total = q.count()
        logs = q.order_by(desc(SystemLog.id)).offset((page - 1) * page_size).limit(page_size).all()
        return logs, total

    @staticmethod
    def get_max_id(db: Session) -> int:
        """获取最新日志ID（用于轮询）"""
        latest = db.query(SystemLog).order_by(desc(SystemLog.id)).first()
        return latest.id if latest else 0

    @staticmethod
    def delete_before_days(db: Session, days: int = 7) -> int:
        """删除 N 天前的日志，返回删除数量"""
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        count = db.query(SystemLog).filter(SystemLog.created_at < cutoff).delete()
        db.commit()
        return count
