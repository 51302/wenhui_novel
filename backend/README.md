# 文辉小说 - 后端项目文档

## 项目简介

文辉小说是一个基于 AI 的小说创作平台，后端采用 FastAPI 框架构建，提供用户认证、小说创作、章节生成、社交互动、VIP 会员等核心功能。使用 Docker Compose 编排部署。

## 技术栈

### 核心框架
- **FastAPI** 0.104.1 - 现代化的 Python Web 框架
- **Uvicorn** 0.24.0 - ASGI 服务器
- **SQLAlchemy** 2.0.23 - ORM 框架
- **PyMySQL** 1.1.0 - MySQL 数据库驱动

### 数据存储
- **MySQL** 8.0 - 关系型数据库（用户、小说、订单等数据）
- **Redis** 7-alpine - 缓存和会话管理（含记忆体存储）
- **Elasticsearch** 8.11.0 - 全文搜索引擎
- **SeaweedFS** - 分布式文件存储

### 安全与认证
- **PyJWT** 2.8.0 - JWT token 生成和验证
- **Bcrypt** 4.0.1 - 密码加密
- **Cryptography** 41.0.7 - 加密库（支付宝签名）

### AI 与数据处理
- **HTTPX** 0.25.2 - 异步 HTTP 客户端（调用 DeepSeek API）
- **NumPy** 1.26.4 - 数值计算

### 其他依赖
- **PyYAML** 6.0.1 - 配置文件解析
- **Pydantic** 2.5.2 - 数据验证
- **Requests** 2.31.0 - HTTP 请求库
- **Python-multipart** 0.0.6 - 文件上传支持

## 项目结构

```
backend/
├── app/                         # 应用主目录
│   ├── api/                     # API 路由层
│   │   ├── auth.py             # 用户认证（登录、注册、邮箱验证码）
│   │   ├── novels.py           # 小说管理（CRUD + 搜索）
│   │   ├── chapters.py         # 章节管理（AI 生成、手动创建）
│   │   ├── interactions.py     # 社交互动（点赞、评论、关注、收藏）
│   │   ├── upload.py           # 文件上传（SeaweedFS + 本地）
│   │   ├── bookshelf.py        # 书架管理
│   │   ├── vip.py              # VIP 会员系统（支付宝支付）
│   │   ├── config.py           # 公开配置接口
│   │   └── deps.py             # 依赖注入（JWT 认证解析）
│   ├── dao/                     # 数据访问层
│   │   ├── user_dao.py         # 用户数据操作
│   │   ├── novel_dao.py        # 小说数据操作
│   │   ├── chapter_dao.py      # 章节数据操作
│   │   ├── interaction_dao.py  # 互动数据操作
│   │   ├── bookshelf_dao.py    # 书架数据操作
│   │   └── vip_order_dao.py    # VIP 订单数据操作
│   ├── models/                  # SQLAlchemy 数据模型
│   │   ├── user.py             # 用户模型（含 vip_level）
│   │   ├── novel.py            # 小说模型
│   │   ├── chapter.py          # 章节模型
│   │   ├── interaction.py      # 互动模型
│   │   ├── bookshelf.py        # 书架模型
│   │   └── vip_order.py        # VIP 订单模型
│   ├── service/                 # 业务逻辑层
│   │   ├── auth_service.py     # 认证业务
│   │   ├── novel_service.py    # 小说业务
│   │   ├── chapter_service.py  # 章节业务
│   │   ├── interaction_service.py # 互动业务
│   │   ├── bookshelf_service.py # 书架业务
│   │   ├── alipay_service.py   # 支付宝支付服务
│   │   └── es_service.py       # Elasticsearch 搜索服务
│   ├── prompts/                 # AI 提示词模板
│   │   └── chapter_prompts.py  # 章节生成提示词
│   ├── conf/                    # 配置文件
│   │   └── config.yaml         # 主配置文件
│   ├── utils/                   # 工具函数
│   │   ├── response.py         # 统一响应格式
│   │   ├── logger.py           # 日志配置
│   │   ├── redis_cache.py      # Redis 缓存工具
│   │   ├── seaweedfs_client.py # SeaweedFS 客户端
│   │   └── chroma_client.py    # ChromaDB 客户端
│   ├── sql/                     # SQL 脚本
│   │   └── init.sql            # 数据库初始化脚本
│   ├── application/             # 应用基础设施
│   │   └── jwt_handler.py      # JWT Token 处理
│   ├── config.py                # 应用配置加载
│   └── main.py                 # 应用入口
├── requirements.txt             # Python 依赖
├── Dockerfile                   # Docker 构建文件
└── logs/                        # 日志文件（挂载到宿主机 data/backend/logs）
```

## 核心功能

### 1. 用户认证系统 (`api/auth.py`)
- 邮箱验证码注册（Resend 邮件服务）
- 用户登录（JWT Token，30 天有效期）
- VIP 等级权限控制（0=免费, 1=VIP, 2=SVIP）

### 2. 小说管理系统 (`api/novels.py`)
- 创建/编辑/删除小说
- 小说列表查询（分页 + 分类筛选）
- ES 全文搜索

### 3. 章节管理系统 (`api/chapters.py`)
- 手动创建章节
- **AI 生成章节**（调用 DeepSeek API）
- 草稿管理、发布、编辑

### 4. 社交互动系统 (`api/interactions.py`)
- 点赞、评论、关注、收藏
- 互动动态流（时间线）

### 5. 书架系统 (`api/bookshelf.py`)
- 收藏/取消收藏作品
- 书架列表查询
- VIP 阅读配额控制

### 6. VIP 会员系统 (`api/vip.py`)
- 套餐管理（月度 ¥59 / 季度 ¥149 / 年度 ¥499）
- 支付宝支付集成（正式环境）
- 支付回调处理（异步通知 + 前端确认）
- VIP 状态查询

### 7. 配置接口 (`api/config.py`)
- 公开配置查询（如 `show_all_works`）

## 数据模型

### 用户 (`models/user.py`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| username | varchar(64) | 用户名（唯一） |
| password | varchar(256) | bcrypt 加密密码 |
| email | varchar(128) | 邮箱 |
| vip_level | tinyint | 0=免费, 1=VIP, 2=SVIP |
| vip_expire_at | datetime | VIP 过期时间 |
| free_generate_quota | int | AI 生成每日配额 |
| quota_date | date | 配额日期（跨天重置） |

## 安装和运行

### 开发模式
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Compose 一键部署（推荐）
```bash
# 在项目根目录执行，自动构建镜像并启动所有服务
docker compose up -d

# 仅重启单个服务（如修改代码后）
docker compose up -d frontend   # 重启前端
docker compose up -d backend    # 重启后端
```

### 手动构建镜像

#### 后端镜像
```bash
cd backend
docker build -t wenhui_novel-backend .
```

#### 前端镜像
```bash
cd frontend
docker build -t wenhui_novel-frontend .
```

#### 构建并推送至阿里云镜像仓库（用于生产环境）
```bash
# 1. 登录阿里云镜像仓库
docker login --username=你的用户名 crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com

# 2. 构建并打标签
docker tag wenhui_novel-backend crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-backend:v1.1.0
docker tag wenhui_novel-frontend crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-frontend:v1.1.0

# 3. 推送
docker push crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-backend:v1.1.0
docker push crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-frontend:v1.1.0
```

### 完整部署流程（从代码到上线）

```bash
# 1. 修改代码后，重新构建镜像
docker compose build frontend
docker compose build backend

# 2. 重新创建并启动容器
docker compose up -d

# 3. 查看启动日志
docker compose logs -f backend    # 监控后端启动日志
docker compose logs -f frontend   # 监控前端启动日志

# 4. 重启内网穿透（如更换域名或隧道失效）
docker rm -f wenhui-natapp
docker compose up -d natapp

# 5. 验证服务
curl http://localhost           # 前端 → 应返回 200
curl http://localhost:8000/api/config/public  # 后端 → 应返回 200
```

## 配置说明

主配置文件：`app/conf/config.yaml`（Docker 部署时通过 `-v` 挂载到容器）

### 配置项概览
| 模块 | 关键配置 |
|------|----------|
| app | `website_url`、`show_all_works` |
| database | MySQL 连接信息 |
| redis | Redis 连接信息 |
| es | Elasticsearch 连接信息 |
| email | Resend API Key、发件地址 |
| alipay | app_id、密钥、回调地址、套餐价格 |
| deepseek | API Key、Base URL |

## API 文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Docker Compose 服务

| 服务 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| backend | wenhui_novel-backend | 8000 | FastAPI 应用 |
| frontend | wenhui_novel-frontend | 80 | Nginx 静态文件 |
| mysql | mysql:8.0 | 3306 | 数据库 |
| redis | redis:7-alpine | 6379 | 缓存 |
| elasticsearch | elasticsearch:8.11.0 | 9200 | 全文搜索 |
| seaweedfs | chrislusf/seaweedfs | 9333/8080/8888 | 文件存储 |
| natapp | natapp/natapp | - | 内网穿透 |

### 数据持久化

所有数据挂载到项目根目录的 `data/` 下：
```
data/
├── mysql/                 # MySQL 数据文件
├── redis/                 # Redis 数据
├── es/                    # ES 索引数据
├── seaweedfs/            # 文件存储数据
│   ├── master/
│   ├── volume/
│   └── filer/
├── backend/
│   ├── novel_structure_data/  # 小说结构文本文件
│   └── logs/                  # 后端日志
└── frontend/
    ├── uploads/          # 上传文件
    └── covers/           # 封面图片
```

## 注意事项

1. **配置安全**：生产环境请修改默认密码和密钥
2. **数据库备份**：`data/mysql/` 定期备份
3. **日志监控**：`data/backend/logs/` 关注应用日志
4. **支付回调**：确保支付宝回调地址（`wenhui.nat100.top`）可公网访问
5. **Natapp 隧道**：重启前先执行 `docker rm -f wenhui-natapp`
