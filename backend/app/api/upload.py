import os
import uuid
import traceback
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(prefix="/api/upload", tags=["文件上传"])

# 本地兜底目录
_BASE = Path(__file__).resolve().parent.parent.parent.parent
LOCAL_UPLOAD_DIR = _BASE / "frontend" / "public" / "uploads"
LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# SeaweedFS 开关: 环境变量 SEAWEEDFS_ENABLED=true 时优先使用
SEAWEED_ENABLED = os.environ.get("SEAWEEDFS_ENABLED", "true").lower() in ("1", "true", "yes")


def _upload_to_seaweed(file_bytes: bytes, filename: str, content_type: str) -> str | None:
    """上传到 SeaweedFS，返回访问 URL 或 None"""
    from app.utils.seaweedfs_client import upload_file
    url = upload_file(file_bytes, filename, content_type)
    if url:
        print(f"[UPLOAD] SeaweedFS 上传成功: {url}")
    return url


def _save_locally(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """保存到本地磁盘，返回 (文件路径, 访问URL)"""
    file_path = LOCAL_UPLOAD_DIR / filename
    file_path.write_bytes(file_bytes)
    local_url = f"/uploads/{filename}"
    print(f"[UPLOAD] 本地保存成功: {file_path} -> {local_url}")
    return str(file_path), local_url


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """上传封面图片：优先 SeaweedFS，失败/未启用则存本地"""
    try:
        content = await file.read()

        if file.content_type and not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="只支持上传图片文件")

        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")

        ext = os.path.splitext(file.filename or "image.png")[1] or ".png"
        unique_name = uuid.uuid4().hex + ext

        file_url = None

        # 1. 尝试 SeaweedFS
        if SEAWEED_ENABLED:
            seaweed_url = _upload_to_seaweed(content, unique_name, file.content_type or "image/png")
            if seaweed_url:
                # 返回 SeaweedFS 完整 URL，前端 <img> 直接加载
                file_url = seaweed_url
                print(f"[UPLOAD] SeaweedFS URL: {file_url}")

                # 同时本地也存一份（兜底：SeaweedFS 挂了还能用本地）
                _save_locally(content, unique_name)
            else:
                # SeaweedFS 不可用 → 回退本地
                print("[UPLOAD] SeaweedFS 不可用，回退到本地存储")
                _, file_url = _save_locally(content, unique_name)
        else:
            # 未启用 SeaweedFS → 直接本地
            _, file_url = _save_locally(content, unique_name)

        return {
            "success": True,
            "url": file_url,
            "filename": unique_name,
            "size": len(content)
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
