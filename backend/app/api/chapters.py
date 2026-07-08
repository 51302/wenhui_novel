from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.chapter_service import ChapterService
from app.api.deps import get_current_user, require_vip
from app.utils.response import fail
from pydantic import BaseModel

router = APIRouter(prefix="/api/chapters", tags=["章节"])


@router.post("/create")
def create_chapter(
    novel_unique_id: str, chapter_name: str,
    characters_involved: str = None, organizations: str = None,
    locations: str = None, skills: str = None,
    word_count: int = 0, chapter_summary: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    return ChapterService.create_chapter(
        db, novel_unique_id, current_user["user_id"],
        chapter_name, characters_involved, organizations,
        locations, skills, word_count, chapter_summary,
        current_user["username"]
    )


@router.post("/generate")
async def generate_chapter(
    novel_unique_id: str, chapter_name: str,
    characters_involved: str = None, organizations: str = None,
    locations: str = None, skills: str = None,
    word_count: int = 2000, chapter_summary: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    return await ChapterService.generate_with_ai(
        db, novel_unique_id, current_user["user_id"],
        chapter_name, characters_involved, organizations,
        locations, skills, word_count, chapter_summary,
        current_user["username"]
    )


@router.get("/drafts")
def get_drafts(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return ChapterService.get_drafts(db, current_user["user_id"])


@router.put("/update/{chapter_unique_id}")
def update_chapter(
    chapter_unique_id: str,
    content: str = None, chapter_name: str = None,
    chapter_summary: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    return ChapterService.update_chapter(
        db, chapter_unique_id, content, chapter_name, chapter_summary
    )


@router.post("/publish/{chapter_unique_id}")
def publish_chapter(
    chapter_unique_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    """发布章节到作品圈"""
    return ChapterService.publish_chapter(db, chapter_unique_id, body.get("content"))


@router.delete("/delete/{chapter_unique_id}")
def delete_chapter(
    chapter_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(require_vip),
):
    return ChapterService.delete_chapter(db, chapter_unique_id)


@router.get("/novel/{novel_unique_id}")
def get_novel_chapters(
    novel_unique_id: str,
    db: Session = Depends(get_db)
):
    return ChapterService.get_novel_chapters(db, novel_unique_id)
