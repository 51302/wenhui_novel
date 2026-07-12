from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.log_service import LogService

router = APIRouter(prefix="/api/logs", tags=["系统日志"])


@router.get("/list")
def get_logs(
    level: str = Query(None, description="日志级别: INFO/WARNING/ERROR/ALL"),
    source: str = Query(None, description="来源: api/user/system"),
    keyword: str = Query(None, description="搜索关键词"),
    since_id: int = Query(0, description="轮询: 只返回 id > since_id 的新日志"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """查询日志列表，支持筛选、搜索、轮询"""
    return LogService.query_logs(
        db, level=level, source=source, keyword=keyword,
        since_id=since_id, page=page, page_size=page_size
    )


@router.get("/max-id")
def get_max_id(db: Session = Depends(get_db)):
    """获取最新日志ID（用于前端轮询起始点）"""
    from app.dao.log_dao import LogDAO
    return {"max_id": LogDAO.get_max_id(db)}


@router.post("/cleanup")
def manual_cleanup(days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)):
    """手动清理 N 天前的日志"""
    count = LogService.cleanup_old_logs(db, days)
    return {"deleted": count, "message": f"已清理 {count} 条 {days} 天前的日志"}
