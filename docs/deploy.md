# 文辉小说 - 部署文档

> 版本：v1.1.0 | 基础环境：Docker + Docker Compose

---

## 环境要求

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Docker | 24.0+ | 容器运行时 |
| Docker Compose | 2.20+ | 服务编排 |
| Git | 可选 | 代码版本管理 |

---

## 项目结构

```
wenhui_novel/
├── backend/                    # 后端源码
│   ├── app/                    # FastAPI 应用
│   ├── Dockerfile              # 后端镜像构建
│   └── requirements.txt        # Python 依赖
├── frontend/                   # 前端源码
│   ├── src/                    # Vue 3 源码
│   ├── Dockerfile              # 前端镜像构建（Nginx 运行）
│   └── nginx.conf              # Nginx 配置
├── docker-compose.yml          # 服务编排文件
├── .env                        # 环境变量（DEEPSEEK_API_KEY）
└── data/                       # 数据持久化目录（自动创建）
    ├── mysql/
    ├── redis/
    ├── es/
    ├── seaweedfs/
    ├── backend/
    │   ├── novel_structure_data/
    │   └── logs/
    └── frontend/
        ├── uploads/
        └── covers/
```

---

## 一键部署

```bash
# 1. 克隆代码
git clone <仓库地址> wenhui_novel
cd wenhui_novel

# 2. 配置环境变量（DeepSeek API Key）
echo "DEEPSEEK_API_KEY=sk-xxxxx" > .env

# 3. 一键启动所有服务（构建镜像 + 启动容器）
docker compose up -d

# 4. 验证服务
curl http://localhost                   # 前端，应返回 200
curl http://localhost:8000/api/config/public  # 后端，应返回 200
```

首次启动会自动构建前后端镜像，包含所有依赖安装，耗时约 2-5 分钟。

---

## 手动构建镜像

### 后端镜像

```bash
cd backend
docker build -t wenhui_novel-backend .
```

构建过程：
1. 基于 `python:3.11-slim`
2. 安装系统依赖（gcc、mariadb-dev 等）
3. 安装 Python 依赖（约 40+ 个包）
4. 复制应用代码

### 前端镜像

```bash
cd frontend
docker build -t wenhui_novel-frontend .
```

构建过程：
1. 第一阶段：基于 `node:18-alpine`，安装依赖并执行 `vite build`
2. 第二阶段：基于 `nginx:alpine`，复制构建产物和 Nginx 配置

---

## 推送至阿里云镜像仓库

```bash
# 1. 登录
docker login --username=你的阿里云用户名 crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com

# 2. 打标签
docker tag wenhui_novel-backend crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-backend:v1.1.0
docker tag wenhui_novel-frontend crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-frontend:v1.1.0

# 3. 推送
docker push crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-backend:v1.1.0
docker push crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-frontend:v1.1.0
```

推送完成后，修改 `docker-compose.yml`，将 `build` 替换为 `image` 即可跳过构建直接拉取镜像。

---

## 重新部署

```bash
# 1. 重新构建镜像
docker compose build frontend   # 仅前端
docker compose build backend    # 仅后端
docker compose build            # 全部

# 2. 重启服务
docker compose up -d

# 3. 查看日志
docker compose logs -f backend
docker compose logs -f frontend

# 4. 重启内网穿透（地址变更时）
docker rm -f wenhui-natapp
docker compose up -d natapp
```

---

## 数据持久化

所有重要数据挂载到 `data/` 目录：

| 数据 | 宿主机路径 | 容器路径 |
|------|-----------|----------|
| MySQL | `data/mysql/` | `/var/lib/mysql` |
| Redis | `data/redis/` | `/data` |
| ES | `data/es/` | `/usr/share/elasticsearch/data` |
| SeaweedFS | `data/seaweedfs/` | `/data` |
| 小说文本 | `data/backend/novel_structure_data/` | `/app/app/novel_structure_data` |
| 后端日志 | `data/backend/logs/` | `/app/app/logs` |
| 上传文件 | `data/frontend/uploads/` | `/usr/share/nginx/html/uploads` |
| 封面图片 | `data/frontend/covers/` | `/usr/share/nginx/html/covers` |

删除容器不会丢失数据，如需彻底清理请手动删除 `data/` 目录。

---

## 服务清单

| 服务 | 内部地址 | 对外端口 | 健康检查 |
|------|----------|----------|----------|
| MySQL | `mysql:3306` | `3306` | 是 |
| Redis | `redis:6379` | `6379` | 是 |
| ES | `http://elasticsearch:9200` | `9200` | 是 |
| SeaweedFS Master | `seaweedfs-master:9333` | `9333` | - |
| SeaweedFS Volume | `seaweedfs-volume:8080` | `8080` | - |
| SeaweedFS Filer | `seaweedfs-filer:8888` | `8888` | 是 |
| Backend | `backend:8000` | `8000` | - |
| Frontend | - | `80` | - |
| Natapp | - | - | - |

---

## 常见问题

### 1. 端口冲突

```bash
# 检查端口占用
netstat -ano | findstr ":80"
netstat -ano | findstr ":8000"
netstat -ano | findstr ":3306"

# 或修改 docker-compose.yml 中的 ports 映射
```

### 2. DeepSeek API Key 未配置

```bash
# 在 .env 文件中配置
DEEPSEEK_API_KEY=sk-your-key-here

# 然后重启后端
docker compose up -d backend
```

### 3. Natapp 隧道失效

```bash
docker rm -f wenhui-natapp
docker compose up -d natapp
docker compose logs -f natapp  # 查看分配的域名
```

### 4. 后端容器启动失败（MySQL 连接超时）

MySQL 首次启动需要 20-30 秒初始化，后端会自动重试。如持续失败：

```bash
docker compose logs backend  # 查看具体错误
docker compose restart backend
```
