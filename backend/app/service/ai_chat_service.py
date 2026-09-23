import json

import httpx

from app.config import deepseek_api_key, deepseek_base_url
from app.utils.logger import system_logger


async def chat_completion_stream(messages: list, model: str, max_tokens: int, timeout: int = 180,
                                 on_chunk=None, **params) -> tuple:
    api_key = (deepseek_api_key() or "").strip()
    if not api_key:
        return "", "未配置模型 API Key，请在服务环境中设置 DEEPSEEK_API_KEY 后重新创建服务容器", None
    text_parts = []
    usage = None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", deepseek_base_url(),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "messages": messages, "max_tokens": max_tokens,
                      "stream": True, **params},
            ) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    try:
                        data = json.loads(raw.decode())
                        message = data.get("error", {}).get("message", f"HTTP {response.status_code}")
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        message = f"HTTP {response.status_code}"
                    return "", f"AI接口错误: {message}", None
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    usage = data.get("usage") or usage
                    choices = data.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    chunk = delta.get("content") or ""
                    if chunk:
                        text_parts.append(chunk)
                        if on_chunk:
                            await on_chunk(chunk)
        text = "".join(text_parts).strip()
        if not text:
            return "", "模型返回空内容", usage
        return text, "", usage
    except httpx.TimeoutException:
        return "", "AI接口调用超时", None
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
        return "", f"AI接口网络错误（{type(e).__name__}）: {e}", None
    except Exception as e:
        return "", str(e), None


async def chat_completion(messages: list, model: str, max_tokens: int, timeout: int = 180,
                          **params) -> tuple:
    """调用AI接口，返回 (text, err, usage_dict)。

    usage_dict 格式：{"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    失败时 usage_dict 为 None；网络异常只发送一次请求并直接返回错误。
    """
    api_key = (deepseek_api_key() or "").strip()
    if not api_key:
        return "", "未配置模型 API Key，请在服务环境中设置 DEEPSEEK_API_KEY 后重新创建服务容器", None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                deepseek_base_url(),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    **params,
                },
            )
        raw_text = response.text
        if not raw_text or not raw_text.strip():
            return "", f"AI接口返回空响应(HTTP {response.status_code})，请重试", None
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return "", f"AI接口返回格式异常(HTTP {response.status_code})，请重试", None
        if response.status_code != 200:
            err_msg = str(data.get("error", {}).get("message", f"HTTP {response.status_code}"))
            return "", f"AI接口错误: {err_msg}", None
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            err_msg = str(data.get("error", {}).get("message", "未知错误"))
            return "", err_msg, None
        message = choices[0].get("message")
        if not isinstance(message, dict):
            return "", "模型返回内容格式异常", None
        text = (message.get("content") or "").strip()
        if not text:
            return "", "模型返回空内容（可能只输出思考内容）", None
        usage = data.get("usage") or {}
        usage_dict = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        return text, "", usage_dict
    except httpx.TimeoutException as e:
        system_logger.error(f"[AI接口] 请求超时: {e}")
        return "", "AI接口调用超时", None
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
        exception_type = type(e).__name__
        system_logger.error(f"[AI接口] 网络错误 {exception_type}: {e}")
        return "", f"AI接口网络错误（{exception_type}）: {e}", None
    except Exception as e:
        return "", str(e), None


def log_ai_call(tag: str, messages: list, text: str, err: str = None,
                usage: dict = None, model: str = None,
                extra_info: dict = None):
    """统一记录AI调用的日志：输入字数、输出字数、token用量、实际费用。

    tag: 调用标识，如 "正文生成" "续写" "事实核查" "记忆提取"
    model: 模型名称，用于匹配定价（如 "mimo-v2.5-pro"）
    extra_info: 可选的额外信息
    """
    from app.config import get as cfg

    # 模型定价（元/百万token）
    PRICING = {
        "mimo-v2.5-pro": {"input": 3.00, "output": 6.00},
        "mimo-v2.5": {"input": 0.50, "output": 1.00},
        "deepseek-v4-pro": {"input": 4.00, "output": 8.00},
        "deepseek-v4-flash": {"input": 0.50, "output": 1.00},
    }

    # 统计输入消息总字符数
    input_chars = sum(len(m.get("content") or "") for m in messages)
    output_chars = len(text) if text else 0
    usage = usage or {}
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    tt = usage.get("total_tokens", 0)

    # 计算费用
    cost = 0.0
    cost_str = ""
    if model and pt > 0:
        pricing = PRICING.get(model, PRICING.get("mimo-v2.5-pro"))
        cost = (pt * pricing["input"] + ct * pricing["output"]) / 1_000_000
        cost_str = f" | 费用=¥{cost:.4f}"

    extra_parts = []
    if extra_info:
        for k, v in extra_info.items():
            extra_parts.append(f"{k}={v}")
    extra_str = f" | {' | '.join(extra_parts)}" if extra_parts else ""

    if err:
        system_logger.info(
            f"[AI调用] {tag} | 输入={input_chars}字 | 失败: {err}")
    else:
        system_logger.info(
            f"[AI调用] {tag} | 输入={input_chars}字 | 输出={output_chars}字 | "
            f"prompt_tokens={pt} | completion_tokens={ct} | total_tokens={tt}"
            f"{cost_str}{extra_str}")

    # 返回费用，方便上层累计
    return cost


# ============================================================
# Token 预估与动态优化
# ============================================================

# 中文/英文混合文本的 token 比率（经验值：1个中文字≈1.5token，1个英文词≈1.3token）
# 对于 DeepSeek/mimo 系列模型，中文字符约占字符数的 60-70%，
# 英文+标点约占 30-40%，综合比率约 1.2-1.5 token/字符
_TOKEN_RATIO_CHINESE = 1.5    # 中文字符 token 比率
_TOKEN_RATIO_OTHER = 0.8     # 英文/标点/空格 token 比率（英文字符通常比中文短）


def estimate_tokens(text: str) -> int:
    """预估文本的 token 数量（中英混合文本的经验估算）"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'
                        or '\u3400' <= c <= '\u4dbf'
                        or '\U00020000' <= c <= '\U0002a6df')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * _TOKEN_RATIO_CHINESE + other_chars * _TOKEN_RATIO_OTHER)


def estimate_generation_tokens(
    system_prompt: str = "",
    memory_body: str = "",
    prompt: str = "",
    summary: str = "",
    last_ending: str = "",
    max_tokens: int = 6000,
    word_count: int = 2000,
) -> dict:
    """预估章节生成全流程的 token 消耗

    返回:
        {
            "input_tokens": 预估输入token,
            "output_tokens": 预估输出token,
            "total_tokens": 预估总token,
            "breakdown": 各部分token明细,
            "recommendations": 优化建议列表,
        }
    """
    # 各部分 token 预估
    sys_tokens = estimate_tokens(system_prompt)
    mem_tokens = estimate_tokens(memory_body)
    prompt_tokens = estimate_tokens(prompt)
    summary_tokens = estimate_tokens(summary)
    ending_tokens = estimate_tokens(last_ending)

    input_tokens = sys_tokens + mem_tokens + prompt_tokens + summary_tokens + ending_tokens
    # 输出 token 通常约为输入的 15-25%（生成 2000-3000 字）
    output_tokens = max_tokens  # 以上限预估

    breakdown = {
        "系统提示词": {"chars": len(system_prompt), "tokens": sys_tokens},
        "记忆体": {"chars": len(memory_body), "tokens": mem_tokens},
        "续写提示词": {"chars": len(prompt), "tokens": prompt_tokens},
        "章节概要": {"chars": len(summary), "tokens": summary_tokens},
        "上章末尾": {"chars": len(last_ending), "tokens": ending_tokens},
        "输出上限": {"tokens": output_tokens},
    }

    # 动态优化建议
    recommendations = []
    if input_tokens > 25000:
        recommendations.append(
            f"输入token偏高({input_tokens})，建议压缩记忆体(当前{mem_tokens}token)"
            "或减少系统提示词长度")
    if mem_tokens > 15000:
        recommendations.append(
            f"记忆体token偏高({mem_tokens})，建议降低 memory.max_inject_chars"
            "或开启按需检索压缩")
    if sys_tokens > 8000:
        recommendations.append(
            f"系统提示词token偏高({sys_tokens})，建议精简铁律和指南")
    if output_tokens > 8000:
        recommendations.append(
            f"输出token上限偏高({output_tokens})，建议降低 max_tokens_min"
            f"（当前{max_tokens}）以加速生成")

    total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "breakdown": breakdown,
        "recommendations": recommendations,
    }


def log_token_estimate(tag: str, estimate: dict):
    """输出 token 预估日志"""
    breakdown = estimate["breakdown"]
    parts = [f"{k}={v['tokens']}tk" for k, v in breakdown.items()]
    system_logger.info(
        f"[Token预估] {tag} | 输入≈{estimate['input_tokens']}tk | "
        f"输出≈{estimate['output_tokens']}tk | 总计≈{estimate['total_tokens']}tk | "
        f"明细: {' | '.join(parts)}")
    for rec in estimate["recommendations"]:
        system_logger.info(f"[Token优化] {tag} | {rec}")
