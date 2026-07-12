from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.novel_service import NovelService
from app.api.deps import get_current_user, check_creation_access

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
    _perm=Depends(check_creation_access),
):
    """
    创建小说作品
    必需参数：书名、读者受众（男频/女频）
    可选：简介、故事背景、世界观设定、修炼境界、角色设定、题材、封面
    """
    from app.utils.logger import system_logger
    result = NovelService.create_novel(
        db, current_user["user_id"], current_user["username"],
        title, target_reader, description, story_background,
        world_setting, realm_setting, characters, genre, cover_image, current_user["username"]
    )
    if result.get("状态码") == 200:
        novel_id = result.get("数据", {}).get("novel_unique_id", "")
        system_logger.info(f"小说创建成功: {title} (ID={novel_id}, 用户={current_user['username']})")
    else:
        system_logger.warning(f"小说创建失败: {title} → {result.get('消息', '')}")
    return result


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
    _vip=Depends(check_creation_access),
):
    """删除小说作品（含所有关联章节）"""
    from app.utils.logger import system_logger
    result = NovelService.delete_novel(db, novel_unique_id)
    if result.get("状态码") == 200:
        system_logger.info(f"小说删除成功: ID={novel_unique_id}, 用户={current_user['username']}")
    return result

@router.put("/update/{novel_unique_id}")
def update_novel(
    novel_unique_id: str,
    title: str = None, target_reader: str = None,
    description: str = None, story_background: str = None,
    world_setting: str = None, genre: str = None,
    cover_image: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _vip=Depends(check_creation_access),
):
    """更新小说作品信息（标题、简介、世界观设定等）"""
    from app.utils.logger import system_logger
    result = NovelService.update_novel(
        db, novel_unique_id, title, target_reader, description,
        story_background, world_setting, genre, cover_image
    )
    if result.get("状态码") == 200:
        system_logger.info(f"小说更新成功: ID={novel_unique_id}, 用户={current_user['username']}")
    return result
