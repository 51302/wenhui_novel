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
from app.api.config import router as config_router
from app.api.screenplay import router as screenplay_router
from app.utils.redis_cache import RedisCache, redis_client as global_redis
from app.utils.logger import system_logger
from app.utils.task_queue import TaskQueue
from app.config import get as cfg_get


@asynccontextmanager
async def lifespan(application: FastAPI):
    """应用生命周期管理：启动时初始化 Redis/ChromaDB 连接并建表，关闭时记录日志"""
    global global_redis

    global_redis = RedisCache(
        host=os.environ.get("REDIS_HOST", cfg_get("redis.host")),
        port=int(os.environ.get("REDIS_PORT", cfg_get("redis.port", 6379))),
        password=os.environ.get("REDIS_PASSWORD", cfg_get("redis.password", "")),
        db=cfg_get("redis.db"),
        default_ttl=cfg_get("redis.cache_ttl")
    )
    import app.utils.redis_cache as mod_redis
    mod_redis.redis_client = global_redis

    Base.metadata.create_all(bind=engine)

    # ====== 服务启动日志 ======
    try:
        redis_ok = global_redis.ping() if global_redis else False
        db_ok = False
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ok = True
        system_logger.info(f"服务启动成功 → MySQL={'✓' if db_ok else '✗'} Redis={'✓' if redis_ok else '✗'}")
    except Exception as e:
        system_logger.warning(f"服务启动完成(部分服务不可用): {e}")

    # ====== 启动后台 Worker 线程（消费 Redis 任务队列） ======
    # 各队列并发数从 config.yaml → task_queue.workers.* 读取
    try:
        from app.service.chapter_service import ChapterService
        def _worker_concurrency(queue_name: str, default: int) -> int:
            return int(cfg_get(f"task_queue.workers.{queue_name}", default))

        TaskQueue.start_worker("ai:extract",      ChapterService._worker_extract_info,  concurrency=_worker_concurrency("ai:extract", 2))
        TaskQueue.start_worker("ai:generate",     ChapterService._worker_generate,      concurrency=_worker_concurrency("ai:generate", 2))
        TaskQueue.start_worker("ai:regenerate",   ChapterService._worker_regenerate,    concurrency=_worker_concurrency("ai:regenerate", 2))
        TaskQueue.start_worker("ai:continue",     ChapterService._worker_continue,      concurrency=_worker_concurrency("ai:continue", 2))
        TaskQueue.start_worker("ai:screenplay",   ChapterService._worker_generate_screenplay, concurrency=_worker_concurrency("ai:screenplay", 1))
        system_logger.info(
            f"后台Worker线程启动完成 "
            f"(max_concurrency={TaskQueue._max_concurrency}, "
            f"workers={ {q: _worker_concurrency(q, 0) for q in ['ai:extract','ai:generate','ai:regenerate','ai:continue','ai:screenplay']} })"
        )
    except Exception as e:
        system_logger.error(f"启动Worker线程失败: {e}")

    yield  # 服务运行中...

    system_logger.info("服务正常关闭")


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
app.include_router(config_router)
app.include_router(screenplay_router)

# ====== 请求日志中间件 ======
@app.middleware("http")
async def log_requests(request, call_next):
    """HTTP 请求日志中间件：记录每个请求的方法、路径、状态码和耗时，5xx 记 error，4xx 记 warning"""
    import time as _time
    start = _time.time()
    response = await call_next(request)
    duration_ms = (_time.time() - start) * 1000

    path = request.url.path
    if path.startswith("/uploads") or path.startswith("/covers") or path == "/api/health":
        return response

    status = response.status_code
    method = request.method
    msg = f"{method} {path} → {status} {duration_ms:.0f}ms"

    if status >= 500:
        system_logger.error(msg)
    elif status >= 400:
        system_logger.warning(msg)
    else:
        system_logger.info(msg)

    return response


# ====== 健康检查缓存（避免每次请求都建 DB 连接） ======
_health_cache = {"mysql": True, "redis": True, "updated_at": 0}
_HEALTH_CACHE_TTL = 5  # 5 秒内用缓存，不重复检查


@app.get("/api/health")
def health_check():
    """健康检查接口：检查 MySQL 和 Redis 连接状态，5 秒内使用缓存避免重复建连
    :return: 包含 mysql/redis 连接状态的响应字典
    """
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

    # 如果 MySQL 或 Redis 不可用，记录日志
    if not mysql_alive:
        system_logger.error("健康检查: MySQL 连接失败!")
    if not redis_alive:
        system_logger.warning("健康检查: Redis 连接失败!")

    _health_cache["mysql"] = mysql_alive
    _health_cache["redis"] = redis_alive
    _health_cache["updated_at"] = now

    return {
        "状态码": 200, "消息": "服务正常",
        "数据": {"mysql": mysql_alive, "redis": redis_alive,
                 "status": "ok" if mysql_alive else "degraded"}
    }


# ====== Debug: Redis 队列诊断端点 ======
from app.utils.task_queue import _redis as _task_redis, TASK_QUEUE_PREFIX
import json as _json
@app.get("/api/debug/queue")
def debug_queue():
    """调试端点：检查 Redis 连接和队列状态"""
    r = _task_redis()
    from app.utils.task_queue import TASK_QUEUE_PREFIX
    import time as _time
    qkey = f"{TASK_QUEUE_PREFIX}ai:extract"
    unique_test_key = f"debug:rpush:{int(_time.time())}"
    rpush_uuid = str(int(_time.time() * 1000000) % 100000000)
    unique_rpush = r.rpush(unique_test_key, rpush_uuid) if r else False
    _time.sleep(0.1)
    unique_len = r.client.llen(unique_test_key) if (r and r.client) else -1
    unique_items = r.client.lrange(unique_test_key, 0, -1) if (r and r.client) else []
    r.client.delete(unique_test_key)
    return {
        "has_client": str(r.client is not None) if r else "no_r",
        "redis_ping": str(r.ping()) if r else False,
        "unique_rpush_ok": str(unique_rpush),
        "unique_test_key": unique_test_key,
        "unique_len_after": str(unique_len),
        "unique_items": unique_items,
        "queue_exists": str(bool(r.client.exists(qkey)) if r and r.client else False),
    }

# ====== 挂载前端 dist 静态文件（SPA 模式） ======
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    # 先挂载静态资源目录
    _ASSETS = _FRONTEND_DIST / "assets"
    if _ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="assets")
    # 兜底挂载 dist 下其他文件（covers、uploads、index.html 等）
    # 注意：必须在 API 路由注册之后，否则会拦截 API 请求
    from fastapi.responses import FileResponse, Response
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # API 路径不拦截，由已有路由处理（返回 404 等）
        if full_path.startswith("api/"):
            return Response(status_code=404)
        file_path = _FRONTEND_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        # SPA fallback: 返回 index.html（Vue Router 处理前端路由）
        return FileResponse(str(_FRONTEND_DIST / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
