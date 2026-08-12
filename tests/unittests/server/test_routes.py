"""REST API 路由测试。

测试目标：fabrica/server/routes.py 的 7 个 REST 端点
覆盖：工具列表/详情/执行、任务历史/详情/取消/删除，
以及工具/任务不存在的 404 错误路径。
"""

import unittest
from unittest.mock import patch

# 先导入 tests.unittests 包以触发 aurora 路径注入，再导入 fabrica 模块。
from tests.unittests.server.fixtures import (
    DemoTool,
    DummyTool,
    fresh_registry,
    reset_registry,
)

from fastapi.testclient import TestClient

from fabrica.server import create_app

# 期望的 10 种参数类型全集（与 ParamDefSchema 的定义一致）
PARAM_TYPES = {
    "str", "int", "float", "bool", "path", "file",
    "dir", "select", "multi_select", "password",
}


class TestRoutes(unittest.TestCase):
    """REST API 路由测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(DummyTool)
        self.registry.register(DemoTool)
        self.app = create_app(
            {"server": {"cors_origins": ["*"], "static_dir": "server/static"}},
            self.registry,
        )
        # 全局异常处理器走 ServerErrorMiddleware 路径，TestClient 默认会
        # re-raise 被捕获的异常；设为 False 以返回处理器生成的响应。
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        reset_registry(self.registry)

    # ------------------------------------------------------------------
    # 工具端点
    # ------------------------------------------------------------------

    def test_list_tools_with_registered_tools(self):
        """注册工具后 GET /api/tools 应返回工具列表。"""
        resp = self.client.get("/api/tools")
        self.assertEqual(resp.status_code, 200)
        names = {t["name"] for t in resp.json()}
        self.assertEqual(names, {"dummy", "demo"})

    def test_get_tool_detail_with_params(self):
        """GET /api/tools/demo 应返回含 10 种参数类型的详情。"""
        resp = self.client.get("/api/tools/demo")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "demo")
        types = {p["type"] for p in data["params"]}
        self.assertEqual(types, PARAM_TYPES)

    def test_get_tool_not_found(self):
        """GET /api/tools/nonexistent 应返回 404 TOOL_NOT_FOUND。"""
        resp = self.client.get("/api/tools/nonexistent")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error_code"], "TOOL_NOT_FOUND")

    def test_run_tool_returns_task_id(self):
        """POST /api/tools/dummy/run 应返回 task_id 与 pending 状态。"""
        resp = self.client.post(
            "/api/tools/dummy/run", json={"params": {}}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["task_id"])
        self.assertEqual(data["status"], "pending")

    def test_run_tool_not_found(self):
        """POST /api/tools/nonexistent/run 应返回 404。"""
        resp = self.client.post(
            "/api/tools/nonexistent/run", json={"params": {}}
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error_code"], "TOOL_NOT_FOUND")

    # ------------------------------------------------------------------
    # 任务端点
    # ------------------------------------------------------------------

    def _create_task(self, tool="dummy"):
        """提交一个工具执行任务，返回 task_id。"""
        resp = self.client.post(
            f"/api/tools/{tool}/run", json={"params": {"k": "v"}}
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["task_id"]

    def test_list_tasks_empty(self):
        """无任务时 GET /api/tasks 应返回空列表。"""
        resp = self.client.get("/api/tasks")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_list_tasks_after_run(self):
        """提交任务后 GET /api/tasks 应包含该任务。"""
        task_id = self._create_task()
        resp = self.client.get("/api/tasks")
        self.assertEqual(resp.status_code, 200)
        ids = [t["task_id"] for t in resp.json()]
        self.assertIn(task_id, ids)

    def test_get_task_detail(self):
        """GET /api/tasks/{id} 应返回任务详情（不依赖终态）。"""
        task_id = self._create_task()
        resp = self.client.get(f"/api/tasks/{task_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["task_id"], task_id)
        self.assertEqual(data["tool_name"], "dummy")
        self.assertEqual(data["params"], {"k": "v"})
        self.assertIn("status", data)

    def test_get_task_not_found(self):
        """GET /api/tasks/nonexistent 应返回 404 TASK_NOT_FOUND。"""
        resp = self.client.get("/api/tasks/nonexistent")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error_code"], "TASK_NOT_FOUND")

    def test_cancel_task(self):
        """POST /api/tasks/{id}/cancel 应返回 cancelled=True。"""
        task_id = self._create_task()
        resp = self.client.post(f"/api/tasks/{task_id}/cancel")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"task_id": task_id, "cancelled": True})

    def test_cancel_task_not_found(self):
        """取消不存在的任务应返回 404。"""
        resp = self.client.post("/api/tasks/nonexistent/cancel")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error_code"], "TASK_NOT_FOUND")

    def test_delete_task(self):
        """DELETE /api/tasks/{id} 应返回 deleted=True。"""
        task_id = self._create_task()
        resp = self.client.delete(f"/api/tasks/{task_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {"task_id": task_id, "deleted": True})

    def test_delete_task_not_found(self):
        """删除不存在的任务应返回 404。"""
        resp = self.client.delete("/api/tasks/nonexistent")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error_code"], "TASK_NOT_FOUND")

    def test_cleanup_tasks(self):
        """POST /api/tasks/cleanup 应返回清理计数。"""
        with patch.object(
            self.registry, "cleanup_orphans",
            return_value={"keyframes": 3, "features": 5, "output": 1},
        ):
            resp = self.client.post("/api/tasks/cleanup")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {"cleaned": {"keyframes": 3, "features": 5, "output": 1}},
        )


if __name__ == "__main__":
    unittest.main()