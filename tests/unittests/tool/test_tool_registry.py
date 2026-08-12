"""ToolRegistry 工具注册中心测试。

测试目标：fabrica/tool.py 中的 ToolRegistry 类
覆盖：单例、注册、发现、查询、任务执行、取消、回调
"""

import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from fabrica.tool import ToolRegistry, TaskStatus, TaskStateMachine

from tests.unittests.tool.fixtures import (
    CancellableTool,
    CleanupTool,
    CpuTool,
    DummyTool,
    FailingTool,
    MissingNameTool,
    ParamTool,
    RejectingTool,
    fresh_registry,
    reset_registry,
)


class TestToolRegistrySync(unittest.TestCase):
    """ToolRegistry 同步接口测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(DummyTool)
        self.registry.register(ParamTool)

    def tearDown(self):
        reset_registry(self.registry)

    def test_singleton(self):
        """多个 ToolRegistry() 应返回同一实例。"""
        a = ToolRegistry()
        b = ToolRegistry()
        self.assertIs(a, b)

    def test_register_returns_class(self):
        """register 应返回原工具类（装饰器可用）。"""
        result = self.registry.register(FailingTool)
        self.assertIs(result, FailingTool)

    def test_register_duplicate_raises(self):
        """重复注册应抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.registry.register(DummyTool)

    def test_register_missing_name_raises(self):
        """缺少 name 属性应抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.registry.register(MissingNameTool)

    def test_discover_nonexistent_dir(self):
        """不存在的目录应返回 0。"""
        count = self.registry.discover(["/nonexistent/path"])
        self.assertEqual(count, 0)
        self.assertTrue(self.registry._initialized)

    def test_discover_marks_ready(self):
        """discover 后应标记已发起发现并置位完成事件。"""
        self.registry.discover(["/nonexistent/path"])
        self.assertTrue(self.registry._discovery_started)
        self.assertTrue(self.registry._discovery_done.is_set())

    def test_discover_counts_importable_packages(self):
        """扫描目录应统计可导入的子包数量。"""
        with tempfile.TemporaryDirectory() as td:
            pkg1 = os.path.join(td, "tool_a")
            pkg2 = os.path.join(td, "tool_b")
            os.makedirs(pkg1)
            os.makedirs(pkg2)
            os.makedirs(os.path.join(td, "not_a_pkg"))
            open(os.path.join(pkg1, "__init__.py"), "w").close()
            open(os.path.join(pkg2, "__init__.py"), "w").close()
            with patch(
                "fabrica.tool.importlib.import_module",
                return_value=object(),
            ):
                count = self.registry.discover([td])
        self.assertEqual(count, 2)

    def test_get_tool_lazy_instantiation(self):
        """get_tool 应懒加载并缓存实例。"""
        self.assertNotIn("dummy", self.registry._instances)
        inst1 = self.registry.get_tool("dummy")
        inst2 = self.registry.get_tool("dummy")
        self.assertIs(inst1, inst2)
        self.assertIn("dummy", self.registry._instances)

    def test_get_tool_not_found(self):
        """未注册工具应抛 KeyError。"""
        with self.assertRaises(KeyError):
            self.registry.get_tool("nope")

    def test_list_tools(self):
        """list_tools 应返回所有注册工具元信息。"""
        metas = self.registry.list_tools()
        names = {m.name for m in metas}
        self.assertEqual(names, {"dummy", "param_tool"})

    def test_get_schema(self):
        """get_schema 应返回工具参数定义。"""
        schema = self.registry.get_schema("param_tool")
        self.assertEqual(len(schema), 1)
        self.assertEqual(schema[0].key, "threshold")

    def test_get_schema_not_found(self):
        """未注册工具的 get_schema 应抛 KeyError。"""
        with self.assertRaises(KeyError):
            self.registry.get_schema("nope")

    def test_get_tool_meta(self):
        """get_tool_meta 应返回正确的元信息。"""
        meta = self.registry.get_tool_meta("dummy")
        self.assertEqual(meta.name, "dummy")
        self.assertEqual(meta.title, "Dummy Tool")
        self.assertEqual(meta.category, "test")

    def test_get_tool_meta_not_found(self):
        """未注册工具的 get_tool_meta 应抛 KeyError。"""
        with self.assertRaises(KeyError):
            self.registry.get_tool_meta("nope")

    def test_cancel_task_nonexistent(self):
        """取消不存在的任务应返回 False。"""
        self.assertFalse(self.registry.cancel_task("nope"))

    def test_get_task_nonexistent_raises(self):
        """获取不存在的任务应抛 KeyError。"""
        with self.assertRaises(KeyError):
            self.registry.get_task("nope")

    def test_list_tasks_empty(self):
        """无任务时 list_tasks 应返回空列表。"""
        self.assertEqual(self.registry.list_tasks(), [])

    def test_run_tool_unknown_raises(self):
        """运行未注册工具应抛 KeyError。"""
        with self.assertRaises(KeyError):
            self.registry.run_tool("nope", {})

    def test_progress_callback_fire(self):
        """进度回调应触发并解包 (percent, message, stage)。"""
        received = []
        self.registry.register_progress_callback(
            "t1", lambda p, m, s="": received.append((p, m, s))
        )
        self.registry._fire_callback("t1", "progress", (50, "处理中", "测试阶段"))
        self.assertEqual(received, [(50, "处理中", "测试阶段")])

    def test_log_callback_fire(self):
        """日志回调应触发并解包 (level, message)。"""
        received = []
        self.registry.register_log_callback(
            "t1", lambda l, m: received.append((l, m))
        )
        self.registry._fire_callback("t1", "log", ("info", "hello"))
        self.assertEqual(received, [("info", "hello")])

    def test_complete_callback_fire(self):
        """完成回调应触发并接收 payload。"""
        received = []
        self.registry.register_complete_callback(
            "t1", lambda r: received.append(r)
        )
        self.registry._fire_callback("t1", "complete", {"ok": True})
        self.assertEqual(received, [{"ok": True}])

    def test_error_callback_fire(self):
        """错误回调应触发并接收 payload。"""
        received = []
        self.registry.register_error_callback(
            "t1", lambda e: received.append(e)
        )
        self.registry._fire_callback("t1", "error", "boom")
        self.assertEqual(received, ["boom"])

    def test_unregister_callback(self):
        """注销回调后不应再触发。"""
        received = []
        self.registry.register_progress_callback(
            "t1", lambda p, m: received.append((p, m))
        )
        self.registry.unregister_progress_callback("t1")
        self.registry._fire_callback("t1", "progress", (50, "msg"))
        self.assertEqual(received, [])


class TestToolRegistryAsync(unittest.IsolatedAsyncioTestCase):
    """ToolRegistry 异步执行接口测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(DummyTool)
        self.registry.register(RejectingTool)
        self.registry.register(FailingTool)
        self.registry.register(CancellableTool)

    async def tearDown(self):
        reset_registry(self.registry)

    async def _wait_for_terminal(self, task_id, timeout=10.0):
        """轮询等待任务进入终态。"""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            detail = self.registry.get_task(task_id)
            if detail.status in (
                "completed", "failed", "cancelled", "invalid",
            ):
                return detail
            await asyncio.sleep(0.02)
        raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内结束")

    async def test_run_tool_completes(self):
        """run_tool 应返回 task_id 并最终 COMPLETED。"""
        task_id = self.registry.run_tool("dummy", {})
        self.assertTrue(task_id)
        detail = await self._wait_for_terminal(task_id)
        self.assertEqual(detail.status, "completed")
        self.assertEqual(detail.result, {"ok": True})

    async def test_run_tool_rejects_params(self):
        """校验失败的任务应进入 INVALID。"""
        task_id = self.registry.run_tool("rejecting", {})
        detail = await self._wait_for_terminal(task_id)
        self.assertEqual(detail.status, "invalid")
        self.assertIn("参数错误", detail.error)

    async def test_run_tool_fails(self):
        """执行抛异常的任务应进入 FAILED。"""
        task_id = self.registry.run_tool("failing", {})
        detail = await self._wait_for_terminal(task_id)
        self.assertEqual(detail.status, "failed")
        self.assertIn("boom", detail.error)

    async def test_run_tool_cancel(self):
        """执行中取消任务应进入 CANCELLED 并调用 on_cancel。"""
        task_id = self.registry.run_tool("cancellable", {})
        await asyncio.sleep(0.1)
        self.assertTrue(self.registry.cancel_task(task_id))
        detail = await self._wait_for_terminal(task_id)
        self.assertEqual(detail.status, "cancelled")
        tool = self.registry.get_tool("cancellable")
        self.assertTrue(tool.cancel_called)

    async def test_complete_callback_receives_result(self):
        """完成回调应收到执行结果。"""
        received = []
        task_id = self.registry.run_tool(
            "dummy", {}, {"complete": lambda r: received.append(r)}
        )
        await self._wait_for_terminal(task_id)
        self.assertEqual(received, [{"ok": True}])

    async def test_list_tasks_after_run(self):
        """执行后 list_tasks 应包含任务摘要。"""
        task_id = self.registry.run_tool("dummy", {})
        await self._wait_for_terminal(task_id)
        summaries = self.registry.list_tasks()
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].task_id, task_id)


class TestTaskStateMachinePersistence(unittest.TestCase):
    """TaskStateMachine 序列化/反序列化往返测试。"""

    def test_to_dict_from_dict_roundtrip(self):
        """to_dict/from_dict 往返应完整保留状态、结果与日志。"""
        sm = TaskStateMachine("t1", "dummy", {"a": 1})
        sm.transition(TaskStatus.VALIDATING)
        sm.transition(TaskStatus.VALID)
        sm.transition(TaskStatus.RUNNING)
        sm.transition(TaskStatus.COMPLETED)
        sm._result = {"ok": True}
        sm.append_log("info", "hello")
        created_at = sm._created_at
        completed_at = sm._completed_at

        d = sm.to_dict()
        sm2 = TaskStateMachine.from_dict(d)
        self.assertEqual(sm2.task_id, "t1")
        self.assertEqual(sm2.tool_name, "dummy")
        self.assertEqual(sm2.params, {"a": 1})
        self.assertEqual(sm2.status, TaskStatus.COMPLETED)
        self.assertEqual(sm2._result, {"ok": True})
        self.assertEqual(sm2._logs[0]["message"], "hello")
        self.assertEqual(sm2._created_at, created_at)
        self.assertEqual(sm2._completed_at, completed_at)

        # 经 JSON 序列化往返后仍可重建
        d2 = json.loads(json.dumps(d))
        sm3 = TaskStateMachine.from_dict(d2)
        self.assertEqual(sm3._result, {"ok": True})
        self.assertEqual(sm3.status, TaskStatus.COMPLETED)


class TestTaskHistoryPersistence(unittest.IsolatedAsyncioTestCase):
    """任务历史磁盘持久化测试。"""

    async def _wait_for_terminal(self, registry, task_id, timeout=10.0):
        """轮询等待任务进入终态。"""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            detail = registry.get_task(task_id)
            if detail.status in (
                "completed", "failed", "cancelled", "invalid",
            ):
                return detail
            await asyncio.sleep(0.02)
        raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内结束")

    async def test_terminal_saved_and_reloaded(self):
        """终态任务落盘后，重启重建单例可从磁盘加载并返回结果。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tasks.json")
            reg = fresh_registry()
            reg._history_path = path
            reg.register(DummyTool)
            task_id = reg.run_tool("dummy", {})
            detail = await self._wait_for_terminal(reg, task_id)
            self.assertEqual(detail.status, "completed")

            # 模拟重启：重建单例，指向同一历史文件
            reg2 = fresh_registry()
            reg2._history_path = path
            summaries = reg2.list_tasks()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].task_id, task_id)
            d2 = reg2.get_task(task_id)
            self.assertEqual(d2.status, "completed")
            self.assertEqual(d2.result, {"ok": True})

    async def test_non_terminal_not_saved(self):
        """运行中的任务不落盘，终态后才写入。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tasks.json")
            reg = fresh_registry()
            reg._history_path = path
            reg.register(CpuTool)
            task_id = reg.run_tool("cpu_tool", {"seconds": 1.0})
            await asyncio.sleep(0.1)  # 确保仍在运行
            reg._save_tasks()
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data, [])

            # 等待任务结束并落盘后，记录被保存
            detail = await self._wait_for_terminal(reg, task_id)
            self.assertEqual(detail.status, "completed")
            reg._save_tasks()
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["task_id"], task_id)

    async def test_delete_removes_from_disk(self):
        """删除任务后重新落盘，磁盘历史不再包含该任务。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tasks.json")
            reg = fresh_registry()
            reg._history_path = path
            reg.register(DummyTool)
            task_id = reg.run_tool("dummy", {})
            await self._wait_for_terminal(reg, task_id)
            self.assertTrue(os.path.exists(path))
            self.assertTrue(reg.delete_task(task_id))
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data, [])


class TestTaskCleanupHook(unittest.IsolatedAsyncioTestCase):
    """TaskRegistry 中间产物清理编排测试。"""

    async def _wait_for_terminal(self, registry, task_id, timeout=10.0):
        """轮询等待任务进入终态。"""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            detail = registry.get_task(task_id)
            if detail.status in (
                "completed", "failed", "cancelled", "invalid",
            ):
                return detail
            await asyncio.sleep(0.02)
        raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内结束")

    async def test_delete_task_calls_cleanup_with_referenced(self):
        """删除任务应调用工具 cleanup_task，并传入其余任务引用的键。"""
        reg = fresh_registry()
        reg.register(CleanupTool)
        tool = reg.get_tool("cleanup_tool")
        t1 = reg.run_tool("cleanup_tool", {})
        t2 = reg.run_tool("cleanup_tool", {})
        await self._wait_for_terminal(reg, t1)
        await self._wait_for_terminal(reg, t2)

        self.assertTrue(reg.delete_task(t1))
        self.assertEqual(len(tool.cleanup_calls), 1)
        result, referenced = tool.cleanup_calls[0]
        self.assertEqual(referenced, {"h1"})
        self.assertEqual(result["status"], "completed")

    async def test_cleanup_orphans_calls_tool_and_aggregates(self):
        """cleanup_orphans 应调用工具钩子并汇总计数。"""
        reg = fresh_registry()
        reg.register(CleanupTool)
        tool = reg.get_tool("cleanup_tool")
        t1 = reg.run_tool("cleanup_tool", {})
        await self._wait_for_terminal(reg, t1)

        counts = reg.cleanup_orphans()
        self.assertEqual(len(tool.orphan_calls), 1)
        self.assertEqual(counts["keyframes"], 1)
        self.assertEqual(counts["features"], 2)
        self.assertEqual(counts["output"], 0)


if __name__ == "__main__":
    unittest.main()