import logging
import sys
from logging.handlers import RotatingFileHandler

# 定义一个所有脚本共享的日志格式
# !! 这个格式必须与 web_app.py 中的正则表达式匹配 !!
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

def setup_logging(log_file='pipeline.log', level=logging.INFO):
    """
    为任务脚本配置日志。
    会将日志同时输出到控制台 (stdout) 和文件。
    """
    # 获取根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 防止重复添加 handler
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 1. 配置 StreamHandler，用于将日志输出到控制台
    # web_app.py 会捕获这个输出
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(stream_handler)

    # 2. 配置 RotatingFileHandler，用于将日志写入文件
    # 'maxBytes=10*1024*1024' = 10MB, 'backupCount=50' 保留50个备份文件
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=50, encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG) # 文件中可以记录更详细的 DEBUG 信息
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)

    logging.info(f"日志系统已配置完成，日志将输出到控制台和文件 '{log_file}'。")