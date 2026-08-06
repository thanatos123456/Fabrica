"""hestia 资源池集成测试。

测试目标：fabrica/tool.py 中 ToolRegistry 的 hestia 资源池集成
覆盖：初始化、懒加载、优雅关闭、并发控制、超时标记、IO 任务隔离
"""

import asyncio
import time
import unittest

from aurora.python.hestia import PoolConfig

from tests.unittests.tool.fixtures import (
    CpuTool,
    IOTool,
    fresh_registry,
    reset_registry,
)


class TestResourcePool(unittest.IsolatedAsyncioTestCase):
    """hestia 资源池集成测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(CpuTool)
        self.registry.register(IOTool)

    async def tearDown(self):
        reset_registry(self.registry)

    async def _wait_for_terminal(self, task_id, timeout=15.0):
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

    async def test_init_pool_default_config(self):
        """init_pool 默认配置应为线程池 max_size=2 task_timeout=3600。"""
        self.registry.init_pool()
        pool = self.registry.get_pool()
        self.assertEqual(pool._config.pool_type, "thread")
        self.assertEqual(pool._config.max_size, 2)
        self.assertEqual(pool._config.task_timeout, 3600)

    async def test_init_pool_custom_config(self):
        """init_pool 自定义配置应生效。"""
        self.registry.init_pool(
            PoolConfig(pool_type="thread", max_size=4, task_timeout=100)
        )
        pool = self.registry.get_pool()
        self.assertEqual(pool._config.max_size, 4)
        self.assertEqual(pool._config.task_timeout, 100)

    async def test_get_pool_lazy_init(self):
        """get_pool 应懒加载资源池。"""
        self.assertIsNone(self.registry._pool)
        pool = self.registry.get_pool()
        self.assertIsNotNone(self.registry._pool)
        self.assertIs(pool, self.registry._pool)

    async def test_shutdown_sets_pool_none(self):
        """shutdown 后 _pool 应为 None。"""
        self.registry.init_pool()
        self.registry.shutdown()
        self.assertIsNone(self.registry._pool)

    async def test_concurrency_limit(self):
        """3 个 CPU 任务在 max_size=2 下应排队，总耗时约 2s。"""
        self.registry.init_pool(
            PoolConfig(pool_type="thread", max_size=2, task_timeout=3600)
        )
        t1 = self.registry.run_tool("cpu_tool", {"seconds": 1.0})
        t2 = self.registry.run_tool("cpu_tool", {"seconds": 1.0})
        t3 = self.registry.run_tool("cpu_tool", {"seconds": 1.0})
        start = time.monotonic()
        for tid in (t1, t2, t3):
            await self._wait_for_terminal(tid)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 1.8)
        for tid in (t1, t2, t3):
            self.assertEqual(self.registry.get_task(tid).status, "completed")

    async def test_timeout_marks_failed(self):
        """任务超时应被标记为 FAILED 且错误含超时。"""
        self.registry.init_pool(
            PoolConfig(pool_type="thread", max_size=2, task_timeout=1)
        )
        tid = self.registry.run_tool("cpu_tool", {"seconds": 3})
        detail = await self._wait_for_terminal(tid)
        self.assertEqual(detail.status, "failed")
        self.assertIn("超时", detail.error)
        # 等待后台线程结束，避免 shutdown(wait=True) 阻塞 tearDown
        await asyncio.sleep(3)

    async def test_io_task_not_submitted_to_pool(self):
        """IO 任务（默认 cpu_intensive=False）应直接 await 正常完成。"""
        self.registry.init_pool()
        tid = self.registry.run_tool("io_tool", {"seconds": 0.2})
        detail = await self._wait_for_terminal(tid)
        self.assertEqual(detail.status, "completed")
        self.assertEqual(detail.result, {"io": True})


if __name__ == "__main__":
    unittest.main()