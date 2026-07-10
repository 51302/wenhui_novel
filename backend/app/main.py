import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from app.models.base import engine, get_db
from app.models.base import Base
from app.models.user import User
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.interaction import WorkInteraction
from app.models.vip_order import VIPOrder
from app.models.bookshelf import Bookshelf
from app.api.auth import router as auth_router
from app.api.novels import router as novels_router
from app.api.chapters import router as chapters_router
from app.api.interactions import router as interactions_router
from app.api.upload import router as upload_router
from app.api.vip import router as vip_router
from app.api.bookshelf import router as bookshelf_router
from app.utils.redis_cache import RedisCache, redis_client as global_redis
from app.utils.chroma_client import ChromaMemoryStore, chroma_memory as global_chroma
from app.config import get as cfg_get


@asynccontextmanager
async def lifespan(application: FastAPI):
    global global_redis, global_chroma

    global_redis = RedisCache(
        host=os.getenv("REDIS_HOST", cfg_get("redis.host", "localhost")),
        port=int(os.getenv("REDIS_PORT", cfg_get("redis.port", 6379))),
        password=os.getenv("REDIS_PASSWORD", cfg_get("redis.password", "")),
        db=cfg_get("redis.db", 0),
        default_ttl=cfg_get("redis.cache_ttl", 3600)
    )
    import app.utils.redis_cache as mod_redis
    mod_redis.redis_client = global_redis

    global_chroma = ChromaMemoryStore(
        persist_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "vector_db_data"),
        collection_name=cfg_get("chromadb.collection_name", "novel_memory")
    )
    import app.utils.chroma_client as mod_chroma
    mod_chroma.chroma_memory = global_chroma

    Base.metadata.create_all(bind=engine)
    print("文辉小说后端启动成功!")

    yield

    print("文辉小说后端关闭")


app = FastAPI(title="文辉小说", version="1.0.0", docs_url="/api/docs", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录（upload上传的封面图片 + AI生成封面）
_UPLOAD_STATIC = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "uploads"
_UPLOAD_STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_UPLOAD_STATIC)), name="uploads")
_COVERS_STATIC = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "covers"
_COVERS_STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/covers", StaticFiles(directory=str(_COVERS_STATIC)), name="covers")

app.include_router(auth_router)
app.include_router(novels_router)
app.include_router(chapters_router)
app.include_router(interactions_router)
app.include_router(upload_router)
app.include_router(vip_router)
app.include_router(bookshelf_router)


# ====== 健康检查缓存（避免每次请求都建 DB 连接） ======
_health_cache = {"mysql": True, "redis": True, "updated_at": 0}
_HEALTH_CACHE_TTL = 5  # 5 秒内用缓存，不重复检查


@app.get("/api/health")
def health_check():
    import time
    now = time.time()
    if now - _health_cache["updated_at"] < _HEALTH_CACHE_TTL:
        return {
            "状态码": 200, "消息": "服务正常",
            "数据": {"mysql": _health_cache["mysql"], "redis": _health_cache["redis"],
                     "status": "ok" if _health_cache["mysql"] else "degraded"}
        }

    redis_alive = global_redis.ping() if global_redis else False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        mysql_alive = True
    except Exception:
        mysql_alive = False

    _health_cache["mysql"] = mysql_alive
    _health_cache["redis"] = redis_alive
    _health_cache["updated_at"] = now

    return {
        "状态码": 200, "消息": "服务正常",
        "数据": {"mysql": mysql_alive, "redis": redis_alive,
                 "status": "ok" if mysql_alive else "degraded"}
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
