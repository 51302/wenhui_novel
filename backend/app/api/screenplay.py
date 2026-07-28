from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.api.deps import get_current_user
from app.utils.response import fail, success
from app.utils.task_queue import TaskQueue
from app.utils.logger import system_logger
from app.dao.chapter_dao import ChapterDAO
from app.dao.novel_dao import NovelDAO
from pydantic import BaseModel
from typing import List

router = APIRouter(prefix="/api/screenplay", tags=["剧本"])


class GenerateScreenplayBody(BaseModel):
    novel_unique_id: str
    chapter_ids: List[str]  # chapter_unique_id 列表


@router.post("/generate")
def generate_screenplay(
    body: GenerateScreenplayBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """生成剧本（异步：提交队列后返回 task_id，前端轮询结果）
    从选定章节的小说内容转换为剧本格式
    """
    # 验证作品所有权
    novel = NovelDAO.get_by_unique_id(db, body.novel_unique_id)
    if not novel:
        return fail("作品不存在", code=404)
    if novel.author_user_id != current_user["user_id"]:
        return fail("无权操作该作品", code=403)

    # 验证章节存在
    all_chapters = ChapterDAO.get_by_novel_id(db, body.novel_unique_id)
    chapter_map = {c.chapter_unique_id: c for c in all_chapters}
    for cid in body.chapter_ids:
        if cid not in chapter_map:
            return fail(f"章节 {cid} 不存在", code=404)

    task_id = TaskQueue.push("ai:screenplay", {
        "novel_unique_id": body.novel_unique_id,
        "chapter_ids": body.chapter_ids,
        "user_id": current_user["user_id"],
    }, ttl=1800)
    if not task_id:
        return fail("系统繁忙，请稍后重试", code=503)

    system_logger.info(f"[队列] 提交剧本生成任务: {body.novel_unique_id} ({len(body.chapter_ids)}章) → task_id={task_id}")
    return success({
        "task_id": task_id,
        "queue_name": "ai:screenplay",
    }, "剧本生成任务已提交，请稍后查询结果")


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    """查询剧本生成任务状态"""
    status = TaskQueue.get_status(task_id)
    return success(status, "查询成功")
