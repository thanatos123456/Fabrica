#!/usr/bin/env python3
"""Fabrica 日志系统。

基于 aurora/helios 框架，提供统一的日志记录能力。
支持控制台彩色输出和文件日志自动轮转。

特性：
- 控制台彩色输出（INFO 级别）
- 文件日志自动轮转（DEBUG 级别，10MB 轮转，7天保留）
- 按日期分目录存储
- 不同模块日志可通过 logger 名称区分
"""

import os
from typing import Any, Dict, Optional

from aurora.python.helios import (
    get_logger as _helios_get_logger,
    LogConfig,
)

# ============================================================================
# 路径与常量
# ============================================================================

# 通过 __file__ 相对路径计算日志目录
# __file__ 位于 nexus/Fabrica/fabrica/utils/logger.py
# 需向上两级到达项目根目录 nexus/Fabrica/
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_CURRENT_DIR)
_FABRICA_DIR = os.path.dirname(_PACKAGE_DIR)
LOG_DIR = os.path.join(_FABRICA_DIR, "data", "logs")

# 日志格式（T1.2 指定）
LOG_FORMAT = (
    "%(timestamp)s [%(level)s] %(logger)s: %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ============================================================================
# 日志配置
# ============================================================================

def _create_log_config() -> LogConfig:
    """创建 Fabrica 默认日志配置。

    配置两个 handler：
    - 控制台：INFO 级别，彩色输出
    - 文件：DEBUG 级别，10MB 轮转，7天保留

    Returns:
        LogConfig: 日志配置实例
    """
    return LogConfig(config_dict={
        "level": "DEBUG",
        "base_log_dir": LOG_DIR,
        "handlers": [
            {
                "type": "console",
                "level": "INFO",
                "format": "colored",
            },
            {
                "type": "file",
                "level": "DEBUG",
                "format": "text",
                "rotation": "10MB",
                "retention": "7d",
                "date_based_folders": True,
                "folder_date_format": "%Y-%m-%d",
                "filename_pattern": (
                    "fabrica_{date}_{level}_"
                    "{timestamp}{ext}"
                ),
                "filename_date_format": "%Y%m%d",
                "filename_timestamp_format": "%H%M%S.%f",
                "project_name": "fabrica",
                "date_format": DATE_FORMAT,
            },
        ],
        "format_string": LOG_FORMAT,
        "date_format": DATE_FORMAT,
        "project_name": "fabrica",
        "date_based_folders": True,
        "folder_date_format": "%Y-%m-%d",
        "filename_pattern": (
            "fabrica_{date}_{level}_{timestamp}{ext}"
        ),
        "filename_date_format": "%Y%m%d",
        "filename_timestamp_format": "%H%M%S.%f",
    })


# ============================================================================
# LoggerManager 类
# ============================================================================

class LoggerManager:
    """Fabrica 日志管理器。

    封装 aurora/helios 的 HeliosLogger，提供 Fabrica 统一的
    日志接口。支持控制台彩色输出和文件日志自动轮转。

    用法：
        from fabrica.utils import get_logger
        log = get_logger("fabrica.server")
        log.info("服务器启动")
    """

    _initialized = False

    def __init__(self, name: str = "fabrica"):
        """初始化日志管理器。

        Args:
            name: 日志器名称，用于区分不同模块。
        """
        self._name = name
        self._logger = _helios_get_logger(name)

        # 首次初始化时应用 Fabrica 配置
        if not LoggerManager._initialized:
            self._logger.update_config(_create_log_config())
            LoggerManager._initialized = True

    @staticmethod
    def _format_message(
        message: str, args: tuple,
    ) -> str:
        """按标准 logging 风格用位置参数格式化消息。

        Args:
            message: 日志消息，可含 % 占位符。
            args: 位置参数，用于填充占位符。

        Returns:
            str: 格式化后的消息。args 为空时原样返回。
        """
        if args:
            return message % args
        return message

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        """记录 DEBUG 级别日志。"""
        self._logger.debug(
            self._format_message(message, args), **kwargs
        )

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        """记录 INFO 级别日志。"""
        self._logger.info(
            self._format_message(message, args), **kwargs
        )

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        """记录 WARNING 级别日志。"""
        self._logger.warning(
            self._format_message(message, args), **kwargs
        )

    def error(
        self, message: str,
        *args: Any,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """记录 ERROR 级别日志。

        Args:
            message: 日志消息。
            exc_info: 是否包含异常堆栈信息。
        """
        self._logger.error(
            self._format_message(message, args),
            exc_info=exc_info, **kwargs
        )

    def critical(
        self, message: str,
        *args: Any,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """记录 CRITICAL 级别日志。

        Args:
            message: 日志消息。
            exc_info: 是否包含异常堆栈信息。
        """
        self._logger.critical(
            self._format_message(message, args),
            exc_info=exc_info, **kwargs
        )

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        """记录异常信息，自动包含堆栈跟踪。"""
        self._logger.exception(
            self._format_message(message, args), **kwargs
        )

    def get_log_file_path(self) -> Optional[str]:
        """获取当前日志文件路径。

        从 helios logger 的 handler 中查找文件处理器，
        返回其文件路径。

        Returns:
            日志文件路径，如果未找到则返回 None
        """
        for handler in self._logger.logger.handlers:
            # DateRotatingFileHandler 有 current_filename
            if (hasattr(handler, 'current_filename')
                    and handler.current_filename):
                return handler.current_filename
            # FileHandler 有 filename 属性
            if hasattr(handler, 'filename'):
                return handler.filename
        return None


# ============================================================================
# 模块级函数
# ============================================================================

def get_logger(name: str = "fabrica") -> LoggerManager:
    """获取指定名称的日志记录器。

    不同模块可通过不同的 name 区分日志来源，例如：
    - "fabrica.server" — 服务层日志
    - "fabrica.tools.video_dedup" — 工具层日志

    Args:
        name: 日志器名称，用于区分不同模块。

    Returns:
        LoggerManager: 日志管理器实例。
    """
    return LoggerManager(name)


def setup_logging(
    config: Optional[Dict[str, Any]] = None,
) -> LoggerManager:
    """初始化日志系统。

    在应用启动时调用，可传入自定义配置覆盖默认配置。

    Args:
        config: 自定义配置字典。如果为 None，
            则使用 Fabrica 默认配置。

    Returns:
        LoggerManager: 日志管理器实例。
    """
    manager = LoggerManager("fabrica")

    if config is not None:
        log_config = LogConfig(config_dict=config)
        manager._logger.update_config(log_config)

    return manager


# 默认日志器实例
logger = get_logger("fabrica")
