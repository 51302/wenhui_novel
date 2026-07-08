import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import bcrypt

# 数据库连接
DATABASE_URL = "mysql+pymysql://liuwenpeng:liuwenpeng123@localhost:3306/easy-novel"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

# 创建超级用户
username = "superuser"
password = "super123456"
hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

try:
    from app.models.user import User
    from app.models.base import Base
    
    # 检查用户是否已存在
    existing_user = session.query(User).filter(User.username == username).first()
    if existing_user:
        print(f"用户 {username} 已存在，更新为超级用户")
        existing_user.is_super_admin = 1
        session.commit()
    else:
        # 创建新用户
        new_user = User(
            username=username,
            password=hashed_password,
            is_super_admin=1,
            status=1
        )
        session.add(new_user)
        session.commit()
        print(f"超级用户 {username} 创建成功")
        print(f"用户名: {username}")
        print(f"密码: {password}")
        
except Exception as e:
    print(f"错误: {e}")
    session.rollback()
finally:
    session.close()
