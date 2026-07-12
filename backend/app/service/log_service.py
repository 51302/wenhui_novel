from sqlalchemy.orm import Session
from app.dao.log_dao import LogDAO
from app.utils.response import success, fail


class LogService:

    @staticmethod
    def write_log(db: Session, level: str, message: str, source: str = "system",
                  path: str = None, method: str = None, status_code: int = None,
                  user_id: int = None):
        """写一条日志"""
        try:
            LogDAO.create(db, level=level, message=message, source=source,
                          path=path, method=method, status_code=status_code,
                          user_id=user_id)
        except Exception as e:
            print(f"[日志写入失败] {e}")

    @staticmethod
    def query_logs(db: Session, level: str = None, source: str = None,
                   keyword: str = None, since_id: int = 0,
                   page: int = 1, page_size: int = 50) -> dict:
        """查询日志列表（支持轮询 since_id）"""
        try:
            logs, total = LogDAO.query_logs(
                db, level=level, source=source, keyword=keyword,
                since_id=since_id, page=page, page_size=page_size
            )
            items = []
            for log in logs:
                items.append({
                    "id": log.id,
                    "level": log.level,
                    "source": log.source,
                    "message": log.message,
                    "path": log.path or "",
                    "method": log.method or "",
                    "status_code": log.status_code,
                    "user_id": log.user_id,
                    "created_at": log.created_at.isoformat() if log.created_at else "",
                })
            max_id = LogDAO.get_max_id(db)
            return success({
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "max_id": max_id,
            })
        except Exception as e:
            return fail(f"查询日志失败: {str(e)}")

    @staticmethod
    def cleanup_old_logs(db: Session, days: int = 7) -> int:
        """清理 N 天前的日志"""
        try:
            count = LogDAO.delete_before_days(db, days)
            if count > 0:
                print(f"[日志清理] 已删除 {count} 条 {days} 天前的日志")
            return count
        except Exception as e:
            print(f"[日志清理失败] {e}")
            return 0
