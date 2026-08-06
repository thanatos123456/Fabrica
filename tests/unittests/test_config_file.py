"""配置文件加载测试模块。

测试目标：config/config.yaml 文件加载验证
覆盖：配置文件存在性、YAML 格式正确性、各配置段加载
"""

import os
import sys
import types
import unittest

import yaml

# ============================================================================
# 路径注入（确保 aurora 可导入）
# ============================================================================
# tests/unittests/test_config_file.py → 3 层 dirname → Fabrica/
_FABRICA_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_NEXUS_ROOT = os.path.dirname(_FABRICA_ROOT)
_OMNPIPIVOT_ROOT = os.path.dirname(_NEXUS_ROOT)
_AURORA_PATH = os.path.join(_OMNPIPIVOT_ROOT, "aurora", "python")
_AURORA_ROOT = os.path.join(_OMNPIPIVOT_ROOT, "aurora")

if os.path.isdir(_AURORA_PATH) and _AURORA_PATH not in sys.path:
    sys.path.insert(0, _AURORA_PATH)
if _FABRICA_ROOT not in sys.path:
    sys.path.insert(0, _FABRICA_ROOT)

# 创建虚拟 aurora 包
if "aurora" not in sys.modules:
    _aurora_pkg = types.ModuleType("aurora")
    _aurora_pkg.__path__ = [_AURORA_ROOT]
    sys.modules["aurora"] = _aurora_pkg
if "aurora.python" not in sys.modules:
    _aurora_python_pkg = types.ModuleType("aurora.python")
    _aurora_python_pkg.__path__ = [_AURORA_PATH]
    sys.modules["aurora.python"] = _aurora_python_pkg

# 修正 nemesis 别名
try:
    import aurora.python.nemesis as _nemesis
    if not hasattr(_nemesis, "NemesisBaseException"):
        if hasattr(_nemesis, "NemesisException"):
            _nemesis.NemesisBaseException = _nemesis.NemesisException
        elif hasattr(_nemesis, "BaseException"):
            _nemesis.NemesisBaseException = _nemesis.BaseException
except ImportError:
    pass

from fabrica.utils import config as config_module
from fabrica.utils.config import configure_fabrica, get_config


# ============================================================================
# 路径常量
# ============================================================================

_CONFIG_FILE = os.path.join(_FABRICA_ROOT, "config", "config.yaml")


# ============================================================================
# 配置文件加载测试
# ============================================================================

class TestConfigFileLoading(unittest.TestCase):
    """配置文件加载测试集。"""

    def setUp(self):
        """每个测试前重置全局状态。"""
        config_module._config_manager = None

    def tearDown(self):
        """每个测试后重置全局状态。"""
        config_module._config_manager = None

    def test_config_file_exists(self):
        """config.yaml 文件应存在。"""
        self.assertTrue(
            os.path.exists(_CONFIG_FILE),
            f"配置文件不存在: {_CONFIG_FILE}",
        )

    def test_config_file_valid_yaml(self):
        """config.yaml 应为有效 YAML 格式。"""
        with open(_CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f)
        self.assertIsInstance(data, dict)

    def test_configure_fabrica_loads_config(self):
        """configure_fabrica 应成功加载配置。"""
        configure_fabrica()
        self.assertIsNotNone(config_module._config_manager)

    def test_server_config_loaded(self):
        """server 配置段应正确加载。"""
        configure_fabrica()
        # 直接从文件读取验证
        with open(_CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f)
        # 检查 fabrica.server 段存在
        self.assertIn("fabrica", data)
        self.assertIn("server", data["fabrica"])

    def test_logging_config_loaded(self):
        """logging 配置段应正确加载。"""
        with open(_CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f)
        self.assertIn("logging", data.get("fabrica", {}))

    def test_storage_config_loaded(self):
        """storage 配置段应正确加载。"""
        with open(_CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f)
        self.assertIn("storage", data.get("fabrica", {}))


if __name__ == "__main__":
    unittest.main()
