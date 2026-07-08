# 文辉小说 - 后端项目文档

## 项目简介

文辉小说是一个基于AI的小说创作平台，后端采用 FastAPI 框架构建，提供用户认证、小说创作、章节生成、社交互动、VIP会员等核心功能。

## 技术栈

### 核心框架
- **FastAPI** 0.104.1 - 现代化的 Python Web 框架
- **Uvicorn** 0.24.0 - ASGI 服务器
- **SQLAlchemy** 2.0.23 - ORM 框架
- **PyMySQL** 1.1.0 - MySQL 数据库驱动

### 数据存储
- **MySQL** - 关系型数据库（用户、小说、订单等数据）
- **Redis** 5.0.1 - 缓存和会话管理
- **Elasticsearch** 8.11.1 - 全文搜索引擎
- **ChromaDB** 0.4.18 - 向量数据库（AI模型相关）

### 安全与认证
- **PyJWT** 2.8.0 - JWT token 生成和验证
- **Bcrypt** 4.0.1 - 密码加密
- **Cryptography** 41.0.7 - 加密库（支付宝签名）

### AI 与数据处理
- **NumPy** 1.26.4 - 数值计算
- **ONNX Runtime** 1.16.3 - AI 模型推理
- **ChromaDB** 0.4.18 - 向量存储和检索

### 其他依赖
- **PyYAML** 6.0.1 - 配置文件解析
- **Pydantic** 2.5.2 - 数据验证
- **HTTPX** 0.25.2 - 异步 HTTP 客户端
- **Requests** 2.31.0 - HTTP 请求库
- **Python-multipart** 0.0.6 - 文件上传支持

## 项目结构

```
backend/
├── app/                      # 应用主目录
│   ├── api/                  # API 路由层
│   │   ├── auth.py          # 用户认证（登录、注册）
│   │   ├── novels.py        # 小说管理
│   │   ├── chapters.py      # 章节管理
│   │   ├── interactions.py  # 社交互动（点赞、评论）
│   │   ├── upload.py        # 文件上传
│   │   ├── vip.py           # VIP 会员系统
│   │   └── deps.py          # 依赖注入（认证等）
│   ├── dao/                  # 数据访问层
│   │   ├── user_dao.py      # 用户数据操作
│   │   ├── novel_dao.py     # 小说数据操作
│   │   ├── chapter_dao.py   # 章节数据操作
│   │   ├── interaction_dao.py # 互动数据操作
│   │   └── vip_order_dao.py # VIP订单数据操作
│   ├── models/               # 数据模型
│   │   ├── user.py          # 用户模型
│   │   ├── novel.py         # 小说模型
│   │   ├── chapter.py       # 章节模型
│   │   ├── interaction.py   # 互动模型
│   │   └── vip_order.py     # VIP订单模型
│   ├── service/              # 业务逻辑层
│   │   ├── novel_service.py # 小说业务逻辑
│   │   ├── alipay_service.py # 支付宝支付服务
│   │   └── ...
│   ├── conf/                 # 配置文件
│   │   └── config.yaml      # 主配置文件
│   ├── utils/                # 工具函数
│   │   ├── response.py      # 统一响应格式
│   │   └── ...
│   ├── sql/                  # SQL 脚本
│   │   └── init.sql         # 数据库初始化脚本
│   └── main.py              # 应用入口
├── requirements.txt          # Python 依赖
├── Dockerfile               # Docker 构建文件
└── create_super_admin.py    # 创建超级管理员脚本
```

## 核心功能模块

### 1. 用户认证系统 (`app/api/auth.py`)
- 用户注册
- 用户登录（JWT Token）
- 密码加密存储
- 超级管理员创建

### 2. 小说管理系统 (`app/api/novels.py`)
- 创建小说
- 查询小说列表
- 小说详情查询
- 小说编辑和删除

### 3. 章节管理系统 (`app/api/chapters.py`)
- 创建章节
- AI 生成章节内容
- 章节列表查询
- 章节详情和编辑

### 4. 社交互动系统 (`app/api/interactions.py`)
- 点赞功能
- 评论功能
- 收藏功能
- 互动数据统计

### 5. 文件上传系统 (`app/api/upload.py`)
- 图片上传
- 文件存储管理
- 上传文件验证

### 6. VIP 会员系统 (`app/api/vip.py`)
- VIP 套餐管理（月度、季度、年度）
- 订单创建
- 支付宝支付集成（沙箱/正式环境）
- 支付回调处理
- VIP 状态查询
- 会员到期时间管理

## 配置说明

主配置文件：`app/conf/config.yaml`

### 数据库配置
```yaml
database:
  host: "localhost"
  port: 3306
  user: "root"
  password: "your_password"
  database: "wenhui_novel"
```

### Redis 配置
```yaml
redis:
  host: "localhost"
  port: 6379
  db: 0
```

### 支付宝配置
```yaml
alipay:
  # 沙箱环境
  app_id: "your_sandbox_app_id"
  app_private_key: "your_private_key"
  alipay_public_key: "alipay_public_key"
  
  # 回调地址
  notify_url: "http://your-domain.com/api/vip/notify"
  return_url: "http://your-domain.com/vip"
  
  # VIP 套餐配置
  plans:
    monthly:
      name: "月度会员"
      price: "59.00"
      days: 30
```

## 安装和运行

### 环境要求
- Python 3.8+
- MySQL 5.7+
- Redis 5.0+
- Elasticsearch 8.x

### 安装依赖
```bash
pip install -r requirements.txt
```

### 数据库初始化
```bash
# 执行初始化脚本
mysql -u root -p < app/sql/init.sql
```

### 创建超级管理员
```bash
python create_super_admin.py
```

### 启动服务
```bash
# 开发模式（自动重载）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 生产模式
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API 文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 支付模式说明

### Demo 模式（开发调试）
- 不需要配置支付宝密钥
- 本地模拟支付流程
- 点击"确认支付"直接模拟支付成功

### 沙箱模式（测试环境）
- 需要配置支付宝沙箱密钥
- 跳转到支付宝沙箱网关
- 使用沙箱账号扫码支付
- 更接近真实支付流程

### 正式模式（生产环境）
- 配置正式环境支付宝密钥
- 真实的支付流程
- 需要支付宝开放平台审核

## Docker 部署

### 构建镜像
```bash
docker build -t wenhui-novel-backend .
```

### 运行容器
```bash
docker run -d -p 8000:8000 --name wenhui-backend wenhui-novel-backend
```

### Docker Compose
```bash
docker-compose up -d
```

## 注意事项

1. **配置安全**：生产环境请修改默认密码和密钥
2. **数据库备份**：定期备份数据库数据
3. **日志监控**：关注应用日志，及时发现异常
4. **支付安全**：确保支付宝回调地址可公网访问
5. **AI 模型**：确保 ONNX 模型文件正确部署

## 开发规范

### 代码风格
- 遵循 PEP 8 规范
- 使用类型注解
- 编写函数和类的文档字符串

### API 设计
- RESTful 风格
- 统一的响应格式
- 合理的 HTTP 状态码
- 完善的错误处理

### 数据验证
- 使用 Pydantic 进行请求验证
- 数据库操作使用 ORM
- 防止 SQL 注入

## 常见问题

### 1. 数据库连接失败
检查 MySQL 服务是否启动，配置文件中的数据库信息是否正确。

### 2. Redis 连接失败
检查 Redis 服务是否启动，配置文件中的 Redis 信息是否正确。

### 3. 支付回调失败
确保回调地址可公网访问，检查支付宝配置是否正确。

### 4. AI 模型加载失败
确保 ONNX 模型文件存在，路径配置正确。

## 联系方式

如有问题，请联系开发团队。
