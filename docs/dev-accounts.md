# 文辉小说 - 开发环境账号 & 配置

> 本文档记录开发/测试阶段用到的第三方平台账号和配置，请妥善保管，不要提交到公开仓库。

---

## 一、支付宝沙箱

### 沙箱入口
https://openhome.alipay.com/platform/appDaily.htm

### 商家信息（收款方）

| 字段 | 值 |
|------|-----|
| 商户账号 | `oedpsk1399@sandbox.com` |
| 登录密码 | `111111` |
| 商户PID | `2088721102987571` |
| 账户余额 | ¥1,000,298.00 |

### 买家信息（付款方，用于沙箱 App 扫码测试）

| 字段 | 值 |
|------|-----|
| 买家账号 | `jwppja5905@sandbox.com` |
| 登录密码 | `111111` |
| 支付密码 | `111111` |
| 用户UID | `2088722102987583` |
| 用户名称 | `jwppja5905` |
| 证件类型 | `IDENTITY_CARD` |
| 证件账号 | `57623619041113450X` |
| 账户余额 | ¥999,702.00 |

### 使用方式

1. 电脑端登录沙箱页面，下载**支付宝沙箱版 App**（仅安卓）
2. 用**买家账号** `jwppja5905@sandbox.com` 登录沙箱 App
3. 在文辉小说 VIP 页面下单 → 跳转支付宝 → 用沙箱 App 扫码支付
4. 支付密码：`111111`

> ⚠️ 普通支付宝扫不了沙箱二维码，必须用沙箱版 App。

---

## 二、邮件服务 (Resend)

### 入口
https://resend.com/api-keys

### 当前配置（config.yaml）

| 字段 | 值 |
|------|-----|
| API Key | `re_RYn1kQ1Q_6EyQwQQ2ZZzRkBoSZbFiKFBY` |
| 发件地址 | `文辉小说 <onboarding@resend.dev>` |
| 免费额度 | 100 封/天 |

### 说明

- 本地开发使用 Resend 测试模式，发件地址为 `onboarding@resend.dev`。
- 上线前需在 Resend 后台添加真实域名并通过 DNS 验证，然后更换发件地址。
- API Key 已在 `backend/app/conf/config.yaml` 的 `email.resend_api_key` 中配置。

---

## 三、其他配置入口

| 服务 | 地址 |
|------|------|
| DeepSeek API | https://platform.deepseek.com/api_keys |
| 榛子云短信 | http://smsow.zhenzikj.com/ (暂未配置) |
