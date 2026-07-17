# ============================================================
#  文辉小说 后端镜像
# ============================================================
FROM python:3.11-slim

# 系统依赖（ChromaDB 需要 sqlite3, onnxruntime 需要 libgomp）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 再拷源码
COPY . .

# 创建数据目录
RUN mkdir -p /app/novel_structure_data /app/vector_db_data

EXPOSE 8000

# 生产模式：多 worker，无热重载
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
