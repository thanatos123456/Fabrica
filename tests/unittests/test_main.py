"""入口文件与脚本测试模块。

测试目标：main.py（parse_args、_import_fabrica_modules）
         fabrica/app.py（create_app、根路由、健康检查）
"""

import os
import sys
import unittest
from unittest.mock import patch

# 确保 main.py 所在目录在 sys.path 中
_FABRICA_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _FABRICA_ROOT not in sys.path:
    sys.path.insert(0, _FABRICA_ROOT)

# 导入 main 模块（main.py 在 Fabrica 根目录下）
import main as main_module
from fabrica import create_app, __version__


# ============================================================================
# parse_args 测试
# ============================================================================

class TestParseArgs(unittest.TestCase):
    """parse_args 函数测试集。"""

    def test_default_args(self):
        """默认参数应正确。"""
        with patch("sys.argv", ["main.py"]):
            args = main_module.parse_args()
            self.assertIsNone(args.host)
            self.assertIsNone(args.port)
            self.assertEqual(args.log_level, "info")

    def test_custom_host(self):
        """自定义 host 应正确解析。"""
        with patch("sys.argv", ["main.py", "--host", "0.0.0.0"]):
            args = main_module.parse_args()
            self.assertEqual(args.host, "0.0.0.0")

    def test_custom_port(self):
        """自定义 port 应正确解析。"""
        with patch("sys.argv", ["main.py", "--port", "9000"]):
            args = main_module.parse_args()
            self.assertEqual(args.port, 9000)

    def test_log_level_choices(self):
        """日志级别 choices 应正确解析。"""
        with patch("sys.argv", ["main.py", "--log-level", "debug"]):
            args = main_module.parse_args()
            self.assertEqual(args.log_level, "debug")

    def test_invalid_log_level_raises(self):
        """无效日志级别应抛出 SystemExit。"""
        with patch("sys.argv", ["main.py", "--log-level", "invalid"]):
            with self.assertRaises(SystemExit):
                main_module.parse_args()


# ============================================================================
# _import_fabrica_modules 测试
# ============================================================================

class TestImportFabricaModules(unittest.TestCase):
    """_import_fabrica_modules 函数测试集。"""

    def test_returns_all_modules(self):
        """应返回 8 个模块对象。"""
        result = main_module._import_fabrica_modules()
        self.assertEqual(len(result), 8)

    def test_create_app_importable(self):
        """create_app 应可调用。"""
        result = main_module._import_fabrica_modules()
        create_app_func = result[0]
        self.assertTrue(callable(create_app_func))

    def test_version_importable(self):
        """__version__ 应为字符串。"""
        result = main_module._import_fabrica_modules()
        version = result[1]
        self.assertIsInstance(version, str)


# ============================================================================
# create_app 测试（FastAPI 应用工厂）
# ============================================================================

class TestAppFactory(unittest.TestCase):
    """create_app 应用工厂测试集。"""

    def test_create_app_returns_fastapi(self):
        """应返回 FastAPI 实例。"""
        from fastapi import FastAPI
        app = create_app()
        self.assertIsInstance(app, FastAPI)

    def test_root_route(self):
        """根路由应返回平台信息。"""
        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Fabrica")
        self.assertIn("version", data)
        self.assertEqual(data["status"], "running")

    def test_health_route(self):
        """健康检查端点应返回 ok。"""
        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")


if __name__ == "__main__":
    unittest.main()
