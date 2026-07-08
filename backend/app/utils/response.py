from typing import Any, Optional


def success(data: Any = None, message: str = "操作成功") -> dict:
    return {"状态码": 200, "消息": message, "数据": data}


def fail(message: str = "操作失败", code: int = 400) -> dict:
    return {"状态码": code, "消息": message, "数据": None}
