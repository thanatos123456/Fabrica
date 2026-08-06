"""WebSocket 实时推送端点测试。

测试目标：fabrica/server/routes.py 的 WS /api/ws/tasks/{task_id}
覆盖：连接确认、进度/日志/完成/错误事件推送、心跳 ping→pong、
任务不存在时拒绝连接、断开后回调注销。

事件触发方式：连接建立后 WebSocket 端点在 registry 上注册回调，
测试直接调用 registry._fire_callback(...) 触发，隔离真实工具执行。
"""

import json
import unittest

# 先导入 tests.unittests 包以触发 aurora 路径注入，再导入 fabrica 模块。
from tests.unittests.server.fixtures import (
    DummyTool,
    fresh_registry,
    reset_registry,
)

from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient

from fabrica.server import create_app


class TestWebSocket(unittest.TestCase):
    """WebSocket 端点测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(DummyTool)
        self.app = create_app(
            {"server": {"cors_origins": ["*"], "static_dir": "server/static"}},
            self.registry,
        )
        self.client = TestClient(self.app)
        # 创建任务：后台任务在 TestClient 下不推进，但任务记录存在，
        # 供 WebSocket 校验连接与回调绑定。
        self.task_id = self.registry.run_tool("dummy", {})

    def tearDown(self):
        self.client.close()
        reset_registry(self.registry)

    def _connect(self):
        """建立并进入 WebSocket 连接上下文，消费连接确认事件。"""
        ws = self.client.websocket_connect(
            f"/api/ws/tasks/{self.task_id}"
        ).__enter__()
        first = ws.receive_json()
        self.assertEqual(first["type"], "connected")
        return ws

    def test_receives_connected(self):
        """连接已存在任务应收到 connected 事件。"""
        ws = self._connect()
        ws.__exit__(None, None, None)

    def test_receives_progress(self):
        """触发进度回调应收到 progress 事件。"""
        ws = self._connect()
        try:
            self.registry._fire_callback(
                self.task_id, "progress", (50, "处理中")
            )
            event = ws.receive_json()
            self.assertEqual(event["type"], "progress")
            self.assertEqual(event["percent"], 50)
            self.assertEqual(event["message"], "处理中")
        finally:
            ws.__exit__(None, None, None)

    def test_receives_log(self):
        """触发日志回调应收到 log 事件。"""
        ws = self._connect()
        try:
            self.registry._fire_callback(
                self.task_id, "log", ("info", "hello")
            )
            event = ws.receive_json()
            self.assertEqual(event["type"], "log")
            self.assertEqual(event["level"], "info")
            self.assertEqual(event["message"], "hello")
        finally:
            ws.__exit__(None, None, None)

    def test_ping_pong(self):
        """发送 ping 应收到 pong。"""
        ws = self._connect()
        try:
            ws.send_text(json.dumps({"type": "ping"}))
            event = ws.receive_json()
            self.assertEqual(event["type"], "pong")
        finally:
            ws.__exit__(None, None, None)

    def test_receives_complete(self):
        """触发完成回调应收到 complete 事件。"""
        ws = self._connect()
        try:
            self.registry._fire_callback(
                self.task_id, "complete", {"ok": True}
            )
            event = ws.receive_json()
            self.assertEqual(event["type"], "complete")
            self.assertEqual(event["result"], {"ok": True})
        finally:
            ws.__exit__(None, None, None)

    def test_receives_error(self):
        """触发错误回调应收到 error 事件。"""
        ws = self._connect()
        try:
            self.registry._fire_callback(
                self.task_id, "error", "boom"
            )
            event = ws.receive_json()
            self.assertEqual(event["type"], "error")
            self.assertEqual(event["error"], "boom")
        finally:
            ws.__exit__(None, None, None)

    def test_nonexistent_task_rejected(self):
        """连接不存在的任务应被服务端拒绝（断开）。"""
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/ws/tasks/nonexistent"
            ):
                pass

    def test_disconnect_unregisters_callbacks(self):
        """客户端断开后回调应从 registry 注销。"""
        ws = self._connect()
        callbacks = self.registry._callbacks.get(self.task_id, {})
        self.assertIn("progress", callbacks)
        ws.__exit__(None, None, None)
        # 退出连接后服务端 finally 注销回调
        callbacks = self.registry._callbacks.get(self.task_id, {})
        self.assertNotIn("progress", callbacks)
        self.assertNotIn("log", callbacks)
        self.assertNotIn("complete", callbacks)
        self.assertNotIn("error", callbacks)


if __name__ == "__main__":
    unittest.main()