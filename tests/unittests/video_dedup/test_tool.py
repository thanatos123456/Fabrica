"""视频验重工具注册与调度测试。

测试目标：fabrica/tools/video_dedup/__init__.py
覆盖：VideoDedupTool 注册、参数 Schema、validate、run
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from tests.unittests.tool.fixtures import fresh_registry, reset_registry

from fabrica.tools.video_dedup import VideoDedupTool
from fabrica.utils.exceptions import (
    ParamInvalidError,
    ParamMissingError,
)


class TestVideoDedupTool(unittest.TestCase):
    """VideoDedupTool 工具测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(VideoDedupTool)

    def tearDown(self):
        reset_registry(self.registry)

    def test_tool_is_registered(self):
        """video_dedup 应出现在已注册工具列表中。"""
        names = {t.name for t in self.registry.list_tools()}
        self.assertIn("video_dedup", names)

    def test_schema_has_five_params(self):
        """参数 Schema 应包含 5 个参数定义。"""
        schema = self.registry.get_schema("video_dedup")
        keys = {p.key for p in schema}
        self.assertEqual(
            keys,
            {"input_dir", "output", "recursive", "device", "threshold"},
        )

    def test_get_schema_unknown_tool_raises(self):
        """未知工具应抛出异常。"""
        with self.assertRaises(Exception):
            self.registry.get_schema("no_such_tool")

    # ---- validate ----

    def test_validate_missing_input_dir_raises(self):
        """缺少 input_dir 应抛 ParamMissingError。"""
        tool = VideoDedupTool()
        with self.assertRaises(ParamMissingError):
            asyncio.run(tool.validate({}))

    def test_validate_invalid_device_raises(self):
        """device 不在允许范围应抛 ParamInvalidError。"""
        tool = VideoDedupTool()
        params = {"input_dir": "/tmp", "device": "gpu"}
        with self.assertRaises(ParamInvalidError):
            asyncio.run(tool.validate(params))

    def test_validate_threshold_out_of_range_raises(self):
        """threshold 越界应抛 ParamInvalidError。"""
        tool = VideoDedupTool()
        params = {"input_dir": "/tmp", "threshold": 5.0}
        with self.assertRaises(ParamInvalidError):
            asyncio.run(tool.validate(params))

    def test_validate_valid_params_passes(self):
        """合法参数应通过校验而不抛异常。"""
        tool = VideoDedupTool()
        params = {
            "input_dir": "/tmp",
            "device": "cpu",
            "threshold": 0.5,
        }
        asyncio.run(tool.validate(params))

    # ---- run ----

    def test_run_delegates_to_pipeline(self):
        """run 应委托 CascadePipeline 并返回 completed。"""
        fake_report = {
            "cancelled": False,
            "total_videos": 2,
            "l1_groups": [],
            "l2_pairs": [],
            "l3_pairs": [],
            "final_groups": [],
            "errors": [],
        }
        tool = VideoDedupTool()
        ctx = MagicMock()
        with patch(
            "fabrica.tools.video_dedup.CascadePipeline.run_pipeline",
            return_value=fake_report,
        ) as mock_run:
            result = asyncio.run(
                tool.run({"input_dir": "/tmp"}, ctx)
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["report"], fake_report)
        mock_run.assert_called_once()
        ctx.report_progress.assert_called()
        ctx.log.assert_not_called()

    def test_run_cancelled_status(self):
        """run 在 pipeline 报告取消时应返回 cancelled。"""
        fake_report = {
            "cancelled": True,
            "total_videos": 0,
            "l1_groups": [],
            "l2_pairs": [],
            "l3_pairs": [],
            "final_groups": [],
            "errors": [],
        }
        tool = VideoDedupTool()
        ctx = MagicMock()
        with patch(
            "fabrica.tools.video_dedup.CascadePipeline.run_pipeline",
            return_value=fake_report,
        ):
            result = asyncio.run(
                tool.run({"input_dir": "/tmp"}, ctx)
            )
        self.assertEqual(result["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()