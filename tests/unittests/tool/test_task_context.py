"""TaskContext 执行上下文测试。

测试目标：fabrica/tool.py 中的 TaskContext 类
覆盖：进度报告、日志、取消信号、持久化数据目录
"""

import os
import tempfile
import unittest

from fabrica.tool import TaskContext


class TestTaskContext(unittest.TestCase):
    """TaskContext 执行上下文测试集。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="fabrica_test_ctx_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_ctx(self, **kwargs):
        """构造 TaskContext 测试实例。"""
        defaults = {
            "task_id": "t1",
            "params": {"a": 1},
            "temp_dir": self.temp_dir,
        }
        defaults.update(kwargs)
        return TaskContext(**defaults)

    def test_report_progress_triggers_callback(self):
        """report_progress 应触发进度回调。"""
        received = []
        ctx = self._make_ctx(
            _progress_callback=lambda p, m: received.append((p, m))
        )
        ctx.report_progress(50, "处理中")
        self.assertEqual(received, [(50, "处理中")])

    def test_report_progress_without_callback(self):
        """未设置进度回调时 report_progress 不应抛异常。"""
        ctx = self._make_ctx()
        ctx.report_progress(100, "完成")

    def test_log_triggers_callback(self):
        """log 应触发日志回调。"""
        received = []
        ctx = self._make_ctx(
            _log_callback=lambda l, m: received.append((l, m))
        )
        ctx.log("info", "hello")
        self.assertEqual(received, [("info", "hello")])

    def test_log_without_callback(self):
        """未设置日志回调时 log 不应抛异常。"""
        ctx = self._make_ctx()
        ctx.log("error", "boom")

    def test_cancelled_false_by_default(self):
        """初始 cancelled 应为 False。"""
        ctx = self._make_ctx()
        self.assertFalse(ctx.cancelled)

    def test_cancel_sets_cancelled(self):
        """调用 cancel 后 cancelled 应为 True。"""
        ctx = self._make_ctx()
        ctx.cancel()
        self.assertTrue(ctx.cancelled)

    def test_get_data_dir_with_tool_name(self):
        """get_data_dir 应返回 <base>/<tool_name> 且目录存在。"""
        ctx = self._make_ctx(tool_name="video_dedup", data_dir=self.temp_dir)
        path = ctx.get_data_dir()
        self.assertEqual(path, os.path.join(self.temp_dir, "video_dedup"))
        self.assertTrue(os.path.isdir(path))

    def test_get_data_dir_without_tool_name(self):
        """无 tool_name 时 get_data_dir 应确保根目录存在。"""
        ctx = self._make_ctx(data_dir=self.temp_dir)
        path = ctx.get_data_dir()
        self.assertEqual(path, self.temp_dir)
        self.assertTrue(os.path.isdir(path))

    def test_get_data_dir_default_base(self):
        """未指定 data_dir 时应使用默认 "data/tools"。"""
        ctx = self._make_ctx(tool_name="mytool")
        path = ctx.get_data_dir()
        self.assertTrue(path.endswith(os.path.join("data", "tools", "mytool")))


if __name__ == "__main__":
    unittest.main()