import os
import sys
from loguru import logger

# 创建日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 移除默认的控制台输出，以便我们自定义格式
logger.remove()

# 自定义日志格式
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# 添加标准输出（带颜色）
logger.add(
    sys.stdout, 
    format=LOG_FORMAT, 
    level="INFO",
    colorize=True
)

# 添加文件输出（按天切割，保留30天，发生错误时记录完整堆栈）
logger.add(
    os.path.join(LOG_DIR, "app.log"),
    rotation="00:00",      # 每天午夜切割
    retention="30 days",   # 保留 30 天
    format=LOG_FORMAT,
    level="DEBUG",         # 文件中保存更详细的信息
    encoding="utf-8",
    enqueue=True,          # 异步安全，防止多线程阻塞
    backtrace=True,        # 记录完整的堆栈信息
    diagnose=True          # 包含变量值，极大方便调试
)

__all__ = ["logger"]
