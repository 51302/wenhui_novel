from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from app.models.base import get_db
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.service.chapter_service import ChapterService
from app.api.deps import get_current_user, check_generate_permission, require_svip
from fastapi.responses import StreamingResponse
from app.utils.response import fail, success
from app.utils.logger import system_logger
from app.utils.task_queue import TaskQueue
from pydantic import BaseModel
from urllib.parse import quote
import io
import os
import zipfile

router = APIRouter(prefix="/api/chapters", tags=["章节"])


# ============================================================
# 任务状态查询（供前端轮询异步任务结果）
# ============================================================

@router.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    """查询异步任务状态
    返回: {"status": "pending|processing|done|failed", "result": {...}, "error": "..."}
    """
    status = TaskQueue.get_status(task_id)
    return success(status, "查询成功")


# ============================================================
# 章节 CRUD
# ============================================================

class CreateChapterBody(BaseModel):
    novel_unique_id: str
    chapter_name: str
    characters_involved: str = None
    organizations: str = None
    locations: str = None
    skills: str = None
    word_count: int = 0
    chapter_summary: str = None
    chapter_number: int = None


@router.post("/create")
def create_chapter(
    body: CreateChapterBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建空白章节草稿"""
    return ChapterService.create_chapter(
        db, body.novel_unique_id, current_user["user_id"],
        body.chapter_name, body.characters_involved, body.organizations,
        body.locations, body.skills, body.word_count, body.chapter_summary,
        current_user["username"], body.chapter_number
    )


class GenerateChapterBody(BaseModel):
    novel_unique_id: str
    chapter_name: str
    characters_involved: str = None
    organizations: str = None
    locations: str = None
    skills: str = None
    word_count: int = 2000
    chapter_summary: str = None


@router.post("/generate")
def generate_chapter(
    body: GenerateChapterBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(check_generate_permission),
):
    """调用AI生成章节正文内容（异步：提交队列后返回 task_id，前端轮询结果）"""
    # 草稿箱检测：生成新章节前必须保证草稿箱为空
    from app.dao.chapter_dao import ChapterDAO
    drafts = ChapterDAO.get_drafts(db, current_user["user_id"])
    if drafts:
        draft_names = "、".join(d.chapter_name for d in drafts[:5])
        return fail(f"草稿箱未删除，请先删除草稿箱中的内容（草稿：{draft_names}）后再生成新章节", code=400)

    task_id = TaskQueue.push("ai:generate", {
        "novel_unique_id": body.novel_unique_id,
        "user_id": current_user["user_id"],
        "chapter_name": body.chapter_name,
        "characters_involved": body.characters_involved,
        "organizations": body.organizations,
        "locations": body.locations,
        "skills": body.skills,
        "word_count": body.word_count,
        "chapter_summary": body.chapter_summary,
        "created_by": current_user["username"],
    }, ttl=1800)
    if not task_id:
        return fail("系统繁忙，请稍后重试", code=503)
    system_logger.info(f"[队列] 提交AI生成任务: {body.chapter_name} → task_id={task_id}")
    return success({
        "task_id": task_id,
        "queue_name": "ai:generate",
    }, "AI生成任务已提交，请稍后查询结果")


class RegenerateBody(BaseModel):
    chapter_summary: str = None
    word_count: int = 2000


@router.post("/regenerate/{chapter_unique_id}")
async def regenerate_chapter(
    chapter_unique_id: str,
    body: RegenerateBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(check_generate_permission),
    _svip: dict = Depends(require_svip),
):
    """重新生成指定章节（同步：直接调用 AI 并返回内容，前端不需要轮询）"""
    from app.service.chapter_service import ChapterService
    result = await ChapterService.regenerate_with_ai(
        db, chapter_unique_id, current_user["user_id"],
        word_count=body.word_count, chapter_summary=body.chapter_summary,
    )
    if result.get("状态码") == 200:
        ch = result.get("数据", {})
        system_logger.info(f"AI重新生成成功: {ch.get('chapter_name','')} ({ch.get('word_count',0)}字) ID={chapter_unique_id}")
    else:
        system_logger.warning(f"AI重新生成失败: ID={chapter_unique_id} → {result.get('消息', '')}")
    return result


@router.post("/continue/{chapter_unique_id}")
def continue_chapter(
    chapter_unique_id: str,
    word_count: int = 2000,
    db: Session = Depends(get_db),
    current_user: dict = Depends(check_generate_permission),
):
    """AI续写指定章节（异步：提交队列后返回 task_id，前端轮询结果）"""
    task_id = TaskQueue.push("ai:continue", {
        "chapter_unique_id": chapter_unique_id,
        "word_count": word_count,
    }, ttl=1800)
    if not task_id:
        return fail("系统繁忙，请稍后重试", code=503)
    system_logger.info(f"[队列] 提交AI续写任务: {chapter_unique_id} → task_id={task_id}")
    return success({
        "task_id": task_id,
        "queue_name": "ai:continue",
    }, "AI续写任务已提交，请稍后查询结果")


@router.get("/drafts")
def get_drafts(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户的所有草稿章节"""
    try:
        return ChapterService.get_drafts(db, current_user["user_id"])
    except Exception as e:
        system_logger.error(f"获取草稿列表失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return fail(f"获取草稿列表失败: {str(e)}", code=500)


class UpdateChapterBody(BaseModel):
    chapter_name: str = None
    chapter_summary: str = None
    content: str = None


@router.put("/update/{chapter_unique_id}")
def update_chapter(
    chapter_unique_id: str,
    body: UpdateChapterBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新章节名称、概要或正文"""
    return ChapterService.update_chapter(
        db, chapter_unique_id,
        chapter_name=body.chapter_name,
        chapter_summary=body.chapter_summary,
        content=body.content,
    )


@router.post("/publish/{chapter_unique_id}")
def publish_chapter(
    chapter_unique_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    发布章节到作品圈
    附带 AI 提取的关键信息（人物/组织/地点/技能/事件等）
    发布不扣减配额（配额仅在 AI 生成时扣减）
    """
    result = ChapterService.publish_chapter(
        db, chapter_unique_id,
        content=body.get("content"),
        characters_involved=body.get("characters_involved"),
        organizations=body.get("organizations"),
        locations=body.get("locations"),
        skills=body.get("skills"),
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
def extract_chapter_info(
    body: ExtractInfoBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    前端草稿箱：从章节内容中 AI 提取关键信息（异步队列）
    返回 task_id，前端轮询 /api/chapters/tasks/{task_id} 获取结果
    """
    if not body.content or len(body.content.strip()) < 10:
        return fail("章节内容太短，无法提取")
    task_id = TaskQueue.push("ai:extract", {
        "content": body.content,
        "chapter_name": body.chapter_name,
    }, ttl=1800)
    if not task_id:
        return fail("系统繁忙，请稍后重试", code=503)
    system_logger.info(f"[队列] 提交AI提取任务: {body.chapter_name} → task_id={task_id}")
    return success({
        "task_id": task_id,
        "queue_name": "ai:extract",
    }, "AI提取任务已提交，请稍后查询结果")


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
    try:
        beijing_tz = timezone(timedelta(hours=8))
        now_beijing = datetime.now(timezone.utc).astimezone(beijing_tz)
        today_start = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start.astimezone(timezone.utc).replace(tzinfo=None)
        count = db.query(Chapter).filter(
            Chapter.user_id == current_user["user_id"],
            Chapter.is_published == True,
            Chapter.created_at >= today_start_utc,
        ).count()
        return success({"published_today": count}, "查询成功")
    except Exception as e:
        system_logger.error(f"统计今日发布数量失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return fail(f"统计今日发布数量失败: {str(e)}", code=500)


@router.get("/download/{novel_unique_id}")
def download_novel(
    novel_unique_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """下载作品全部章节为ZIP包，每章一个TXT文件，文件名：书名_时间.zip"""
    novel = db.query(Novel).filter(
        Novel.novel_unique_id == novel_unique_id,
        Novel.author_user_id == current_user["user_id"],
    ).first()
    if not novel:
        return fail("作品不存在", code=404)

    chapters = db.query(Chapter).filter(
        Chapter.novel_unique_id == novel_unique_id,
        Chapter.user_id == current_user["user_id"],
    ).order_by(Chapter.id.asc()).all()

    if not chapters:
        return fail("该作品暂无章节", code=404)

    zip_buf = io.BytesIO()
    novel_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "novel_structure_data", novel_unique_id)
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, ch in enumerate(chapters, 1):
            # 从 TXT 文件读取正文
            content = "（本章暂无内容）"
            txt_path = os.path.join(novel_dir, f"{ch.chapter_name}_{ch.chapter_unique_id}.txt")
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    content = f.read()
            filename = f"第{i}章 {ch.chapter_name}.txt"
            zf.writestr(filename, content.encode('utf-8-sig'))

    zip_buf.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_filename = f"{novel.title}_{timestamp}.zip"

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(zip_filename)}"}
    )
