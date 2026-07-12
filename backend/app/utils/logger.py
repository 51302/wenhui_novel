"""
文件日志系统：按天分文件 + 按级别分文件 + 7 天自动清理 + 日志轮询

日志文件位置：项目根目录 /backend/logs/
命名规则：
    info_20260712.log      - INFO 级别日志（正常请求、操作成功等）
    warning_20260712.log    - WARNING 级别日志（4xx 错误、登录失败等）
    error_20260712.log      - ERROR 级别日志（5xx 错误、AI 调用失败等）

轮询规则：每天自动切换到新日期的文件
清理规则：后台线程每 1 小时删除 7 天前的日志文件
线程安全：使用 threading.Lock 保证多线程并发写入不串行

用法：
    from app.utils.logger import system_logger
    system_logger.info("用户注册成功")
    system_logger.warning("登录失败: 密码错误")
    system_logger.error("AI 生成超时")
    today_errors = system_logger.error_count()  # wc 功能
"""
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


class SystemLogger:
    """
    文件日志管理器
    - 三级分类：INFO / WARNING / ERROR
    - 按天写入不同文件，自动跨天切换
    - 线程安全并发写入
    - 后台定时清理过期日志
    - 提供 wc / tail 等查询方法
    """

    def __init__(self, log_dir: str = "logs", keep_days: int = 7):
        """
        初始化日志系统
        :param log_dir:  日志文件夹路径
        :param keep_days: 日志保留天数，默认 7 天
        """
        self._log_dir = Path(log_dir)
        self._keep_days = keep_days
        self._lock = threading.Lock()  # 线程锁，保证写文件安全
        self._today = datetime.now().strftime("%Y%m%d")  # 当前日期字符串，用于判断跨天
        self._ensure_dir()
        self._start_cleanup_loop()
        # 不再打印控制台输出，所有日志仅写入文件

    # ========== 内部方法 ==========

    def _ensure_dir(self):
        """确保日志目录存在"""
        os.makedirs(self._log_dir, exist_ok=True)

    def _file_path(self, level: str, date_str: str = None) -> str:
        """
        生成日志文件路径
        格式：logs/info_20260712.log
        """
        date_str = date_str or self._today
        return os.path.join(self._log_dir, f"{level.lower()}_{date_str}.log")

    def _write(self, level: str, msg: str):
        """
        写入日志到文件（线程安全）
        自动检测跨天并切换文件
        """
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        # 跨天了 → 更新 _today，后续日志写入新文件
        if date_str != self._today:
            self._today = date_str

        line = f"[{timestamp}] [{level}] {msg}\n"
        filepath = self._file_path(level, date_str)

        # 加锁写文件，防止多线程并发写入导致内容交错
        with self._lock:
            try:
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass  # 写文件失败静默忽略，避免影响主业务流程

    # ========== 公开写日志方法 ==========

    def info(self, msg: str):
        """写入 INFO 级别日志（正常操作、请求成功等）"""
        self._write("INFO", msg)

    def warning(self, msg: str):
        """写入 WARNING 级别日志（业务异常、4xx 错误等）"""
        self._write("WARNING", msg)

    def error(self, msg: str):
        """写入 ERROR 级别日志（系统错误、5xx、AI 调用失败等）"""
        self._write("ERROR", msg)

    # ========== 日志查询方法 ==========

    def tail(self, level: str = "all", lines: int = 100, date_str: str = None) -> str:
        """
        读取最新 N 行日志（模拟 Linux tail -n 命令）
        :param level: info / warning / error / all（全部）
        :param lines: 读取行数
        :param date_str: 指定日期，默认今天
        :return: 日志文本
        """
        date_str = date_str or datetime.now().strftime("%Y%m%d")
        levels = ["info", "warning", "error"] if level == "all" else [level.lower()]
        all_lines = []
        for lv in levels:
            fp = self._file_path(lv, date_str)
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    all_lines.extend(f.readlines())
        all_lines.sort()
        return "".join(all_lines[-lines:])

    def error_count(self) -> int:
        """
        统计今日 ERROR 日志行数（等效 wc -l error_*.log）
        :return: 错误行数
        """
        fp = self._file_path("error")
        if os.path.exists(fp):
            with open(fp, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        return 0

    def error_count_since(self, minutes: int = 60) -> int:
        """
        统计最近 N 分钟内的 ERROR 日志数量
        用于监控告警：如果最近 5 分钟 ERROR > 10，可能需要排查
        :param minutes: 最近多少分钟
        :return: 错误数量
        """
        fp = self._file_path("error")
        if not os.path.exists(fp):
            return 0
        cutoff = datetime.now() - timedelta(minutes=minutes)
        count = 0
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                    if ts > cutoff:
                        count += 1
                except Exception:
                    continue
        return count

    def total_size(self) -> int:
        """
        统计日志文件夹总大小（字节）
        用于监控磁盘占用
        """
        total = 0
        for fname in os.listdir(self._log_dir):
            fpath = os.path.join(self._log_dir, fname)
            if os.path.isfile(fpath):
                total += os.path.getsize(fpath)
        return total

    # ========== 清理功能 ==========

    def cleanup(self, keep_days: int = None):
        """
        删除 N 天前的所有日志文件
        按文件修改时间判断，删除过期文件
        :param keep_days: 保留天数，默认使用初始化时的值
        """
        days = keep_days or self._keep_days
        cutoff = datetime.now() - timedelta(days=days)
        deleted = 0
        for fname in os.listdir(self._log_dir):
            fpath = os.path.join(self._log_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    os.remove(fpath)
                    deleted += 1
            except Exception:
                pass
        # 清理完成后写入一条日志（仅当有文件被删除时）
        if deleted > 0:
            self._write("INFO", f"日志清理完成: 已删除 {deleted} 个 {days} 天前日志文件")

    def _start_cleanup_loop(self):
        """
        启动后台清理线程
        每 1 小时执行一次清理，删除 7 天前的日志
        daemon=True 确保主进程退出时自动结束
        """

        def _loop():
            # 启动后先等 5 分钟再开始第一次清理（避免影响启动性能）
            time.sleep(300)
            while True:
                try:
                    self.cleanup()
                except Exception:
                    pass  # 清理异常静默忽略
                time.sleep(3600)  # 每小时执行一次

        t = threading.Thread(target=_loop, daemon=True)
        t.start()


# ==============================================================================
# 全局单例：所有模块统一使用 system_logger
# 日志文件存放在 backend/logs/ 目录
# ==============================================================================
_logs_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs",
)
system_logger = SystemLogger(log_dir=_logs_dir, keep_days=7)
