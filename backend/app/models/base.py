from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get as cfg_get

MYSQL_HOST = cfg_get("mysql.host")
MYSQL_PORT = cfg_get("mysql.port")
MYSQL_USER = cfg_get("mysql.user")
MYSQL_PASSWORD = cfg_get("mysql.password")
MYSQL_DATABASE = cfg_get("mysql.database")

DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"

# 连接池参数从 config.yaml 读取，便于不重启代码调优
MYSQL_POOL_SIZE = int(cfg_get("mysql.pool_size", 10))
MYSQL_MAX_OVERFLOW = int(cfg_get("mysql.max_overflow", 20))
MYSQL_POOL_RECYCLE = int(cfg_get("mysql.pool_recycle", 3600))

engine = create_engine(
    DATABASE_URL,
    pool_size=MYSQL_POOL_SIZE,
    max_overflow=MYSQL_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=MYSQL_POOL_RECYCLE,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    FastAPI 依赖注入：获取数据库会话
    yield SessionLocal()，请求结束后自动关闭连接
    用法：db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
