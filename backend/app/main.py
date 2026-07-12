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
from app.models.log import SystemLog
from app.api.auth import router as auth_router
from app.api.novels import router as novels_router
from app.api.chapters import router as chapters_router
from app.api.interactions import router as interactions_router
from app.api.upload import router as upload_router
from app.api.vip import router as vip_router
from app.api.bookshelf import router as bookshelf_router
from app.api.logs import router as logs_router
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

    # 启动时清理 7 天前日志
    _start_log_cleanup_scheduler()

    yield

    print("文辉小说后端关闭")


def _start_log_cleanup_scheduler():
    """后台线程：每小时检查并清理 7 天前的日志"""
    import threading
    import time
    from sqlalchemy.orm import Session
    from app.models.base import SessionLocal
    from app.service.log_service import LogService

    def cleanup_loop():
        while True:
            time.sleep(3600)  # 每小时执行一次
            db = SessionLocal()
            try:
                LogService.cleanup_old_logs(db, days=7)
            except Exception as e:
                print(f"[日志定时清理异常] {e}")
            finally:
                db.close()

    t = threading.Thread(target=cleanup_loop, daemon=True)
    t.start()
    print("[日志] 后台定时清理已启动（每1小时清理7天前日志）")


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
app.include_router(logs_router)


# ====== 请求日志中间件 ======
@app.middleware("http")
async def log_requests(request, call_next):
    import time as _time
    start = _time.time()
    response = await call_next(request)
    duration = _time.time() - start

    # 不需要记录静态资源和健康检查
    path = request.url.path
    if path.startswith("/uploads") or path.startswith("/covers") or path == "/api/health":
        return response

    status = response.status_code
    level = "ERROR" if status >= 500 else ("WARNING" if status >= 400 else "INFO")
    method = request.method
    from app.models.base import SessionLocal
    from app.service.log_service import LogService
    db = SessionLocal()
    try:
        LogService.write_log(
            db,
            level=level,
            message=f"{method} {path} → {status} ({duration:.2f}s)",
            source="api",
            path=path,
            method=method,
            status_code=status,
        )
    except Exception as e:
        print(f"[请求日志写入异常] {e}")
    finally:
        db.close()

    return response


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
