"""
SeaweedFS Filer 客户端 —— 通过 Filer HTTP API 上传/下载文件
"""
import os
import httpx
from pathlib import Path
from typing import Optional

# SeaweedFS Filer 地址（Docker 内部用 filer:8888，宿主机用 localhost:8888）
FILER_HOST = os.environ.get("SEAWEEDFS_FILER_HOST", "localhost")
FILER_PORT = int(os.environ.get("SEAWEEDFS_FILER_PORT", "8888"))
# 支持HTTPS配置
FILER_PROTOCOL = os.environ.get("SEAWEEDFS_FILER_PROTOCOL", "http")
FILER_BASE_URL = f"{FILER_PROTOCOL}://{FILER_HOST}:{FILER_PORT}"

# 外部访问URL（用于返回给前端）
EXTERNAL_FILER_HOST = os.environ.get("SEAWEEDFS_EXTERNAL_HOST", FILER_HOST)
EXTERNAL_FILER_PORT = os.environ.get("SEAWEEDFS_EXTERNAL_PORT", FILER_PORT)
EXTERNAL_FILER_PROTOCOL = os.environ.get("SEAWEEDFS_EXTERNAL_PROTOCOL", FILER_PROTOCOL)
EXTERNAL_FILER_BASE_URL = f"{EXTERNAL_FILER_PROTOCOL}://{EXTERNAL_FILER_HOST}:{EXTERNAL_FILER_PORT}"

# 上传目录（Filer 里的路径）
UPLOAD_COLLECTION = "uploads"

# 超时
_TIMEOUT = 15.0


def _filer_url(path: str = "") -> str:
    """拼接 Filer 完整 URL"""
    return f"{FILER_BASE_URL}/{UPLOAD_COLLECTION}/{path}" if path else f"{FILER_BASE_URL}/{UPLOAD_COLLECTION}"


def upload_file(file_bytes: bytes, filename: str, content_type: str = "") -> Optional[str]:
    """
    上传文件到 SeaweedFS Filer。
    成功返回访问 URL（如 http://localhost:8888/uploads/xxx.jpg），失败返回 None。
    返回的URL使用外部访问地址配置，确保前端可以正常访问。
    """
    url = _filer_url(filename)
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.put(url, content=file_bytes, headers=headers)
            if resp.status_code in (200, 201, 204):
                # 返回外部可访问的URL
                return f"{EXTERNAL_FILER_BASE_URL}/{UPLOAD_COLLECTION}/{filename}"
            print(f"[SeaweedFS] 上传失败 HTTP {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"[SeaweedFS] 连接失败（服务未启动?）: {e}")
        return None


def delete_file(filename: str) -> bool:
    """从 SeaweedFS 删除文件"""
    url = _filer_url(filename)
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.delete(url)
            return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[SeaweedFS] 删除失败: {e}")
        return False


def filer_accessible() -> bool:
    """检测 SeaweedFS Filer 是否可达"""
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(FILER_BASE_URL)
            return resp.status_code < 500
    except Exception:
        return False

def normalize_url(url: str) -> str:
    """
    把 SeaweedFS 完整 URL 转成前端可用的相对路径。
    例如 http://localhost:8888/uploads/abc.jpg → /seaweed/uploads/abc.jpg
    
    如果 FILER_HOST 不是 localhost，就保留完整 URL（跨域场景）。
    """
    if not url:
        return url
    if url.startswith("http://localhost:") or url.startswith("http://127.0.0.1:"):
        # 本地访问 → 相对路径
        return url.split("/", 3)[-1] if "/" in url.split("://", 1)[-1] else url
    return url
