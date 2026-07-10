import pymysql
import bcrypt

# 数据库配置
config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'liuwenpeng',
    'password': 'liuwenpeng123',
    'database': 'easy-novel',
    'charset': 'utf8mb4'
}

# 普通用户信息
username = "normaluser"
password = "normal123"
email = "normal@example.com"

# 加密密码
hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# 插入用户SQL
sql = """
INSERT INTO users (username, password, email, is_super_admin, status) 
VALUES (%s, %s, %s, %s, %s)
"""

try:
    # 连接数据库
    connection = pymysql.connect(**config)
    cursor = connection.cursor()
    
    # 执行SQL
    cursor.execute(sql, (username, hashed_password, email, 0, 1))
    connection.commit()
    
    print(f"普通用户创建成功！")
    print(f"用户名: {username}")
    print(f"密码: {password}")
    print(f"邮箱: {email}")
    
    # 关闭连接
    cursor.close()
    connection.close()
    
except Exception as e:
    print(f"创建用户失败: {e}")
