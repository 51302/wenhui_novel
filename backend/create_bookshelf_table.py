import pymysql

# 数据库配置
config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'liuwenpeng',
    'password': 'liuwenpeng123',
    'database': 'easy-novel',
    'charset': 'utf8mb4'
}

# 创建书架表的SQL
sql = """
CREATE TABLE IF NOT EXISTS bookshelf (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增ID',
  user_id INT NOT NULL COMMENT '用户ID',
  novel_unique_id VARCHAR(64) NOT NULL COMMENT '作品唯一ID',
  last_chapter_unique_id VARCHAR(64) DEFAULT NULL COMMENT '最后阅读章节ID',
  last_chapter_name VARCHAR(256) DEFAULT NULL COMMENT '最后阅读章节名称',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  INDEX idx_user_id (user_id),
  INDEX idx_novel_unique_id (novel_unique_id),
  UNIQUE KEY uk_user_novel (user_id, novel_unique_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='书架表';
"""

try:
    # 连接数据库
    connection = pymysql.connect(**config)
    cursor = connection.cursor()
    
    # 执行SQL
    cursor.execute(sql)
    connection.commit()
    
    print("书架表创建成功！")
    
    # 关闭连接
    cursor.close()
    connection.close()
    
except Exception as e:
    print(f"创建表失败: {e}")
