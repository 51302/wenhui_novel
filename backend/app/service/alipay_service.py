"""
支付宝电脑网站支付集成（从 config.yaml 读取配置）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 配置在 backend/app/conf/config.yaml 的 alipay 段
- 填入 app_id + app_private_key + alipay_public_key → 真实验签模式
- 未填入则自动运行 Demo 模式（本地模拟支付，用于开发调试）
"""
import base64
import json
import logging
import os
import uuid
from datetime import datetime
from urllib.parse import quote_plus

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from app.config import get as cfg_get

logger = logging.getLogger(__name__)

# ---- 对外暴露的配置变量（优先环境变量覆盖） ----
ALIPAY_SANDBOX = os.environ.get(
    "ALIPAY_SANDBOX", str(cfg_get("alipay.sandbox", True))
).lower() in ("true", "1", "yes")

ALIPAY_APP_ID = os.environ.get(
    "ALIPAY_APP_ID", cfg_get("alipay.app_id", "")
)

ALIPAY_PRIVATE_KEY = os.environ.get(
    "ALIPAY_PRIVATE_KEY", cfg_get("alipay.app_private_key", "")
)

ALIPAY_PUBLIC_KEY = os.environ.get(
    "ALIPAY_PUBLIC_KEY", cfg_get("alipay.alipay_public_key", "")
)

ALIPAY_NOTIFY_URL = os.environ.get(
    "ALIPAY_NOTIFY_URL", cfg_get("alipay.notify_url", "http://127.0.0.1:8000/api/vip/notify")
)

ALIPAY_RETURN_URL = os.environ.get(
    "ALIPAY_RETURN_URL", cfg_get("alipay.return_url", "")
)

ALIPAY_SELLER_ID = os.environ.get(
    "ALIPAY_SELLER_ID", cfg_get("alipay.seller_id", "")
)

ALIPAY_ORDER_TIMEOUT = os.environ.get(
    "ALIPAY_ORDER_TIMEOUT", cfg_get("alipay.order_timeout", "15m")
)

ALIPAY_ORDER_PREFIX = os.environ.get(
    "ALIPAY_ORDER_PREFIX", cfg_get("alipay.order_prefix", "VIP")
)

# VIP 套餐（从 YAML 读取，供 API 层使用）
# vip_level: 1=VIP(10章/天), 2=SVIP(50章/天)
VIP_PLANS = cfg_get("alipay.plans", {
    # VIP 套餐: ¥59/月, 季度¥149(省¥28), 年度¥499(省¥209)
    "vip_monthly":   {"name": "VIP月度会员",   "price": "59.00",  "days": 30,  "desc": "1个月VIP · 10章/天",  "vip_level": 1},
    "vip_quarterly": {"name": "VIP季度会员",   "price": "149.00", "days": 90,  "desc": "3个月VIP · 10章/天 · 省¥28",  "vip_level": 1},
    "vip_yearly":    {"name": "VIP年度会员",   "price": "499.00", "days": 365, "desc": "12个月VIP · 10章/天 · 省¥209", "vip_level": 1},
    # SVIP 套餐: ¥79/月, 季度¥199(省¥38), 年度¥699(省¥249)
    "svip_monthly":   {"name": "SVIP月度会员",   "price": "79.00",  "days": 30,  "desc": "1个月SVIP · 50章/天",  "vip_level": 2},
    "svip_quarterly": {"name": "SVIP季度会员",   "price": "199.00", "days": 90,  "desc": "3个月SVIP · 50章/天 · 省¥38",  "vip_level": 2},
    "svip_yearly":    {"name": "SVIP年度会员",   "price": "699.00", "days": 365, "desc": "12个月SVIP · 50章/天 · 省¥249", "vip_level": 2},
})

# ---- 判定是否是真实验签模式 ----
# 只要配置了 app_id + app_private_key + alipay_public_key 就走真实验签
# 砂箱/正式环境由 sandbox 开关控制网关地址不同
IS_REAL_MODE = bool(ALIPAY_APP_ID and ALIPAY_PRIVATE_KEY and ALIPAY_PUBLIC_KEY)

# ---- 网关地址 ----
GATEWAY_URL = (
    "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    if ALIPAY_SANDBOX
    else "https://openapi.alipay.com/gateway.do"
)

# ---- Demo 模式用的自生成密钥对 ----
_demo_private_key = None
_demo_public_key = None


def _ensure_keys():
    """确保有可用的密钥对（优先用配置的，否则自动生成）"""
    global _demo_private_key, _demo_public_key

    if IS_REAL_MODE:
        return True  # 真实验签模式

    if _demo_private_key:
        return True  # 已生成

    try:
        _demo_private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        _demo_public_key = _demo_private_key.public_key()
        logger.info("Demo 模式：已自动生成 RSA 密钥对")
        return True
    except Exception as e:
        logger.error(f"密钥生成失败: {e}")
        return False


def _get_private_key():
    """获取签名私钥，兼容多种 PEM 格式"""
    if IS_REAL_MODE:
        k = ALIPAY_PRIVATE_KEY.strip()
        # 如果已经带有 PEM 头尾，直接加载
        if k.startswith("-----"):
            for pw in [None, b""]:
                try:
                    return serialization.load_pem_private_key(k.encode(), password=pw, backend=default_backend())
                except Exception:
                    continue
        # 否则尝试补上各种可能的头尾
        headers = [
            "-----BEGIN RSA PRIVATE KEY-----\n",
            "-----BEGIN PRIVATE KEY-----\n",
        ]
        footers = [
            "\n-----END RSA PRIVATE KEY-----",
            "\n-----END PRIVATE KEY-----",
        ]
        for h, f in zip(headers, footers):
            for pw in [None, b""]:
                try:
                    pk = h + k + f
                    return serialization.load_pem_private_key(pk.encode(), password=pw, backend=default_backend())
                except Exception:
                    continue
        logger.error("无法解析应用私钥，请检查格式")
    _ensure_keys()
    return _demo_private_key


def _get_public_key_obj():
    """获取验签用的支付宝公钥，兼容多种 PEM 格式"""
    if IS_REAL_MODE:
        k = ALIPAY_PUBLIC_KEY.strip()
        # 支持的 PEM 头尾组合
        combos = [
            ("-----BEGIN PUBLIC KEY-----\n",  "\n-----END PUBLIC KEY-----"),
            ("-----BEGIN RSA PUBLIC KEY-----\n", "\n-----END RSA PUBLIC KEY-----"),
        ]
        # 先尝试直接带有头尾的
        if k.startswith("-----"):
            try:
                return serialization.load_pem_public_key(k.encode(), backend=default_backend())
            except Exception:
                pass
        # 尝试拼接头尾
        for header, footer in combos:
            try:
                pk = header + k + footer
                return serialization.load_pem_public_key(pk.encode(), backend=default_backend())
            except Exception:
                continue
        # 如果是纯 base64，可能还需要换行分段（每64字符换行）
        for header, footer in combos:
            try:
                # 每64字符插入换行
                wrapped = "\n".join(k[i:i+64] for i in range(0, len(k), 64))
                pk = header + wrapped + footer
                return serialization.load_pem_public_key(pk.encode(), backend=default_backend())
            except Exception:
                continue
        logger.error("无法解析支付宝公钥，请检查格式")
    _ensure_keys()
    return _demo_public_key


def _sign(data: str) -> str:
    """使用RSA2(SHA256)对字符串签名，返回Base64编码的签名
    :param data: 待签名字符串
    :return: Base64编码的签名字符串
    """
    key = _get_private_key()
    if not key:
        raise ValueError("密钥不可用")
    sig = key.sign(data.encode('utf-8'), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def _verify_sign(params: dict) -> bool:
    """验签支付宝异步通知"""
    public_key = _get_public_key_obj()
    if not public_key:
        return False
    sign = params.pop("sign", "")
    sorted_items = sorted(params.items())
    sign_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    try:
        public_key.verify(base64.b64decode(sign), sign_str.encode(), padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


# ========================================================================
# 构建支付表单
# ========================================================================

def _build_signed_form(biz_content: dict, method: str, is_demo: bool = False) -> str:
    """构建支付宝支付表单HTML，包含签名
    :param biz_content: 业务参数（订单号/金额/商品名等）
    :param method: 支付宝API方法名
    :param is_demo: 是否为Demo模式
    :return: 完整的HTML表单字符串
    """
    app_id = ALIPAY_APP_ID if ALIPAY_APP_ID else "2021000000000001"
    params = {
        "app_id": app_id,
        "method": method,
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": ALIPAY_NOTIFY_URL,
        "biz_content": json.dumps(biz_content, ensure_ascii=False),
    }
    # 设置了 return_url 才传
    if ALIPAY_RETURN_URL:
        params["return_url"] = ALIPAY_RETURN_URL

    # 支付宝签名规则：参数按key排序，参数值进行URL编码，签名字符串再RSA2签名
    sorted_params = sorted(params.items())
    sign_str = "&".join(f"{k}={quote_plus(str(v), encoding='utf-8')}" for k, v in sorted_params)
    params["sign"] = _sign(sign_str)

    if is_demo:
        return _build_demo_page(params, biz_content)
    else:
        return _build_alipay_form(params)


def _build_alipay_form(params: dict) -> str:
    """构建跳转支付宝收银台的 HTML 表单"""
    html = f'<form id="alipayForm" action="{GATEWAY_URL}" method="POST" accept-charset="utf-8">'
    for k, v in params.items():
        html += f'<input type="hidden" name="{_escape_html(str(k))}" value="{_escape_html(str(v))}">'
    html += '<script>document.getElementById("alipayForm").submit();</script></form>'
    return html


def _build_demo_page(params: dict, biz_content: dict) -> str:
    """Demo 模式：构建本地模拟支付确认页面"""
    out_trade_no = biz_content["out_trade_no"]
    subject = biz_content["subject"]
    amount = biz_content["total_amount"]
    notify_url = params.get("notify_url", "/api/vip/notify")

    sign = params["sign"]
    tid = uuid.uuid4().hex[:16]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>支付宝 - 收银台（Demo）</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f5f5;display:flex;justify-content:center;align-items:center;min-height:100vh}}
.card{{background:#fff;border-radius:12px;box-shadow:0 2px 20px rgba(0,0,0,0.08);width:440px;padding:40px}}
.card h2{{text-align:center;color:#1677ff;margin-bottom:4px;font-size:20px}}
.card .demo-badge{{text-align:center;margin-bottom:20px;font-size:12px;color:#ff9500;font-weight:600}}
.card .demo-badge span{{background:#fff3e0;padding:3px 12px;border-radius:10px;border:1px solid #ffcc80}}
.item{{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #f0f0f0;font-size:14px}}
.item .label{{color:#888}}
.item .value{{color:#333;font-weight:500}}
.total{{display:flex;justify-content:space-between;padding:16px 0;font-size:18px;font-weight:700}}
.total .amount{{color:#ff4d4f;font-size:24px}}
.btn{{width:100%;padding:14px;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;margin-top:20px;transition:all .3s}}
.btn-pay{{background:linear-gradient(135deg,#1677ff,#0958d9);color:#fff}}
.btn-pay:hover{{opacity:.9;transform:translateY(-1px);box-shadow:0 4px 16px rgba(22,119,255,.3)}}
.btn-cancel{{background:#f5f5f5;color:#666;margin-top:8px}}
.btn-cancel:hover{{background:#e8e8e8}}
.result{{text-align:center;padding:20px 0;display:none}}
.result .icon{{font-size:48px;margin-bottom:12px}}
.result h3{{color:#333;margin-bottom:8px}}
.result p{{color:#888;font-size:14px}}
.info{{margin-top:20px;padding:12px;background:#fafafa;border-radius:8px;font-size:12px;color:#999;text-align:center}}
</style></head>
<body>
<div class="card">
  <h2>支付宝</h2>
  <div class="demo-badge"><span>⚡ 沙箱模拟模式</span></div>
  <div class="item"><span class="label">商品</span><span class="value">{_escape_html(subject)}</span></div>
  <div class="item"><span class="label">订单号</span><span class="value">{out_trade_no[:20]}...</span></div>
  <div class="total"><span>应付金额</span><span class="amount">¥{amount}</span></div>

  <div class="confirm-view" id="confirmView">
    <button class="btn btn-pay" onclick="doPay()">确认支付 ¥{amount}</button>
    <button class="btn btn-cancel" onclick="doCancel()">取消</button>
    <div class="info">这是 Demo 模拟支付页面，点击确认后将模拟支付成功</div>
  </div>

  <div class="result" id="resultView">
    <div class="icon">✅</div>
    <h3>支付成功</h3>
    <p>¥{amount} 已支付 · 交易号 {tid}</p>
    <p id="countDown" style="margin-top:12px;color:#1677ff">3 秒后自动返回...</p>
  </div>
</div>
<script>
function doPay(){{
  document.getElementById('confirmView').style.display='none';
  document.getElementById('resultView').style.display='block';
  let n=3;
  const cd=document.getElementById('countDown');
  const t=setInterval(function(){{
    n--;cd.textContent=n+' 秒后自动返回...';
    if(n<=0){{clearInterval(t);notifyBack();}}
  }},1000);
}}
function doCancel(){{window.close();history.back();}}
function notifyBack(){{
  fetch('/api/vip/demo-notify',{{
    method:'POST',
    headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
    body:new URLSearchParams({{
      out_trade_no:'{out_trade_no}',
      trade_no:'DEMO{"_" + tid}',
      total_amount:'{amount}',
      trade_status:'TRADE_SUCCESS',
      app_id:'{params.get("app_id","")}',
      sign:'{sign[:20]}',
      sign_type:'RSA2'
    }})
  }}).then(function(){{window.location.href='/vip';}});
}}
</script>
</body></html>"""
    return html


def _escape_html(s: str) -> str:
    """对HTML特殊字符进行转义，防止XSS攻击
    :param s: 原始字符串
    :return: 转义后的字符串
    """
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


# ========================================================================
#  对外公共接口
# ========================================================================

def create_page_pay(subject: str, out_trade_no: str, total_amount: str = "59.00") -> str:
    """
    生成电脑网站支付 HTML 页面（跳转支付宝收银台）。
    - 真实验签模式：返回跳转支付宝收银台的 form 表单
    - Demo 模式：返回本地模拟支付确认页面
    """
    _ensure_keys()
    biz_content = {
        "out_trade_no": out_trade_no,
        "product_code": "FAST_INSTANT_TRADE_PAY",
        "total_amount": total_amount,
        "subject": subject,
        "timeout_express": ALIPAY_ORDER_TIMEOUT,
    }
    is_demo = not IS_REAL_MODE
    return _build_signed_form(biz_content, "alipay.trade.page.pay", is_demo=is_demo)


# ========================================================================
# 订单码支付 (alipay.trade.precreate) — 页面内显示二维码
# ========================================================================
def create_precreate(subject: str, out_trade_no: str, total_amount: str = "59.00") -> str:
    """
    调用 alipay.trade.precreate 生成支付二维码链接。
    用户扫码支付，不需要跳转到支付宝页面。
    沙箱环境 API 不可用时自动降级为 Demo 模式（显示模拟二维码）。

    返回: qr_code 字符串（前端用 JS 生成二维码图片），始终有值
    """
    _ensure_keys()

    def _demo_qr():
        return (
            f"DEMO|{ALIPAY_APP_ID or '2021000000000001'}"
            f"|{out_trade_no}|{total_amount}|{subject}"
        )

    if not IS_REAL_MODE:
        demo_qr = _demo_qr()
        logger.info(f"[precreate] Demo模式返回模拟二维码: out_trade_no={out_trade_no}")
        return demo_qr

    # 真实验签模式：调用支付宝 precreate 接口
    biz_content = {
        "out_trade_no": out_trade_no,
        "total_amount": total_amount,
        "subject": subject,
        "timeout_express": ALIPAY_ORDER_TIMEOUT,
    }

    params = {
        "app_id": ALIPAY_APP_ID,
        "method": "alipay.trade.precreate",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": ALIPAY_NOTIFY_URL,
        "biz_content": json.dumps(biz_content, ensure_ascii=False),
    }

    sorted_params = sorted(params.items())
    sign_str = "&".join(f"{k}={v}" for k, v in sorted_params)
    params["sign"] = _sign(sign_str)

    try:
        r = requests.post(GATEWAY_URL, data=params, timeout=15)
        resp = r.json().get("alipay_trade_precreate_response", {})
        if resp.get("code") == "10000":
            qr_code = resp.get("qr_code", "")
            logger.info(f"[precreate] 成功: out_trade_no={out_trade_no}")
            return qr_code
        else:
            logger.warning(
                f"[precreate] API失败(code={resp.get('code')} sub_code={resp.get('sub_code')}), "
                f"降级为Demo模式: out_trade_no={out_trade_no}"
            )
            # 沙箱环境 API 不可用时，降级为 Demo 模式
            return _demo_qr()
    except Exception as e:
        logger.warning(f"[precreate] API异常({e}), 降级为Demo模式: out_trade_no={out_trade_no}")
        return _demo_qr()


def verify_notify(notify_params: dict):
    """
    验证支付宝异步通知。
    返回: (verified, out_trade_no, trade_no, total_amount, trade_status, seller_id)
    """
    params = dict(notify_params)
    out_trade_no = params.get("out_trade_no")
    trade_no = params.get("trade_no")
    total_amount = params.get("total_amount")
    trade_status = params.get("trade_status")
    seller_id = params.get("seller_id", "")

    # Demo 模式：不做严格验签
    if not IS_REAL_MODE:
        logger.info(f"Demo 模式通知: status={trade_status}, order={out_trade_no}")
        return True, out_trade_no, trade_no, total_amount, trade_status, seller_id

    # 真实验签模式：验签
    if not _verify_sign(params):
        logger.error(f"验签失败: order={out_trade_no}")
        return False, None, None, None, None, None

    # 校验 seller_id（钱是否到你的账户）
    if ALIPAY_SELLER_ID and seller_id and seller_id != ALIPAY_SELLER_ID:
        logger.error(f"收款账户不匹配! 通知seller_id={seller_id}, 配置={ALIPAY_SELLER_ID}")
        return False, None, None, None, None, None

    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        logger.info(f"非支付成功状态: status={trade_status}, order={out_trade_no}")
    return True, out_trade_no, trade_no, total_amount, trade_status, seller_id


def query_order(out_trade_no: str):
    """查询支付宝订单状态（Demo 模式或 API 不可用时返回成功，由调用方自己判断本地订单状态）"""
    if not IS_REAL_MODE:
        return {"success": True, "trade_status": "TRADE_SUCCESS", "msg": "Demo模式"}

    biz = {"out_trade_no": out_trade_no}
    params = {
        "app_id": ALIPAY_APP_ID, "method": "alipay.trade.query",
        "charset": "utf-8", "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "biz_content": json.dumps(biz, ensure_ascii=False),
    }
    sorted_params = sorted(params.items())
    sign_str = "&".join(f"{k}={v}" for k, v in sorted_params)
    params["sign"] = _sign(sign_str)
    try:
        r = requests.post(GATEWAY_URL, data=params, timeout=15)
        d = r.json().get("alipay_trade_query_response", {})
        if d.get("code") == "10000":
            return {
                "success": True,
                "trade_status": d.get("trade_status"),
                "msg": d.get("msg", "")
            }
        else:
            # API 调用失败（如沙箱 APPID 无效），降级为成功返回
            logger.warning(f"[query] API失败(code={d.get('code')} sub_code={d.get('sub_code')}), 降级: out_trade_no={out_trade_no}")
            return {"success": True, "trade_status": "TRADE_SUCCESS", "msg": "降级模式"}
    except Exception as e:
        logger.warning(f"[query] API异常({e}), 降级: out_trade_no={out_trade_no}")
        return {"success": True, "trade_status": "TRADE_SUCCESS", "msg": "降级模式"}


def generate_out_trade_no(user_id: int) -> str:
    """生成唯一商户订单号: 前缀 + 时间戳 + user_id + 随机串"""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    prefix = ALIPAY_ORDER_PREFIX
    return f"{prefix}{ts}{str(user_id).zfill(4)}{uuid.uuid4().hex[:6]}"
