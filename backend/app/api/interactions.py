from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.models.base import get_db
from app.service.interaction_service import InteractionService
from app.api.deps import get_current_user

router = APIRouter(prefix="/api/interactions", tags=["互动"])


@router.post("/comment")
def comment(
    novel_unique_id: str, comment_text: str,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return InteractionService.comment(
        db, novel_unique_id, user_id,
        current_user["user_id"], current_user["username"], comment_text
    )


@router.post("/like")
def like(
    novel_unique_id: str, user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return InteractionService.like(
        db, novel_unique_id, user_id,
        current_user["user_id"], current_user["username"]
    )


@router.post("/follow")
def follow(
    novel_unique_id: str, user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return InteractionService.follow(
        db, novel_unique_id, user_id,
        current_user["user_id"], current_user["username"]
    )


@router.post("/bookmark")
def bookmark(
    novel_unique_id: str, user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return InteractionService.bookmark(
        db, novel_unique_id, user_id,
        current_user["user_id"], current_user["username"]
    )


@router.get("/comments/{novel_unique_id}")
def get_comments(
    novel_unique_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    return InteractionService.get_comments(db, novel_unique_id, page, page_size)


@router.get("/feed")
def get_feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    return InteractionService.get_feed(db, page, page_size)
