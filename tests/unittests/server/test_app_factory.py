"""create_app 应用工厂测试。

测试目标：fabrica/server/__init__.py 中的 create_app()
覆盖：FastAPI 实例、CORS 中间件、静态资源挂载、API 路由挂接、
状态绑定、配置分支、静态目录缺失容错、根/健康检查端点。
"""

import os
import tempfile
import unittest
from unittest import mock

# 先导入 tests.unittests 包以触发 aurora 路径注入，再导入 fabrica 模块。
from tests.unittests.server.fixtures import (
    DemoTool,
    DummyTool,
    ParamTool,
    fresh_registry,
    reset_registry,
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import Mount
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from fabrica.server import create_app


class TestCreateApp(unittest.TestCase):
    """create_app 应用工厂测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(DummyTool)
        self.registry.register(ParamTool)
        self.registry.register(DemoTool)

    def tearDown(self):
        reset_registry(self.registry)

    def test_returns_fastapi_instance(self):
        """create_app 应返回 FastAPI 实例。"""
        app = create_app(tool_registry=self.registry)
        self.assertIsInstance(app, FastAPI)

    def test_cors_middleware_registered(self):
        """应注册 CORS 中间件。"""
        app = create_app(tool_registry=self.registry)
        cors = [
            m for m in app.user_middleware if m.cls is CORSMiddleware
        ]
        self.assertEqual(len(cors), 1)

    def test_cors_origins_from_config(self):
        """传入 config 时 cors_origins 应生效。"""
        app = create_app(
            {"server": {"cors_origins": ["https://a.example"],
                        "static_dir": "server/static"}},
            self.registry,
        )
        cors = [
            m for m in app.user_middleware if m.cls is CORSMiddleware
        ][0]
        self.assertEqual(cors.kwargs["allow_origins"],
                         ["https://a.example"])

    def test_static_mount_registered(self):
        """应挂载 /static 静态资源目录。"""
        app = create_app(tool_registry=self.registry)
        mounts = [
            r for r in app.routes
            if isinstance(r, Mount) and getattr(r, "path", None) == "/static"
        ]
        self.assertEqual(len(mounts), 1)
        self.assertIsInstance(mounts[0].app, StaticFiles)

    def test_api_routes_registered(self):
        """应挂接 /api 前缀路由（含 /api/tools）。"""
        app = create_app(tool_registry=self.registry)
        paths = [getattr(r, "path", None) for r in app.routes]
        self.assertIn("/api/tools", paths)
        self.assertIn("/api/tasks", paths)

    def test_state_binds_registry(self):
        """app.state.tool_registry 应绑定传入的注册中心。"""
        app = create_app(tool_registry=self.registry)
        self.assertIs(app.state.tool_registry, self.registry)

    def test_state_falls_back_to_singleton(self):
        """未传 tool_registry 时应回退到全局单例。"""
        app = create_app()
        self.assertIsNotNone(app.state.tool_registry)

    def test_missing_static_dir_no_crash(self):
        """静态目录不存在时应用仍应创建成功并跳过挂载。"""
        app = create_app(
            {"server": {"cors_origins": ["*"],
                        "static_dir": "no/such/dir"}},
            self.registry,
        )
        mounts = [
            r for r in app.routes
            if isinstance(r, Mount) and getattr(r, "path", None) == "/static"
        ]
        self.assertEqual(mounts, [])

    def test_root_endpoint(self):
        """GET / 应返回平台欢迎信息。"""
        app = create_app(tool_registry=self.registry)
        with TestClient(app) as client:
            resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "Fabrica")
        self.assertEqual(data["status"], "running")

    def test_health_endpoint(self):
        """GET /health 应返回 ok。"""
        app = create_app(tool_registry=self.registry)
        with TestClient(app) as client:
            resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_keyframes_mount_created_when_dir_missing(self):
        """关键帧目录不存在时也应创建并挂载 /keyframes。"""
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "keyframes")
            with mock.patch(
                "fabrica.tools.video_dedup.storage.DEFAULT_KEYFRAME_DIR",
                missing,
            ):
                app = create_app(tool_registry=self.registry)
            mounts = [
                r for r in app.routes
                if isinstance(r, Mount)
                and getattr(r, "path", None) == "/keyframes"
            ]
            self.assertEqual(len(mounts), 1)
            self.assertIsInstance(mounts[0].app, StaticFiles)
            self.assertEqual(mounts[0].app.directory, missing)
            self.assertTrue(os.path.isdir(missing))
            # 写入图片后应能通过 HTTP 访问
            os.makedirs(os.path.join(missing, "abc"), exist_ok=True)
            with open(os.path.join(missing, "abc", "f.jpg"), "wb") as fh:
                fh.write(b"\xff\xd8\xff\xe0fakejpeg")
            with TestClient(app) as client:
                resp = client.get("/keyframes/abc/f.jpg")
            self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()