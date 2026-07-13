from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from datetime import datetime
from app.models.base import get_db
from app.models.chapter import Chapter
from app.service.chapter_service import ChapterService
from app.api.deps import get_current_user, check_generate_permission
from app.utils.response import fail, success
from app.utils.logger import system_logger
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
):
    """创建空白章节草稿"""
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
):
    """调用AI生成章节正文内容"""
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
):
    """AI续写指定章节：根据作品设定、前序章节、当前内容续写"""
    return await ChapterService.continue_with_ai(db, chapter_unique_id, word_count)


@router.get("/drafts")
def get_drafts(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户的所有草稿章节"""
    return ChapterService.get_drafts(db, current_user["user_id"])


@router.put("/update/{chapter_unique_id}")
def update_chapter(
    chapter_unique_id: str,
    content: str = None, chapter_name: str = None,
    chapter_summary: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新章节内容、名称或概要"""
    return ChapterService.update_chapter(
        db, chapter_unique_id, content, chapter_name, chapter_summary
    )


@router.post("/publish/{chapter_unique_id}")
def publish_chapter(
    chapter_unique_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _perm=Depends(check_generate_permission),
):
    """
    发布章节到作品圈
    附带 AI 提取的关键信息（人物/组织/地点/技能/事件等）
    发布后同步到作品圈，不自动更新记忆体（由 extract-info 负责）
    """
    result = ChapterService.publish_chapter(
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
    if result.get("状态码") == 200:
        ch_name = result.get("数据", {}).get("chapter_name", "")
        system_logger.info(f"章节发布成功: {ch_name} (ID={chapter_unique_id}, 用户={current_user['username']})")
    else:
        system_logger.warning(f"章节发布失败: ID={chapter_unique_id} → {result.get('消息', '')}")
    return result


class ExtractInfoBody(BaseModel):
    content: str
    chapter_name: str = ""
    novel_unique_id: str = ""

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
    if not body.content or len(body.content.strip()) < 10:
        return fail("章节内容太短，无法提取")
    try:
        result = await ChapterService.extract_chapter_info(body.content, body.chapter_name)
        if result.get("success"):
            # 提取成功 → 更新记忆体
            if body.novel_unique_id and body.chapter_name:
                ChapterService.save_extracted_to_memory(
                    body.novel_unique_id, result["data"], body.chapter_name
                )
            system_logger.info(f"AI关键信息提取成功: {body.chapter_name} (novel={body.novel_unique_id})")
            return success(result["data"], "提取成功")
        return fail(result.get("error", "提取失败"))
    except Exception as e:
        system_logger.error(f"AI关键信息提取异常: {body.chapter_name} → {str(e)}")
        import traceback
        traceback.print_exc()
        return fail(f"提取异常: {str(e)}")


@router.delete("/delete/{chapter_unique_id}")
def delete_chapter(
    chapter_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除指定章节"""
    return ChapterService.delete_chapter(db, chapter_unique_id)


@router.get("/novel/{novel_unique_id}")
def get_novel_chapters(
    novel_unique_id: str,
    db: Session = Depends(get_db)
):
    """获取指定作品的所有章节列表"""
    return ChapterService.get_novel_chapters(db, novel_unique_id)


@router.get("/today-published-count")
def today_published_count(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """统计当前用户今日已发布的章节数量
    用于前端显示「今日已发布 X/Y 章」
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = db.query(Chapter).filter(
        Chapter.user_id == current_user["user_id"],
        Chapter.is_published == True,
        Chapter.updated_at >= today_start,
    ).count()
    return success({"published_today": count}, "查询成功")
