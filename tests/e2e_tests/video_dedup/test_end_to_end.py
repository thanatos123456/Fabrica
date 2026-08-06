"""视频验重工具端到端测试（T5.6）。

覆盖：工具注册 → 参数校验 → run() 执行（真实管线）→ 进度上报 →
报告 JSON 输出 → 取消。
"""

import asyncio
import json
import os
import tempfile
import unittest

from tests.fixtures.video_factory import (
    create_derived_video,
    create_test_video,
)
from tests.unittests.tool.fixtures import fresh_registry, reset_registry

from fabrica.tool import TaskContext
from fabrica.tools.video_dedup import VideoDedupTool


def _make_ctx(tool_name="video_dedup"):
    """构造一个 TaskContext。"""
    return TaskContext(
        task_id="task-1",
        params={},
        temp_dir=tempfile.mkdtemp(),
        tool_name=tool_name,
    )


class EndToEndTest(unittest.TestCase):
    """端到端测试集。"""

    def setUp(self):
        self.registry = fresh_registry()
        self.registry.register(VideoDedupTool)
        self._tmp = tempfile.TemporaryDirectory()
        self.video_dir = os.path.join(self._tmp.name, "videos")
        os.makedirs(self.video_dir)

    def tearDown(self):
        reset_registry(self.registry)
        self._tmp.cleanup()

    def test_register_and_validate(self):
        """注册成功、schema 完整、合法参数校验通过。"""
        names = {t.name for t in self.registry.list_tools()}
        self.assertIn("video_dedup", names)
        schema = self.registry.get_schema("video_dedup")
        keys = {p.key for p in schema}
        self.assertEqual(
            keys,
            {"input_dir", "output", "recursive", "device", "threshold"},
        )
        tool = VideoDedupTool()
        asyncio.run(
            tool.validate(
                {"input_dir": self.video_dir, "device": "cpu"}
            )
        )

    def test_run_end_to_end(self):
        """run() 真实执行：检出重复对并生成报告文件。"""
        src = create_test_video(
            os.path.join(self.video_dir, "a.mp4"), content="e2e"
        )
        create_derived_video(
            src, os.path.join(self.video_dir, "a_dup.mp4"), resize=True
        )
        outgoing = os.path.join(self._tmp.name, "out.json")
        tool = VideoDedupTool()
        ctx = _make_ctx()
        result = asyncio.run(
            tool.run(
                {
                    "input_dir": self.video_dir,
                    "output": outgoing,
                    "device": "cpu",
                    "db_path": os.path.join(self._tmp.name, "dedup.db"),
                },
                ctx,
            )
        )
        self.assertEqual(result["status"], "completed")
        report = result["report"]
        self.assertEqual(report["total_videos"], 2)
        # 重复对应出现在同一 final_group
        # （组内元素为文件完整路径，需按 basename 比较）
        def in_same_group(a, b):
            def has(group, name):
                return any(
                    os.path.basename(item) == name for item in group
                )
            return any(
                has(group, os.path.basename(a))
                and has(group, os.path.basename(b))
                for group in report["final_groups"]
            )
        self.assertTrue(in_same_group("a.mp4", "a_dup.mp4"))
        # 报告 JSON 文件已生成
        self.assertTrue(os.path.exists(outgoing))
        with open(outgoing, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("final_groups", data)

    def test_run_cancel(self):
        """取消后 run() 返回 cancelled。"""
        create_test_video(
            os.path.join(self.video_dir, "a.mp4"), content="cancel"
        )
        tool = VideoDedupTool()
        ctx = _make_ctx()
        ctx.cancel()  # 预置取消信号
        result = asyncio.run(
            tool.run(
                {
                    "input_dir": self.video_dir,
                    "db_path": os.path.join(self._tmp.name, "cancel.db"),
                },
                ctx,
            )
        )
        self.assertEqual(result["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()