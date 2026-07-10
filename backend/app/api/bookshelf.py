from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.bookshelf_service import BookshelfService, ProfileService
from app.api.deps import get_current_user

router = APIRouter(prefix="/api/bookshelf", tags=["书架"])


@router.post("/add")
def add_to_bookshelf(
    novel_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """加入书架"""
    return BookshelfService.add_to_bookshelf(db, current_user["user_id"], novel_unique_id)


@router.post("/remove")
def remove_from_bookshelf(
    novel_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """移出书架"""
    return BookshelfService.remove_from_bookshelf(db, current_user["user_id"], novel_unique_id)


@router.get("/check")
def check_bookshelf(
    novel_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """检查某作品是否已在书架中"""
    return BookshelfService.is_in_bookshelf(db, current_user["user_id"], novel_unique_id)


@router.get("/list")
def list_bookshelf(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取我的书架列表"""
    return BookshelfService.list_bookshelf(db, current_user["user_id"])


@router.post("/progress")
def save_progress(
    novel_unique_id: str,
    chapter_unique_id: str,
    chapter_name: str = "",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """保存阅读进度（书架中的书）"""
    return BookshelfService.save_progress(
        db, current_user["user_id"], novel_unique_id, chapter_unique_id, chapter_name
    )
