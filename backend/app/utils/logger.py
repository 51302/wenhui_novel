"""
文件日志系统：按天分文件 + 按级别分文件 + 7天自动清理 + 轮询
日志文件格式：logs/info_20260712.log  logs/warning_20260712.log  logs/error_20260712.log
"""
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


class SystemLogger:
    """文件日志管理器：INFO / WARNING / ERROR 三级，按天分文件，7天自动清理"""

    def __init__(self, log_dir: str = "logs", keep_days: int = 7):
        self._log_dir = Path(log_dir)
        self._keep_days = keep_days
        self._lock = threading.Lock()
        self._today = datetime.now().strftime("%Y%m%d")
        self._ensure_dir()
        self._start_cleanup_loop()

    # ---- 内部 ----
    def _ensure_dir(self):
        os.makedirs(self._log_dir, exist_ok=True)

    def _file_path(self, level: str, date_str: str = None) -> str:
        date_str = date_str or self._today
        return os.path.join(self._log_dir, f"{level.lower()}_{date_str}.log")

    def _write(self, level: str, msg: str):
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        # 跨天了换日期
        if date_str != self._today:
            self._today = date_str

        line = f"[{timestamp}] [{level}] {msg}\n"
        filepath = self._file_path(level, date_str)

        with self._lock:
            try:
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                print(f"[日志写入失败] {filepath}: {e}")

    # ---- 公开方法 ----
    def info(self, msg: str):
        self._write("INFO", msg)

    def warning(self, msg: str):
        self._write("WARNING", msg)

    def error(self, msg: str):
        self._write("ERROR", msg)

    # ---- 读取 ----
    def tail(self, level: str = "all", lines: int = 100, date_str: str = None) -> str:
        """
        读最新 N 行（模拟 tail -n）
        level: info / warning / error / all
        """
        date_str = date_str or datetime.now().strftime("%Y%m%d")
        levels = ["info", "warning", "error"] if level == "all" else [level.lower()]
        all_lines = []
        for lv in levels:
            fp = self._file_path(lv, date_str)
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    all_lines.extend(f.readlines())
        all_lines.sort()  # 按时间排序
        return "".join(all_lines[-lines:])

    def error_count(self) -> int:
        """今日 ERROR 日志行数（wc 功能）"""
        fp = self._file_path("error")
        if os.path.exists(fp):
            with open(fp, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        return 0

    def error_count_since(self, minutes: int = 60) -> int:
        """最近 N 分钟内的 ERROR 数量"""
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

    # ---- 清理 ----
    def cleanup(self, keep_days: int = None):
        """删除 N 天前的日志文件"""
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
        if deleted > 0:
            print(f"[日志清理] 已删除 {deleted} 个 {days} 天前日志文件")

    def _start_cleanup_loop(self):
        """后台线程：每小时清理一次"""

        def _loop():
            while True:
                time.sleep(3600)
                try:
                    self.cleanup()
                except Exception as e:
                    print(f"[日志定时清理异常] {e}")

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        print(f"[日志] 文件日志系统已启动 → {self._log_dir.absolute()}")
        print(f"[日志] 后台定时清理已启动（每1小时清理{self._keep_days}天前日志）")


# 全局单例
_logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
system_logger = SystemLogger(log_dir=_logs_dir, keep_days=7)
