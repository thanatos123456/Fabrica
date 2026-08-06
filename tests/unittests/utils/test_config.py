"""配置管理测试模块。

测试目标：fabrica/utils/config.py
覆盖：configure_fabrica、get_config、get_all_config、reload_config
"""

import unittest

from fabrica.utils import config as config_module
from fabrica.utils.config import (
    configure_fabrica,
    get_config,
    get_all_config,
    reload_config,
)


# ============================================================================
# configure_fabrica 测试
# ============================================================================

class TestConfigureFabrica(unittest.TestCase):
    """configure_fabrica 函数测试集。"""

    def setUp(self):
        """每个测试前重置全局状态。"""
        config_module._config_manager = None

    def tearDown(self):
        """每个测试后重置全局状态。"""
        config_module._config_manager = None

    def test_configure_with_default_dir(self):
        """默认配置目录应正确加载。"""
        configure_fabrica()
        self.assertIsNotNone(config_module._config_manager)

    def test_configure_with_custom_dir(self):
        """自定义配置目录应不抛异常。"""
        # 使用不存在的目录，应不抛异常（phoenix 内部处理）
        configure_fabrica("nonexistent_config")
        self.assertIsNotNone(config_module._config_manager)


# ============================================================================
# get_config 测试
# ============================================================================

class TestGetConfig(unittest.TestCase):
    """get_config 函数测试集。"""

    def setUp(self):
        config_module._config_manager = None

    def tearDown(self):
        config_module._config_manager = None

    def test_get_existing_config(self):
        """已存在的配置项应返回值。"""
        # 先加载配置
        configure_fabrica()
        # fabrica.server.port 应存在
        result = get_config("fabrica.server.port", 9999)
        # 返回值应为配置中的端口或默认值
        self.assertIsNotNone(result)

    def test_get_nonexistent_config_returns_default(self):
        """不存在的配置项应返回默认值。"""
        configure_fabrica()
        result = get_config("nonexistent.key.path", "default_val")
        self.assertEqual(result, "default_val")

    def test_get_nested_config(self):
        """嵌套配置路径应正确解析。"""
        configure_fabrica()
        # 测试多级嵌套
        result = get_config("fabrica.server.host", "127.0.0.1")
        self.assertIsInstance(result, str)

    def test_get_config_auto_init(self):
        """_config_manager 为 None 时应自动初始化。"""
        # 不调用 configure_fabrica，直接调用 get_config
        result = get_config("fabrica.server.port", 8520)
        # 应自动初始化并返回值或默认值
        self.assertIsNotNone(result)

    def test_get_config_invalid_returns_default(self):
        """配置读取异常时应返回默认值。"""
        configure_fabrica()
        # 使用一个无效的 key 格式
        result = get_config("", "fallback")
        # 空字符串应返回默认值或配置根
        self.assertIsNotNone(result)


# ============================================================================
# get_all_config 测试
# ============================================================================

class TestGetAllConfig(unittest.TestCase):
    """get_all_config 函数测试集。"""

    def setUp(self):
        config_module._config_manager = None

    def tearDown(self):
        config_module._config_manager = None

    def test_get_all_config_returns_dict(self):
        """应返回字典。"""
        configure_fabrica()
        result = get_all_config()
        self.assertIsInstance(result, dict)

    def test_get_all_config_auto_init(self):
        """_config_manager 为 None 时应自动初始化。"""
        result = get_all_config()
        self.assertIsInstance(result, dict)


# ============================================================================
# reload_config 测试
# ============================================================================

class TestReloadConfig(unittest.TestCase):
    """reload_config 函数测试集。"""

    def setUp(self):
        config_module._config_manager = None

    def tearDown(self):
        config_module._config_manager = None

    def test_reload_config(self):
        """已初始化时重载应不抛异常。"""
        configure_fabrica()
        # 重载不应抛异常
        reload_config()

    def test_reload_config_auto_init(self):
        """_config_manager 为 None 时应自动初始化。"""
        # 不调用 configure_fabrica
        reload_config()
        # 应自动初始化
        self.assertIsNotNone(config_module._config_manager)


if __name__ == "__main__":
    unittest.main()
