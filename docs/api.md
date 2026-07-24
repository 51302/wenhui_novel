# 文辉小说 API 接入文档

> 版本：v1.1.0 | 基础地址：`http://127.0.0.1:8000` | Swagger 文档：`/api/docs`

---

## 通用说明

### 响应格式

所有接口统一返回 JSON：

```json
{
  "状态码": 200,
  "消息": "操作成功",
  "数据": { ... }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| 状态码 | int | 200=成功，4xx=客户端错误，5xx=服务端错误 |
| 消息 | string | 友好的提示信息 |
| 数据 | any | 业务数据，失败时为 `null` |

### 认证方式

需要登录的接口，提供 **二选一** 的认证方式：

| 方式 | 说明 |
|------|------|
| Cookie | 登录/注册成功后自动设置 `novel_token` Cookie（httpOnly，30天），浏览器自动携带 |
| Header | 请求头 `Authorization: Bearer <jwt_token>` |

> 需要 VIP 权限的接口根据用户 `vip_level` 判定：0=免费用户，1=VIP，2=SVIP。

---

## 一、认证模块 `/api/auth`

### 1.1 用户注册

```
POST /api/auth/register
```

**请求体**
```json
{
  "username": "string (必填)",
  "password": "string (必填, ≥8位)",
  "email": "string (必填, 有效邮箱格式)",
  "phone": "string (选填, 11位数字)",
  "email_code": "string (必填, 邮箱验证码)"
}
```

**响应**
```json
{
  "状态码": 200,
  "消息": "注册成功",
  "数据": {
    "user_id": 1,
    "username": "testuser",
    "is_vip": false,
    "is_svip": false,
    "vip_level": 0,
    "token": "eyJhbG..."
  }
}
```

---

### 1.2 用户登录

```
POST /api/auth/login
```

**请求体**
```json
{
  "username": "string (必填)",
  "password": "string (必填)"
}
```

**响应**
```json
{
  "状态码": 200,
  "消息": "登录成功",
  "数据": {
    "user_id": 1,
    "username": "testuser",
    "is_vip": true,
    "is_svip": false,
    "vip_level": 1,
    "token": "eyJhbG..."
  }
}
```

---

### 1.3 发送邮箱验证码

```
POST /api/auth/send-email-code
```

**请求体**
```json
{
  "target": "user@example.com"
}
```

**响应**
```json
{
  "状态码": 200,
  "消息": "验证码已发送至您的邮箱，请查收"
}
```

> 验证码 5 分钟有效。通过 Resend 发送，发件地址为 `noreply@wenhui.xyz`。

---

### 1.4 退出登录

```
POST /api/auth/logout
```

**响应**
```json
{
  "状态码": 200,
  "消息": "已退出登录",
  "数据": null
}
```

---

### 1.5 获取当前用户信息 🔒

```
GET /api/auth/me
```

**响应**
```json
{
  "状态码": 200,
  "消息": "已登录",
  "数据": {
    "user_id": 1,
    "username": "testuser",
    "vip_level": 1,
    "is_vip": true,
    "is_svip": false,
    "vip_expire_at": "2026-08-23 12:00:00",
    "free_generate_quota": 10
  }
}
```

---

## 二、作品模块 `/api/novels`

### 2.1 创建作品 🔒

```
POST /api/novels/create
```

**请求体** (multipart/form-data 或 JSON)
```
title: string (必填)
target_reader: string (必填, "男频" 或 "女频")
description: string (选填)
story_background: string (选填)
world_setting: string (选填)
realm_setting: string (选填)
characters: string (选填)
genre: string (选填, 题材)
cover_image: file (选填, 封面图片)
```

**响应**
```json
{
  "状态码": 200,
  "消息": "创建成功",
  "数据": { "novel_unique_id": "xxx", "title": "作品名", ... }
}
```

---

### 2.2 作品列表（匿名可访问）

```
GET /api/novels/list?target_reader=男频&genre=玄幻&page=1&page_size=12
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_reader | string | 否 | 男频 / 女频 |
| genre | string | 否 | 题材筛选 |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 12，最大 50 |

**响应**
```json
{
  "状态码": 200,
  "消息": "查询成功",
  "数据": [
    {
      "novel_unique_id": "xxx",
      "title": "紫薇星途",
      "target_reader": "男频",
      "genre": "玄幻",
      "description": "...",
      "cover_image": "/uploads/xxx.png",
      "author_name": "admin",
      "status": 1,
      "created_at": "2026-07-01 10:00:00"
    }
  ]
}
```

---

### 2.3 搜索作品

```
GET /api/novels/search?keyword=修仙&page=1&page_size=12
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| keyword | string | 是 | 搜索关键词 |
| page | int | 否 | 默认 1 |
| page_size | int | 否 | 默认 12，最大 50 |

---

### 2.4 作品详情

```
GET /api/novels/detail/{novel_unique_id}
```

**响应**
```json
{
  "状态码": 200,
  "消息": "查询成功",
  "数据": {
    "novel_unique_id": "xxx",
    "title": "紫薇星途",
    "author_name": "admin",
    "target_reader": "男频",
    "genre": "玄幻",
    "description": "...",
    "story_background": "...",
    "world_setting": "...",
    "realm_setting": "...",
    "characters": "...",
    "cover_image": "/uploads/xxx.png",
    "status": 1,
    "word_count": 50000,
    "created_at": "2026-07-01 10:00:00"
  }
}
```

---

### 2.5 我的作品列表 🔒

```
GET /api/novels/my
```

> 返回当前登录用户创建的所有作品，直接从 MySQL 查询，不使用缓存。

---

### 2.6 编辑作品 🔒

```
PUT /api/novels/update/{novel_unique_id}
```

**请求体** (全部选填)
```json
{
  "title": "新标题",
  "target_reader": "男频",
  "description": "新简介",
  "story_background": "...",
  "world_setting": "...",
  "genre": "修真",
  "cover_image": "..."
}
```

---

### 2.7 删除作品 🔒

```
DELETE /api/novels/delete/{novel_unique_id}
```

> 同时删除关联的章节、互动记录、Redis 缓存、ES 索引、本地文本文件。

---

## 三、章节模块 `/api/chapters`

### 3.1 手动创建章节 🔒

```
POST /api/chapters/create
```

**请求体**
```json
{
  "novel_unique_id": "string (必填)",
  "chapter_name": "第一章 穿越异世界 (必填)",
  "characters_involved": "主角、配角 (选填)",
  "organizations": "宗门、门派 (选填)",
  "locations": "地点描述 (选填)",
  "skills": "功法、技能 (选填)",
  "word_count": 2000,
  "chapter_summary": "本章概要 (选填)"
}
```

---

### 3.2 AI 生成章节 🔒

```
POST /api/chapters/generate
```

**请求体** 同上，`word_count` 默认 2000。

> 异步接口。调用 DeepSeek API 根据作品设定 + 历史章节生成新章节内容，生成后返回章节信息。

---

### 3.3 获取草稿列表 🔒

```
GET /api/chapters/drafts
```

> 返回当前用户所有未发布的草稿章节。

---

### 3.4 更新章节 🔒

```
PUT /api/chapters/update/{chapter_unique_id}
```

**请求体** (全部选填)
```json
{
  "content": "章节正文内容...",
  "chapter_name": "修改后的标题",
  "chapter_summary": "修改后的摘要"
}
```

---

### 3.5 发布章节 🔒

```
POST /api/chapters/publish/{chapter_unique_id}
```

**请求体**
```json
{
  "content": "章节正文内容..."
}
```

> 发布后会触发互动动态流通知。

---

### 3.6 删除章节 🔒

```
DELETE /api/chapters/delete/{chapter_unique_id}
```

---

### 3.7 获取作品章节列表

```
GET /api/chapters/novel/{novel_unique_id}
```

**响应**
```json
{
  "状态码": 200,
  "消息": "查询成功",
  "数据": [
    {
      "chapter_unique_id": "xxx",
      "chapter_name": "第一章 穿越异世界",
      "chapter_index": 1,
      "word_count": 2500,
      "status": 1,
      "created_at": "2026-07-01 10:30:00"
    }
  ]
}
```

---

## 四、互动模块 `/api/interactions`

### 4.1 发表评论 🔒

```
POST /api/interactions/comment
```

**请求体**
```
novel_unique_id: string (必填)
comment_text: string (必填)
user_id: int (必填, 被评论的作者ID)
```

---

### 4.2 点赞 🔒

```
POST /api/interactions/like
```

**请求体**
```
novel_unique_id: string (必填)
user_id: int (必填, 被点赞的作者ID)
```

---

### 4.3 关注 🔒

```
POST /api/interactions/follow
```

**请求体**
```
novel_unique_id: string (必填)
user_id: int (必填, 被关注的作者ID)
```

---

### 4.4 收藏 🔒

```
POST /api/interactions/bookmark
```

**请求体**
```
novel_unique_id: string (必填)
user_id: int (必填, 被收藏的作者ID)
```

---

### 4.5 获取作品评论

```
GET /api/interactions/comments/{novel_unique_id}?page=1&page_size=20
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 默认 1 |
| page_size | int | 否 | 默认 20，最大 50 |

---

### 4.6 互动动态流

```
GET /api/interactions/feed?page=1&page_size=20
```

> 返回所有人发布章节、评论等互动动态的时间线，支持分页。

---

## 五、上传模块 `/api/upload`

### 5.1 上传封面图片

```
POST /api/upload/image
```

**请求体** multipart/form-data
| 字段 | 类型 | 说明 |
|------|------|------|
| file | File | 图片文件，限 10MB，仅限 image/* 类型 |

**响应**
```json
{
  "success": true,
  "url": "/uploads/abc123.png",
  "filename": "abc123.png",
  "size": 204800
}
```

> 图片保存到 `frontend/public/uploads/` 目录，URL 可直接通过前端访问。

---

## 六、VIP 模块 `/api/vip`

### 6.1 VIP 套餐列表

```
GET /api/vip/plans
```

**响应**
```json
{
  "状态码": 200,
  "消息": "查询成功",
  "数据": {
    "monthly": { "name": "月度会员", "price": 59.00, "days": 30, "desc": "1个月" },
    "quarterly": { "name": "季度会员", "price": 149.00, "days": 90, "desc": "3个月" },
    "yearly": { "name": "年度会员", "price": 499.00, "days": 365, "desc": "12个月" }
  }
}
```

---

### 6.2 创建支付订单 🔒

```
POST /api/vip/create-order
```

**请求体**
```json
{
  "plan_type": "monthly"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| plan_type | string | 否 | monthly / quarterly / yearly，默认 monthly |

**响应**
```json
{
  "状态码": 200,
  "消息": "订单创建成功",
  "数据": {
    "pay_url": "/api/vip/pay/VIP20260701xxx",
    "out_trade_no": "VIP20260701xxx",
    "plan_name": "月度会员",
    "amount": 59.00
  }
}
```

> 前端拿到 `pay_url` 后直接 `window.location.href = pay_url` 跳转支付宝页面。

---

### 6.3 支付宝收银台页面

```
GET /api/vip/pay/{out_trade_no}
```

> 返回 HTML 页面，自动 POST 到支付宝，展示扫码支付界面。

---

### 6.4 确认支付并开通 VIP 🔒

```
POST /api/vip/confirm/{out_trade_no}
```

> 支付完成后前端调用。后端向支付宝查询订单状态，确认已支付则开通 VIP。

**响应**
```json
{
  "状态码": 200,
  "消息": "支付成功，VIP 已开通！"
}
```

```json
{
  "状态码": 402,
  "消息": "尚未收到支付，请确认已完成支付后再试"
}
```

---

### 6.5 VIP 状态查询 🔒

```
GET /api/vip/status
```

**响应**
```json
{
  "状态码": 200,
  "消息": "查询成功",
  "数据": {
    "is_vip": true,
    "is_svip": true,
    "vip_level": 2,
    "vip_expire_at": "2026-08-23 12:00:00",
    "username": "testuser"
  }
}
```

---

### 6.6 查询订单状态 🔒

```
GET /api/vip/query/{out_trade_no}
```

---

### 6.7 支付宝异步通知（支付宝回调）

```
POST /api/vip/notify
```

> 支付宝服务器主动回调，验签后更新订单 + 用户 VIP 状态。返回纯文本 `success` 或 `failure`。

---

## 七、配置模块 `/api/config`

### 7.1 获取公开配置

```
GET /api/config/public
```

**响应**
```json
{
  "状态码": 200,
  "消息": "查询成功",
  "数据": {
    "show_all_works": false
  }
}
```

> 返回前端公开配置项，无需登录。

---

## 八、系统端点

### 8.1 健康检查

```
GET /api/health
```

**响应**
```json
{
  "状态码": 200,
  "消息": "服务正常",
  "数据": {
    "mysql": true,
    "redis": true,
    "status": "ok"
  }
}
```

---

## 附录

### 认证图例

| 图标 | 含义 |
|------|------|
| 🔒 | 需要登录认证 |

### VIP 等级

| 等级 | 值 | 说明 |
|------|-----|------|
| 免费用户 | `vip_level=0` | 基础使用权限 |
| VIP 会员 | `vip_level=1` | 10 章/天 AI 生成配额 |
| SVIP 会员 | `vip_level=2` | 50 章/天 AI 生成配额 |

### 错误码速查

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 参数错误 / 业务逻辑错误 |
| 401 | 未登录 / Token 无效或过期 |
| 402 | 支付未完成 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
