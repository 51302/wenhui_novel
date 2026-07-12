from typing import Any, Optional


def success(data: Any = None, message: str = "操作成功") -> dict:
    """构建成功响应字典
    :param data: 响应数据
    :param message: 提示消息
    :return: 包含状态码 200 的响应字典
    """
    return {"状态码": 200, "消息": message, "数据": data}


def fail(message: str = "操作失败", code: int = 400) -> dict:
    """构建失败响应字典
    :param message: 错误提示消息
    :param code: HTTP 状态码
    :return: 包含错误信息的响应字典
    """
    return {"状态码": code, "消息": message, "数据": None}
