from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get as cfg_get

MYSQL_HOST = cfg_get("mysql.host")
MYSQL_PORT = cfg_get("mysql.port")
MYSQL_USER = cfg_get("mysql.user")
MYSQL_PASSWORD = cfg_get("mysql.password")
MYSQL_DATABASE = cfg_get("mysql.database")

DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"

engine = create_engine(DATABASE_URL, pool_size=30, max_overflow=50, pool_pre_ping=True, pool_recycle=3600)
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
