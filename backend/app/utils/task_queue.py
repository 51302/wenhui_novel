"""
Redis 任务队列 — 使用 Redis List 实现轻量级任务队列
支持：RPUSH 提交任务 / LPOP 消费任务 / 状态跟踪 / 结果存储

使用方式：
  1. 生产者（API层）：TaskQueue.push(queue_name, task_data) → task_id
  2. 消费者（后台Worker）：TaskQueue.pop(queue_name) → task_data
  3. 状态轮询：TaskQueue.get_status(task_id) → {status, result, error}
"""
import json
import uuid
import time
import threading
import asyncio
import app.utils.redis_cache as redis_mod
from app.config import get as cfg_get

TASK_PREFIX = "task:"
TASK_QUEUE_PREFIX = "task:queue:"
TASK_STATUS_PREFIX = "task:status:"
TASK_RESULT_PREFIX = "task:result:"
TASK_DATA_PREFIX = "task:data:"


def run_async(async_func, *args, **kwargs):
    """在 Worker 线程中运行异步函数
    使用独立的事件循环，不干扰主线程的事件循环
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(async_func(*args, **kwargs))
    finally:
        loop.close()


def _redis():
    return redis_mod.redis_client


class TaskQueue:

    # 并发控制上限从 config.yaml → task_queue.max_concurrency 读取（默认 3）
    _max_concurrency = int(cfg_get("task_queue.max_concurrency", 3))
    _semaphore = threading.Semaphore(_max_concurrency)
    _worker_started = False
    _worker_threads = []

    @staticmethod
    def push(queue_name: str, task_data: dict, ttl: int = 3600) -> str:
        """提交任务到队列，返回task_id
        :param queue_name: 队列名，如 'ai:generate'
        :param task_data: 任务参数字典
        :param ttl: 结果保留时间（秒）
        :return: task_id
        """
        task_id = uuid.uuid4().hex[:16]
        r = _redis()
        if not r:
            return ""

        # 存储任务数据
        r.set(f"{TASK_DATA_PREFIX}{task_id}", json.dumps(task_data), ttl=ttl)
        # 设置初始状态
        r.set(f"{TASK_STATUS_PREFIX}{task_id}", json.dumps("pending"), ttl=ttl)
        # 正式入队
        queue_key = f"{TASK_QUEUE_PREFIX}{queue_name}"
        rpush_result = r.rpush(queue_key, task_id)
        if not rpush_result:
            from app.utils.logger import system_logger
            system_logger.warning(f"rpush失败: key={queue_key} task_id={task_id}")

        return task_id

    @staticmethod
    def pop(queue_name: str, timeout: int = 1) -> tuple:
        """从队列取出一个任务（阻塞等待）
        :param queue_name: 队列名
        :param timeout: 阻塞超时秒数
        :return: (task_id, task_data_dict) 或 (None, None)
        """
        r = _redis()
        if not r:
            return None, None

        result = r.blpop(f"{TASK_QUEUE_PREFIX}{queue_name}", timeout=timeout)
        if not result:
            return None, None

        task_id = result[1]
        data_json = r.get(f"{TASK_DATA_PREFIX}{task_id}")
        # 注意：RedisCache.get() 内部已做 json.loads，返回的是 Python 对象
        # 这里直接使用，不要再 json.loads
        task_data = data_json if isinstance(data_json, dict) else {}

        # 标记为处理中
        r.set(f"{TASK_STATUS_PREFIX}{task_id}", json.dumps("processing"))

        return task_id, task_data

    @staticmethod
    def set_status(task_id: str, status: str):
        """更新任务状态（存储为 JSON，确保 RedisCache.get() 正确反序列化）"""
        r = _redis()
        if r:
            r.set(f"{TASK_STATUS_PREFIX}{task_id}", json.dumps(status))

    @staticmethod
    def set_result(task_id: str, result_data: dict):
        """设置任务结果"""
        r = _redis()
        if r:
            r.set(f"{TASK_RESULT_PREFIX}{task_id}", json.dumps(result_data))

    @staticmethod
    def set_progress(task_id: str, current: int, total: int, message: str = ""):
        """更新任务进度"""
        r = _redis()
        if r:
            from app.utils.logger import system_logger
            progress_data = {"current": current, "total": total, "message": message}
            r.set(f"{TASK_STATUS_PREFIX}{task_id}", json.dumps("processing"))
            r.set(f"{TASK_RESULT_PREFIX}{task_id}:progress", json.dumps(progress_data))
            system_logger.info(f"[进度] task={task_id} {current}/{total} - {message}")

    @staticmethod
    def get_status(task_id: str) -> dict:
        """查询任务状态和结果
        :return: {"status": "pending|processing|done|failed", "result": {...}, "error": "...", "progress": {...}}
        """
        r = _redis()
        if not r:
            return {"status": "unknown", "error": "Redis不可用"}

        status = r.get(f"{TASK_STATUS_PREFIX}{task_id}")
        if not status:
            return {"status": "not_found", "error": "任务不存在或已过期"}

        result = {"status": status}
        if status == "done":
            result_data = r.get(f"{TASK_RESULT_PREFIX}{task_id}")
            if isinstance(result_data, dict):
                result["result"] = result_data
        elif status == "failed":
            result_data = r.get(f"{TASK_RESULT_PREFIX}{task_id}")
            if isinstance(result_data, dict):
                result["error"] = result_data.get("error", "未知错误")

        # 获取进度（RedisCache.get() 已自动 json.loads，返回 dict）
        progress_data = r.get(f"{TASK_RESULT_PREFIX}{task_id}:progress")
        if isinstance(progress_data, dict):
            result["progress"] = progress_data

        return result

    @staticmethod
    def start_worker(queue_name: str, handler_func, concurrency: int = 1):
        """启动后台Worker线程，持续消费队列中的任务
        :param queue_name: 队列名
        :param handler_func: 处理函数，签名 handler(task_id, task_data) → dict
        :param concurrency: 并发Worker数
        """
        def _worker_loop():
            from app.utils.logger import system_logger as _log
            _hb_count = 0
            while True:
                try:
                    task_id, task_data = TaskQueue.pop(queue_name, timeout=5)
                    if task_id is None:
                        _hb_count += 1
                        if _hb_count % 60 == 0:  # 每5分钟心跳
                            _log.info(f"[Worker-{queue_name}] 心跳: 等待中...")
                        continue

                    _hb_count = 0
                    _log.info(f"[Worker-{queue_name}] 消费任务: task_id={task_id} data_keys={list(task_data.keys())}")

                    TaskQueue.set_status(task_id, "processing")

                    # 限制并发数
                    acquired = TaskQueue._semaphore.acquire(timeout=300)
                    if not acquired:
                        TaskQueue.set_status(task_id, "failed")
                        TaskQueue.set_result(task_id, {"error": "等待超时，所有Worker繁忙"})
                        _log.warning(f"[Worker-{queue_name}] 任务等待超时: task_id={task_id}")
                        continue

                    _log.info(f"[Worker-{queue_name}] 开始执行: task_id={task_id}")

                    try:
                        result = handler_func(task_id, task_data)
                        is_ok = result.get("success") or result.get("状态码") == 200
                        if is_ok:
                            TaskQueue.set_status(task_id, "done")
                            TaskQueue.set_result(task_id, result)
                            _log.info(f"[Worker-{queue_name}] 任务完成: task_id={task_id}")
                        else:
                            TaskQueue.set_status(task_id, "failed")
                            TaskQueue.set_result(task_id, {"error": result.get("error") or result.get("消息", "处理失败")})
                            _log.warning(f"[Worker-{queue_name}] 任务失败: task_id={task_id} error={result.get('error') or result.get('消息', '')}")
                    except Exception as e:
                        TaskQueue.set_status(task_id, "failed")
                        TaskQueue.set_result(task_id, {"error": str(e)})
                        _log.error(f"[Worker-{queue_name}] 任务异常: task_id={task_id} error={e}")
                    finally:
                        TaskQueue._semaphore.release()

                except Exception as e:
                    _log.error(f"[Worker-{queue_name}] 循环异常: {e}")
                    import traceback
                    _log.error(traceback.format_exc())
                    time.sleep(1)

        for _ in range(concurrency):
            t = threading.Thread(target=_worker_loop, daemon=True)
            t.start()
            TaskQueue._worker_threads.append(t)
