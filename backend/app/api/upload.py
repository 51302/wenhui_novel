import os
import uuid
import traceback
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(prefix="/api/upload", tags=["文件上传"])


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """上传封面图片到 SeaweedFS"""
    try:
        content = await file.read()

        if file.content_type and not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="只支持上传图片文件")

        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")

        ext = os.path.splitext(file.filename or "image.png")[1] or ".png"
        unique_name = uuid.uuid4().hex + ext

        from app.utils.seaweedfs_client import upload_file
        file_url = upload_file(content, unique_name, file.content_type or "image/png")

        if not file_url:
            raise HTTPException(status_code=503, detail="SeaweedFS 存储服务不可用，请稍后重试")

        print(f"[UPLOAD] SeaweedFS 上传成功: {file_url}")

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
