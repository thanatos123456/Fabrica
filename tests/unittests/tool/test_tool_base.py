"""ToolBase 抽象基类测试。

测试目标：fabrica/tool.py 中的 ToolBase 类
覆盖：抽象约束、类属性默认值、可选方法、方法签名
"""

import inspect
import unittest

from fabrica.tool import ToolBase

from tests.unittests.tool.fixtures import (
    DummyTool,
    MissingNameTool,
    UnimplementedTool,
)


class _SimpleTool(ToolBase):
    """完整实现但不覆盖 on_cancel/on_complete 的工具。"""

    name = "simple"

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        return {}


class TestToolBase(unittest.TestCase):
    """ToolBase 抽象基类测试集。"""

    def test_cannot_instantiate_abstract_subclass(self):
        """未实现全部抽象方法的子类应抛 TypeError。"""
        with self.assertRaises(TypeError):
            UnimplementedTool()

    def test_can_instantiate_complete_subclass(self):
        """完整实现的子类应可实例化。"""
        tool = DummyTool()
        self.assertIsInstance(tool, ToolBase)

    def test_default_metadata_attributes(self):
        """ToolBase 默认类属性应正确。"""
        self.assertIsNone(ToolBase.name)
        self.assertIsNone(ToolBase.title)
        self.assertEqual(ToolBase.description, "")
        self.assertIsNone(ToolBase.icon)
        self.assertEqual(ToolBase.params, [])
        self.assertEqual(ToolBase.version, "1.0.0")
        self.assertEqual(ToolBase.category, "misc")
        self.assertFalse(ToolBase.cpu_intensive)

    def test_subclass_overrides_metadata(self):
        """子类应可覆盖类属性元信息。"""
        self.assertEqual(DummyTool.name, "dummy")
        self.assertEqual(DummyTool.title, "Dummy Tool")
        self.assertEqual(DummyTool.version, "1.0.0")
        self.assertEqual(DummyTool.category, "test")

    def test_cpu_intensive_default_false(self):
        """默认子类 cpu_intensive 应为 False。"""
        self.assertFalse(DummyTool.cpu_intensive)

    def test_cpu_intensive_can_be_true(self):
        """子类可覆盖 cpu_intensive 为 True。"""
        from tests.unittests.tool.fixtures import CpuTool
        self.assertTrue(CpuTool.cpu_intensive)

    def test_on_init_is_async(self):
        """on_init 应为协程函数。"""
        self.assertTrue(inspect.iscoroutinefunction(DummyTool.on_init))

    def test_validate_is_async(self):
        """validate 应为协程函数。"""
        self.assertTrue(inspect.iscoroutinefunction(DummyTool.validate))

    def test_run_is_async(self):
        """run 应为协程函数。"""
        self.assertTrue(inspect.iscoroutinefunction(DummyTool.run))

    def test_on_cancel_is_async(self):
        """on_cancel 应为协程函数。"""
        self.assertTrue(inspect.iscoroutinefunction(DummyTool.on_cancel))

    def test_on_complete_is_async(self):
        """on_complete 应为协程函数。"""
        self.assertTrue(inspect.iscoroutinefunction(DummyTool.on_complete))

    def test_on_cancel_default_noop(self):
        """默认 on_cancel 应为空操作，不抛异常。"""
        import asyncio
        tool = _SimpleTool()
        asyncio.run(tool.on_cancel())

    def test_on_complete_default_noop(self):
        """默认 on_complete 应为空操作，不抛异常。"""
        import asyncio
        tool = _SimpleTool()
        asyncio.run(tool.on_complete({"ok": True}))

    def test_missing_name_has_no_name(self):
        """缺少 name 属性的工具类 name 应为 None。"""
        self.assertIsNone(MissingNameTool.name)


if __name__ == "__main__":
    unittest.main()