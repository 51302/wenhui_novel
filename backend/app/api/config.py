from fastapi import APIRouter
from app.config import show_all_works

router = APIRouter(prefix="/api/config", tags=["配置"])


@router.get("/public")
def get_public_config():
    """获取前端公开配置（无需登录）
    包含 show_all_works 等前端需要的开关配置
    """
    return {
        "状态码": 200,
        "消息": "获取成功",
        "数据": {
            "show_all_works": show_all_works()
        }
    }
