import sys
import logging
from pathlib import Path

def setup_logging(log_file: Path, level=logging.INFO):
    """
    配置全局日志。
    :param log_file: 日志文件路径 (Path对象)
    :param level: 日志级别
    """
    # 确保日志目录存在
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 创建 Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Root Logger 设置
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 清除旧的 handler 防止重复打印
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # File Handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 屏蔽一些啰嗦的第三方库日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)