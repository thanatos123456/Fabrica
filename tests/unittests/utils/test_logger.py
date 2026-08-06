"""日志模块测试。

测试目标：fabrica/utils/logger.py
覆盖：LoggerManager 类、get_logger、setup_logging、_create_log_config
"""

import unittest
from unittest.mock import patch, MagicMock

from fabrica.utils.logger import (
    LoggerManager,
    get_logger,
    setup_logging,
    _create_log_config,
)
from aurora.python.helios import LogConfig


# ============================================================================
# LoggerManager 测试
# ============================================================================

class TestLoggerManager(unittest.TestCase):
    """LoggerManager 类测试集。"""

    def setUp(self):
        """重置类级状态。"""
        LoggerManager._initialized = False

    def tearDown(self):
        """测试后重置类级状态。"""
        LoggerManager._initialized = False

    def test_init_with_default_name(self):
        """默认名称应为 'fabrica'。"""
        manager = LoggerManager()
        self.assertEqual(manager._name, "fabrica")

    def test_init_with_custom_name(self):
        """自定义名称应正确设置。"""
        manager = LoggerManager("custom.module")
        self.assertEqual(manager._name, "custom.module")

    def test_debug_logging(self):
        """debug 方法应不抛异常。"""
        manager = LoggerManager("test.debug")
        manager.debug("debug message")

    def test_info_logging(self):
        """info 方法应不抛异常。"""
        manager = LoggerManager("test.info")
        manager.info("info message")

    def test_warning_logging(self):
        """warning 方法应不抛异常。"""
        manager = LoggerManager("test.warning")
        manager.warning("warning message")

    def test_error_logging(self):
        """error 方法应不抛异常。"""
        manager = LoggerManager("test.error")
        manager.error("error message")

    def test_error_with_exc_info(self):
        """error 方法带 exc_info 应不抛异常。"""
        manager = LoggerManager("test.exc")
        try:
            raise ValueError("test")
        except ValueError:
            manager.error("error with trace", exc_info=True)

    def test_critical_logging(self):
        """critical 方法应不抛异常。"""
        manager = LoggerManager("test.critical")
        manager.critical("critical message")

    def test_exception_logging(self):
        """exception 方法应不抛异常。"""
        manager = LoggerManager("test.exception")
        try:
            raise RuntimeError("test")
        except RuntimeError:
            manager.exception("exception occurred")

    def test_get_log_file_path(self):
        """get_log_file_path 应返回路径或 None。"""
        manager = LoggerManager("test.filepath")
        result = manager.get_log_file_path()
        # 返回值应为字符串或 None
        self.assertTrue(result is None or isinstance(result, str))

    def test_get_log_file_path_none(self):
        """无文件处理器时应返回 None。"""
        manager = LoggerManager("test.nofile")
        # Mock handlers 为空列表
        manager._logger.logger.handlers = []
        result = manager.get_log_file_path()
        self.assertIsNone(result)


# ============================================================================
# get_logger 测试
# ============================================================================

class TestGetLogger(unittest.TestCase):
    """get_logger 函数测试集。"""

    def test_default_logger(self):
        """默认日志器名称应为 'fabrica'。"""
        manager = get_logger()
        self.assertIsInstance(manager, LoggerManager)
        self.assertEqual(manager._name, "fabrica")

    def test_custom_name_logger(self):
        """自定义名称应正确设置。"""
        manager = get_logger("custom.logger")
        self.assertEqual(manager._name, "custom.logger")


# ============================================================================
# setup_logging 测试
# ============================================================================

class TestSetupLogging(unittest.TestCase):
    """setup_logging 函数测试集。"""

    def setUp(self):
        LoggerManager._initialized = False

    def tearDown(self):
        LoggerManager._initialized = False

    def test_setup_with_default_config(self):
        """默认配置应返回 LoggerManager 实例。"""
        manager = setup_logging()
        self.assertIsInstance(manager, LoggerManager)

    def test_setup_with_custom_config(self):
        """自定义配置应不抛异常。"""
        custom_config = {
            "level": "INFO",
            "base_log_dir": "/tmp/fabrica_test_logs",
            "handlers": [
                {
                    "type": "console",
                    "level": "INFO",
                    "format": "text",
                },
            ],
        }
        manager = setup_logging(config=custom_config)
        self.assertIsInstance(manager, LoggerManager)


# ============================================================================
# _create_log_config 测试（私有方法）
# ============================================================================

class TestCreateLogConfig(unittest.TestCase):
    """_create_log_config 私有方法测试集。"""

    def test_create_log_config_returns_config(self):
        """应返回 LogConfig 实例。"""
        config = _create_log_config()
        self.assertIsInstance(config, LogConfig)

    def test_config_has_console_handler(self):
        """配置应包含控制台 handler。"""
        config = _create_log_config()
        handlers = config.config.get("handlers", [])
        console_handlers = [
            h for h in handlers if h.get("type") == "console"
        ]
        self.assertGreaterEqual(len(console_handlers), 1)

    def test_config_has_file_handler(self):
        """配置应包含文件 handler。"""
        config = _create_log_config()
        handlers = config.config.get("handlers", [])
        file_handlers = [
            h for h in handlers if h.get("type") == "file"
        ]
        self.assertGreaterEqual(len(file_handlers), 1)


if __name__ == "__main__":
    unittest.main()
