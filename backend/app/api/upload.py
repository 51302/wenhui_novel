import os
import uuid
import traceback
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(prefix="/api/upload", tags=["文件上传"])

# 图片上传到 frontend/public/uploads，前端可直接访问 /uploads/xxx.png
_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "public", "uploads")
UPLOAD_DIR = os.path.abspath(_UPLOAD_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """上传封面图片，保存到 frontend/public/uploads/"""
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="只支持上传图片文件")

        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")

        ext = os.path.splitext(file.filename or "image.png")[1] or ".png"
        unique_name = uuid.uuid4().hex + ext
        file_path = os.path.join(UPLOAD_DIR, unique_name)

        with open(file_path, "wb") as f:
            f.write(content)

        file_url = f"/uploads/{unique_name}"
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
