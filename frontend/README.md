# 文辉小说 - 前端项目文档

## 项目简介

文辉小说前端是一个基于 Vue 3 的单页应用，提供用户友好的小说创作、阅读和社交互动界面。采用现代化的前端技术栈，支持响应式设计，提供流畅的用户体验。

## 技术栈

### 核心框架
- **Vue 3** 3.4.0 - 渐进式 JavaScript 框架
- **Vue Router** 4.2.5 - 官方路由管理器
- **Vite** 5.0.0 - 下一代前端构建工具

### HTTP 客户端
- **Axios** 1.6.2 - HTTP 请求库

### 功能组件
- **QRCode** 1.5.4 - 二维码生成库（VIP支付）

### 开发工具
- **@vitejs/plugin-vue** 4.5.2 - Vue 3 Vite 插件

## 项目结构

```
frontend/
├── public/                  # 静态资源
├── src/                     # 源代码目录
│   ├── api/                # API 接口封装
│   │   └── index.js       # Axios 配置和接口定义
│   ├── assets/             # 静态资源（图片、样式等）
│   ├── components/         # 可复用组件
│   ├── router/             # 路由配置
│   │   └── index.js       # 路由定义
│   ├── stores/             # 状态管理
│   ├── views/              # 页面组件
│   │   ├── Home.vue       # 首页
│   │   ├── Login.vue      # 登录页
│   │   ├── Register.vue   # 注册页
│   │   ├── Creation.vue   # 创作页
│   │   ├── Reader.vue     # 阅读页
│   │   ├── WorkCircle.vue # 作品圈
│   │   ├── VIP.vue        # VIP会员页
│   │   └── Settings.vue   # 设置页
│   ├── App.vue            # 根组件
│   ├── main.js            # 应用入口
│   └── theme.css          # 全局样式
├── index.html              # HTML 模板
├── package.json            # 项目配置
├── vite.config.js          # Vite 配置
└── dist/                   # 构建输出目录
```

## 核心功能模块

### 1. 首页 (`views/Home.vue`)
- 小说列表展示
- 推荐小说
- 分类浏览
- 搜索功能

### 2. 用户认证
- **登录页** (`views/Login.vue`)
  - 用户名/密码登录
  - JWT Token 存储
  - 登录状态保持
  
- **注册页** (`views/Register.vue`)
  - 用户注册
  - 密码强度验证
  - 注册成功跳转

### 3. 小说创作 (`views/Creation.vue`)
- 小说信息编辑
- 章节管理
- AI 辅助创作
- 实时保存
- 富文本编辑

### 4. 阅读器 (`views/Reader.vue`)
- 章节阅读
- 章节导航
- 阅读进度保存
- 字体大小调整
- 夜间模式

### 5. 作品圈 (`views/WorkCircle.vue`)
- 作品展示
- 点赞功能
- 评论互动
- 收藏功能
- 用户关注

### 6. VIP 会员 (`views/VIP.vue`)
- VIP 套餐展示
- 支付宝扫码支付
- 订单状态查询
- 支付结果确认
- VIP 状态显示

### 7. 用户设置 (`views/Settings.vue`)
- 个人信息编辑
- 密码修改
- 账号安全
- 偏好设置

## 路由配置

```javascript
const routes = [
  { path: '/', component: Home },                          // 首页
  { path: '/login', component: Login },                    // 登录
  { path: '/register', component: Register },             // 注册
  { path: '/circle', component: WorkCircle },              // 作品圈
  { path: '/creation', component: Creation },              // 创作中心
  { path: '/reader/:novel_unique_id', component: Reader }, // 小说阅读
  { path: '/reader/:novel_unique_id/:chapter_unique_id', component: Reader }, // 章节阅读
  { path: '/vip', component: VIP },                        // VIP会员
  { path: '/settings', component: Settings },              // 设置
]
```

## API 接口封装

### Axios 配置 (`src/api/index.js`)
```javascript
import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器 - 添加 Token
api.interceptors.request.use(config => {
  const token = localStorage.getItem('novel_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器 - 统一错误处理
api.interceptors.response.use(
  response => response.data,
  error => {
    // 错误处理逻辑
    return Promise.reject(error)
  }
)
```

### 主要接口
- `POST /api/auth/login` - 用户登录
- `POST /api/auth/register` - 用户注册
- `GET /api/novels` - 获取小说列表
- `POST /api/novels` - 创建小说
- `GET /api/chapters` - 获取章节列表
- `POST /api/chapters` - 创建章节
- `POST /api/vip/create-order` - 创建VIP订单
- `GET /api/vip/status` - 查询VIP状态

## 样式系统

### 全局样式 (`src/theme.css`)
- CSS 变量定义
- 全局重置样式
- 通用组件样式
- 响应式布局

### 设计特点
- 暗色主题为主
- 渐变色和毛玻璃效果
- 流畅的动画过渡
- 移动端适配

## 开发配置

### Vite 配置 (`vite.config.js`)
```javascript
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    host: '127.0.0.1',
    allowedHosts: ['your-domain.com'], // 允许的域名
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
```

### 代理配置
开发环境下，API 请求通过 Vite 代理转发到后端服务器，避免跨域问题。

## 安装和运行

### 环境要求
- Node.js 16+
- npm 或 yarn

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

### 预览构建
```bash
npm run preview
```

## 部署

### 静态部署
将 `dist/` 目录部署到任何静态服务器：
- Nginx
- Apache
- Vercel
- Netlify

### Nginx 配置示例
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    root /path/to/dist;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 功能特性

### 1. 响应式设计
- 支持桌面端和移动端
- 自适应布局
- 触摸友好

### 2. 性能优化
- 路由懒加载
- 组件按需加载
- 图片懒加载
- 代码分割

### 3. 用户体验
- 加载状态提示
- 错误提示
- 操作确认
- 平滑过渡动画

### 4. 安全性
- Token 认证
- XSS 防护
- CSRF 防护
- 敏感信息加密

## 开发规范

### 代码风格
- 使用 ESLint 进行代码检查
- 组件命名采用 PascalCase
- 文件命名采用 kebab-case
- 使用语义化的 HTML 标签

### 组件开发
- 单一职责原则
- Props 验证
- 事件命名规范
- 样式隔离（scoped）

### 状态管理
- 合理使用响应式数据
- 避免不必要的重渲染
- 使用 computed 优化计算属性
- 使用 watch 监听数据变化

## 常见问题

### 1. 跨域问题
开发环境使用 Vite 代理解决，生产环境需要配置服务器反向代理。

### 2. Token 过期
Token 过期后自动跳转到登录页，需要重新登录。

### 3. 二维码生成失败
确保 qrcode 库正确安装，检查网络连接。

### 4. 样式不生效
检查样式作用域，确认 CSS 选择器优先级。

## 浏览器兼容性

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## 性能指标

- 首屏加载时间 < 2s
- 交互响应时间 < 100ms
- 页面大小 < 500KB (gzip)

## 后续优化

- [ ] 添加单元测试
- [ ] 添加 E2E 测试
- [ ] 优化图片资源
- [ ] 添加 PWA 支持
- [ ] 国际化支持
- [ ] 主题切换功能

## 联系方式

如有问题，请联系开发团队。
