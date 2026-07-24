# 文辉小说 - 前端项目文档

## 项目简介

文辉小说前端是一个基于 Vue 3 的单页应用，提供用户友好的小说创作、阅读和社交互动界面。采用现代化的前端技术栈，支持响应式设计，提供流畅的用户体验。

## 技术栈

### 核心框架
- **Vue 3** 3.4.0 - 渐进式 JavaScript 框架
- **Vue Router** 4.2.5 - 官方路由管理器
- **Pinia** - 状态管理
- **Vite** 5.0.0 - 前端构建工具

### HTTP 客户端
- **Axios** 1.6.2 - HTTP 请求库

### 功能组件
- **QRCode** 1.5.4 - 二维码生成库（VIP 支付）

### 开发工具
- **@vitejs/plugin-vue** 4.5.2 - Vue 3 Vite 插件

## 项目结构

```
frontend/
├── public/                   # 静态资源
├── src/                      # 源代码目录
│   ├── api/                  # API 接口封装
│   │   └── index.js         # Axios 配置和接口定义
│   ├── assets/               # 静态资源（图片等）
│   ├── components/           # 可复用组件
│   ├── router/               # 路由配置
│   │   └── index.js         # 路由定义
│   ├── stores/               # 状态管理（Pinia）
│   │   ├── user.js          # 用户状态
│   │   └── themeStore.js    # 主题状态
│   ├── views/                # 页面组件（共 12 个）
│   │   ├── Home.vue         # 首页
│   │   ├── Login.vue        # 登录页
│   │   ├── Register.vue     # 注册页
│   │   ├── Creation.vue     # 创作中心
│   │   ├── Reader.vue       # 阅读器
│   │   ├── Bookshelf.vue    # 书架
│   │   ├── WorkCircle.vue   # 作品圈
│   │   ├── VIP.vue          # VIP 会员
│   │   ├── Settings.vue     # 系统设置
│   │   ├── MyProfile.vue    # 个人中心
│   │   ├── BookManage.vue   # 作品管理
│   │   └── WorkList.vue     # 作品列表
│   ├── App.vue              # 根组件
│   ├── main.js              # 应用入口
│   └── theme.css            # 全局样式
├── index.html                # HTML 模板
├── package.json              # 项目配置
├── vite.config.js            # Vite 配置
├── Dockerfile                # Docker 构建文件（多阶段构建）
├── nginx.conf                # Nginx 部署配置
└── dist/                     # 构建输出目录
```

## 核心功能

### 1. 首页 (`views/Home.vue`)
- 小说列表展示
- 推荐小说
- 分类浏览
- 搜索功能

### 2. 用户认证
- **登录页** (`views/Login.vue`) - 用户名/密码登录，JWT Token 存储
- **注册页** (`views/Register.vue`) - 邮箱验证码注册

### 3. 小说创作 (`views/Creation.vue`)
- 小说信息编辑
- 章节管理
- AI 辅助创作（DeepSeek）
- 实时保存

### 4. 阅读器 (`views/Reader.vue`)
- 章节阅读
- 章节导航
- 阅读进度保存
- 字体大小调整
- 夜间模式

### 5. 书架 (`views/Bookshelf.vue`)
- 收藏作品展示
- 阅读进度
- 分类管理

### 6. 作品圈 (`views/WorkCircle.vue`)
- 作品动态展示
- 点赞、评论互动
- 可控开关（通过 `show_all_works` 配置）

### 7. VIP 会员 (`views/VIP.vue`)
- 套餐展示（月度/季度/年度）
- 支付宝支付集成
- VIP 状态显示

### 8. 系统设置 (`views/Settings.vue`)
- 主题色调切换
- VIP 会员信息展示（等级、到期时间）
- 视觉效果控制

### 9. 个人中心 (`views/MyProfile.vue`)
- 用户信息展示
- VIP 状态
- AI 生成配额

## 路由配置

```javascript
const routes = [
  { path: '/', component: Home },                              // 首页
  { path: '/login', component: Login },                        // 登录
  { path: '/register', component: Register },                  // 注册
  { path: '/bookshelf', component: Bookshelf },                // 书架
  { path: '/circle', component: WorkCircle },                  // 作品圈
  { path: '/creation', component: Creation },                  // 创作中心
  { path: '/reader/:novel_unique_id', component: Reader },     // 阅读
  { path: '/reader/:novel_unique_id/:chapter_unique_id', component: Reader }, // 章节阅读
  { path: '/vip', component: VIP },                            // VIP 会员
  { path: '/settings', component: Settings },                  // 设置
  { path: '/my-profile', component: MyProfile },               // 个人中心
  { path: '/books/:novel_unique_id/manage', component: BookManage }, // 作品管理
  { path: '/works/:username', component: WorkList },           // 作品列表
]
```

> 未登录时，导航栏的首页、作品圈、书架、开通会员、创作中心等菜单项自动隐藏。

## 样式系统

### 全局样式 (`src/theme.css`)
- CSS 变量定义
- 全局重置样式
- 通用组件样式
- 响应式布局

### 设计特点
- 暗色主题为主
- 多色主题切换（浅色/深色/蓝色/紫色/绿色）
- 渐变色和毛玻璃效果
- 流畅的动画过渡
- 移动端适配

## 构建和运行

### 环境要求
- Node.js 16+
- npm

### 安装依赖
```bash
npm install
```

### 开发模式
```bash
npm run dev
```
访问：http://localhost:3000

### 生产构建
```bash
npm run build
```
构建产物输出到 `dist/` 目录

## Docker 部署

### 构建镜像
```bash
docker build -t wenhui_novel-frontend .
```

### 运行容器
```bash
docker run -d -p 80:80 --name wenhui-frontend wenhui_novel-frontend
```

### Docker Compose（推荐）
```bash
# 在项目根目录执行
docker-compose up -d frontend
```

## Nginx 配置

生产环境使用 Nginx 反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 功能特性

- 响应式设计（桌面端 + 移动端）
- 多主题切换（6 种配色）
- 路由懒加载
- 高性能构建（gzip 压缩）
- Token 认证，登录状态持久化
- 登录态控制导航栏可见性

## 浏览器兼容性

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+
