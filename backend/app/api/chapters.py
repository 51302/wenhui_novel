from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.chapter_service import ChapterService
from app.api.deps import get_current_user, check_generate_permission, check_creation_access
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
    _perm=Depends(check_generate_permission),
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
    _perm=Depends(check_generate_permission),
):
    return await ChapterService.generate_with_ai(
        db, novel_unique_id, current_user["user_id"],
        chapter_name, characters_involved, organizations,
        locations, skills, word_count, chapter_summary,
        current_user["username"]
    )


@router.post("/continue/{chapter_unique_id}")
async def continue_chapter(
    chapter_unique_id: str,
    word_count: int = 800,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _perm=Depends(check_generate_permission),
):
    """AI续写指定章节：根据作品设定、前序章节、当前内容续写"""
    return await ChapterService.continue_with_ai(db, chapter_unique_id, word_count)


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
    _vip=Depends(check_creation_access),
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
    _vip=Depends(check_creation_access),
):
    """发布章节到作品圈，附带AI提取的关键信息"""
    return ChapterService.publish_chapter(
        db, chapter_unique_id,
        content=body.get("content"),
        characters_involved=body.get("characters_involved"),
        organizations=body.get("organizations"),
        locations=body.get("locations"),
        skills=body.get("skills"),
        events=body.get("events"),
        time_info=body.get("time_info"),
        key_items=body.get("key_items"),
        power_changes=body.get("power_changes"),
        foreshadowing=body.get("foreshadowing"),
    )


class ExtractInfoBody(BaseModel):
    content: str
    chapter_name: str = ""

@router.post("/extract-info")
async def extract_chapter_info(
    body: ExtractInfoBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    前端草稿箱：从章节内容中 AI 提取关键信息
    返回: 人物、组织、功法/技能、关键事件、地点、时间线、关键物品、实力变化、伏笔/悬念
    """
    result = await ChapterService.extract_chapter_info(body.content, body.chapter_name)
    if result.get("success"):
        return success(result["data"], "提取成功")
    return fail(result.get("error", "提取失败"))


@router.delete("/delete/{chapter_unique_id}")
def delete_chapter(
    chapter_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(check_creation_access),
):
    return ChapterService.delete_chapter(db, chapter_unique_id)


@router.get("/novel/{novel_unique_id}")
def get_novel_chapters(
    novel_unique_id: str,
    db: Session = Depends(get_db)
):
    return ChapterService.get_novel_chapters(db, novel_unique_id)
