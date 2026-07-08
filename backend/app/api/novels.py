from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.novel_service import NovelService
from app.api.deps import get_current_user, require_vip

router = APIRouter(prefix="/api/novels", tags=["小说"])


@router.post("/create")
def create_novel(
    title: str, target_reader: str,
    description: str = "", story_background: str = "",
    world_setting: str = "", realm_setting: str = None,
    characters: str = None, genre: str = None,
    cover_image: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    return NovelService.create_novel(
        db, current_user["user_id"], current_user["username"],
        title, target_reader, description, story_background,
        world_setting, realm_setting, characters, genre, cover_image, current_user["username"]
    )


@router.get("/list")
def list_novels(
    target_reader: str = Query(None, description="男频/女频"),
    genre: str = Query(None, description="题材"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db)
):
    return NovelService.list_novels(db, target_reader, genre, page, page_size)


@router.get("/search")
def search_novels(
    keyword: str = Query(..., description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db)
):
    return NovelService.search_novels(db, keyword, page, page_size)


@router.get("/detail/{novel_unique_id}")
def get_novel_detail(novel_unique_id: str, db: Session = Depends(get_db)):
    return NovelService.get_novel_detail(db, novel_unique_id)


@router.get("/my")
def my_novels(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return NovelService.get_user_novels(db, current_user["user_id"])


@router.delete("/delete/{novel_unique_id}")
def delete_novel(
    novel_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    return NovelService.delete_novel(db, novel_unique_id)


@router.put("/update/{novel_unique_id}")
def update_novel(
    novel_unique_id: str,
    title: str = None,
    target_reader: str = None,
    description: str = None,
    story_background: str = None,
    world_setting: str = None,
    genre: str = None,
    cover_image: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    return NovelService.update_novel(
        db, novel_unique_id, title, target_reader, description,
        story_background, world_setting, genre, cover_image
    )
