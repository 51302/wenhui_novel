# 文辉小说 - 开发环境账号 & 配置

> 本文档记录开发/测试阶段用到的第三方平台账号和配置，请妥善保管，不要提交到公开仓库。

---

## 一、支付宝支付

### 正式环境（当前使用）

| 字段 | 值 |
|------|-----|
| app_id | `2021006169682344` |
| seller_id | `2088422450482191` |
| 支付域名 | `wenhui.nat100.top` |
| 异步通知 URL | `http://wenhui.nat100.top/api/vip/notify` |
| 同步跳转 URL | `http://wenhui.nat100.top/vip` |

> 当前使用**正式环境**（`sandbox: false`），已配置正式密钥。

### VIP 套餐

| 套餐 | 价格 | 有效期 |
|------|------|--------|
| 月度会员 | ¥59.00 | 30 天 |
| 季度会员 | ¥149.00 | 90 天 |
| 年度会员 | ¥499.00 | 365 天 |

### 管理入口

| 用途 | 地址 |
|------|------|
| 开放平台（应用管理） | https://open.alipay.com/develop/manage |
| 商家平台（产品签约） | https://b.alipay.com/page/ar-center/front-product-sign/form?productCode=I1080300001000041203 |
| 传统管理首页 | https://open.alipay.com/platform/manageHome.htm |

> **产品签约**：在商家平台搜索"电脑网站支付"并签约，解决 `insufficient-isv-permissions` 错误。

---

## 二、邮件服务 (Resend)

### 入口
https://resend.com/api-keys

### 当前配置（config.yaml）

| 字段 | 值 |
|------|-----|
| API Key | `re_SX3ts5UT_PeyPGXNyQLcqVZuHTG8KRAbR` |
| 发件地址 | `文辉小说 <noreply@wenhui.xyz>` |
| 已验证域名 | `wenhui.xyz` |
| 免费额度 | 100 封/天 |

### 说明
- `wenhui.xyz` 域名已通过 DNS 验证
- 发件地址统一使用 `noreply@wenhui.xyz`
- API Key 已在 `backend/app/conf/config.yaml` 的 `email.resend_api_key` 中配置

---

## 三、内网穿透 (Natapp)

### 账号信息
| 字段 | 值 |
|------|-----|
| 手机号 | `13001991536` |
| 密码 | `lwp123.com` |

### 管理入口
https://natapp.cn/

### 隧道配置
| 字段 | 值 |
|------|-----|
| Authtoken | `52774ac87431feaa` |
| 映射域名 | `wenhui.nat100.top` |
| 本地端口 | 80（前端 Nginx） |

### 重启方式
```bash
docker rm -f wenhui-natapp
docker compose up -d natapp
```

---

## 四、域名管理

### 域名信息
| 字段 | 值 |
|------|-----|
| 域名 | `wenhui.xyz` |
| 解析平台 | 阿里云 DNS |

### DNS 管理
https://dnsnext.console.aliyun.com/authoritative/domains/wenhui.xyz

### ICP 备案
https://beian.aliyun.com/pcContainer/orderdetail?baOrderId=2034805095182

### 当前 DNS 记录

| 记录类型 | 主机记录 | 记录值 | 说明 |
|----------|----------|--------|------|
| A | `wenhui` | 服务器 IP | 网站访问 |

---

## 五、Docker 镜像仓库

### 地址
https://cr.console.aliyun.com/cn-hangzhou/instance/repositories

### 命名空间
`wenhui_novel`

### 镜像列表

| 镜像名 | 最新标签 | 说明 |
|--------|----------|------|
| `wenhui_novel-backend` | `v1.1.0` | FastAPI 后端 |
| `wenhui_novel-frontend` | `v1.1.0` | Nginx + Vue 前端 |

### 登录命令
```bash
docker login --username=aliyun8562152228 crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com
密码： lwp123.com
```

### 推送命令
```bash
docker tag wenhui_novel-backend crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-backend:v1.1.0
docker tag wenhui_novel-frontend crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-frontend:v1.1.0

docker push crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-backend:v1.1.0
docker push crpi-1xy58ppkqat4md0n.cn-hangzhou.personal.cr.aliyuncs.com/wenhui_novel/wenhui_novel-frontend:v1.1.0
```

### 修改权限
```bash
# VIP - 1个月
docker exec wenhui-mysql mysql -uwenhui -pwenhui123 easy-novel -e "UPDATE users SET vip_level=1, vip_expire_at=DATE_ADD(NOW(), INTERVAL 1 MONTH) WHERE username='momomo';"

# VIP - 1个季度（3个月）
docker exec wenhui-mysql mysql -uwenhui -pwenhui123 easy-novel -e "UPDATE users SET vip_level=1, vip_expire_at=DATE_ADD(NOW(), INTERVAL 3 MONTH) WHERE username='momomo';"

# VIP - 1年
docker exec wenhui-mysql mysql -uwenhui -pwenhui123 easy-novel -e "UPDATE users SET vip_level=1, vip_expire_at=DATE_ADD(NOW(), INTERVAL 1 YEAR) WHERE username='momomo';"

# SVIP - 1个月
docker exec wenhui-mysql mysql -uwenhui -pwenhui123 easy-novel -e "UPDATE users SET vip_level=2, vip_expire_at=DATE_ADD(NOW(), INTERVAL 1 MONTH) WHERE username='momomo';"

# SVIP - 1个季度（3个月）
docker exec wenhui-mysql mysql -uwenhui -pwenhui123 easy-novel -e "UPDATE users SET vip_level=2, vip_expire_at=DATE_ADD(NOW(), INTERVAL 3 MONTH) WHERE username='momomo';"

# SVIP - 1年
docker exec wenhui-mysql mysql -uwenhui -pwenhui123 easy-novel -e "UPDATE users SET vip_level=2, vip_expire_at=DATE_ADD(NOW(), INTERVAL 1 YEAR) WHERE username='momomo';"
```

---

## 六、其他配置入口

| 服务 | 地址 | 说明 |
|------|------|------|
| DeepSeek API | https://platform.deepseek.com/api_keys | AI 章节生成 |
| 阿里云控制台 | https://home.console.aliyun.com/ | 云资源管理 |
