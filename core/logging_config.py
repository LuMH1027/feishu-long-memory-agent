"""日志配置模块"""
import logging
import os
import sys
from pathlib import Path


def setup_logging(log_level: str = None, log_file: str = None):
    """
    配置日志系统

    Args:
        log_level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_file: 日志文件路径（可选）
    """
    # 获取日志级别
    level = log_level or os.getenv("LOG_LEVEL", "INFO")
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = level_map.get(level.upper(), logging.INFO)

    # 创建根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除现有的处理器
    root_logger.handlers.clear()

    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器（如果指定了日志文件）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 设置第三方库的日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志器

    Args:
        name: 日志器名称

    Returns:
        日志器实例
    """
    return logging.getLogger(name)
