# ============================================================
#  文辉小说 前端镜像（多阶段构建）
#  阶段1: node 构建 dist
#  阶段2: nginx 服务静态文件 + 反向代理 API
# ============================================================

# ---- 阶段1: 构建前端 ----
FROM node:18-alpine AS builder

WORKDIR /app

# 先拷 package.json 利用缓存层
COPY package.json package-lock.json* ./

# 安装依赖
RUN npm config set registry https://registry.npmmirror.com && npm install

# 拷源码并构建
COPY . .
RUN npm run build

# ---- 阶段2: nginx 部署 ----
FROM nginx:alpine

# 拷贝构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 拷贝 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
