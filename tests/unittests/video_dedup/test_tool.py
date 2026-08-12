"""视频验重工具注册与调度测试。

测试目标：fabrica/tools/video_dedup/__init__.py
覆盖：VideoDedupTool 注册、参数 Schema、validate、run
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tests.unittests.tool.fixtures import fresh_registry, reset_registry

from fabrica.tools.video_dedup import VideoDedupTool, _vid_hash


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
        """缺少 input_dir 应返回包含 input_dir 的错误列表。"""
        tool = VideoDedupTool()
        errors = asyncio.run(tool.validate({}))
        self.assertTrue(errors)
        self.assertTrue(any("input_dir" in e for e in errors))

    def test_validate_invalid_device_raises(self):
        """device 不在允许范围应返回 device 错误。"""
        tool = VideoDedupTool()
        params = {"input_dir": "/tmp", "device": "gpu"}
        errors = asyncio.run(tool.validate(params))
        self.assertTrue(any("device" in e for e in errors))

    def test_validate_threshold_out_of_range_raises(self):
        """threshold 越界应返回非空错误列表。"""
        tool = VideoDedupTool()
        params = {"input_dir": "/tmp", "threshold": 5.0}
        errors = asyncio.run(tool.validate(params))
        self.assertTrue(errors)

    def test_validate_valid_params_passes(self):
        """合法参数应返回空列表。"""
        tool = VideoDedupTool()
        params = {
            "input_dir": "/tmp",
            "device": "cpu",
            "threshold": 0.5,
        }
        errors = asyncio.run(tool.validate(params))
        self.assertEqual(errors, [])

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
            "fabrica.tools.video_dedup.pipeline.CascadePipeline.run_pipeline",
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
            "fabrica.tools.video_dedup.pipeline.CascadePipeline.run_pipeline",
            return_value=fake_report,
        ):
            result = asyncio.run(
                tool.run({"input_dir": "/tmp"}, ctx)
            )
        self.assertEqual(result["status"], "cancelled")


class TestCleanupMethods(unittest.TestCase):
    """VideoDedupTool 中间产物清理钩子测试。"""

    def test_extract_refs_collects_hashes(self):
        """extract_refs 应从 report 各结构提取 video_id 的 md5 键。"""
        tool = VideoDedupTool()
        result = {
            "status": "completed", "tool": "video_dedup",
            "report": {
                "keyframes": {
                    "a.mp4": {0: "/keyframes/x/frame_0000.jpg"},
                },
                "final_groups": [{"videos": [{"id": "b.mp4"}]}],
                "l1_groups": [["c.mp4"]],
                "l2_pairs": [["d.mp4", "e.mp4", 0.9]],
                "l3_pairs": [["f.mp4", "g.mp4", 0.9]],
            },
        }
        refs = tool.extract_refs(result)
        expected = {_vid_hash(v) for v in
                    ["a.mp4", "b.mp4", "c.mp4", "d.mp4",
                     "e.mp4", "f.mp4", "g.mp4"]}
        self.assertEqual(refs, expected)

    def test_extract_refs_ignores_invalid(self):
        """extract_refs 对非 dict 输入应返回空集合。"""
        tool = VideoDedupTool()
        self.assertEqual(tool.extract_refs(None), set())
        self.assertEqual(tool.extract_refs("x"), set())

    def test_cleanup_task_deletes_orphans_and_output(self):
        """cleanup_task 删除孤儿产物并保留仍被引用的产物。"""
        tool = VideoDedupTool()
        with tempfile.TemporaryDirectory() as tmp:
            kf = os.path.join(tmp, "keyframes")
            feat = os.path.join(tmp, "features")
            os.makedirs(kf)
            os.makedirs(feat)
            h_orphan = _vid_hash("orphan.mp4")
            h_keep = _vid_hash("keep.mp4")
            os.makedirs(os.path.join(kf, h_orphan))
            os.makedirs(os.path.join(kf, h_keep))
            open(os.path.join(feat, f"{h_orphan}.npy"), "w").close()
            open(os.path.join(feat, f"{h_keep}.npy"), "w").close()
            out = os.path.join(tmp, "report.json")
            open(out, "w").close()
            result = {
                "status": "completed", "tool": "video_dedup",
                "report": {
                    "final_groups": [
                        {"videos": [
                            {"id": "orphan.mp4"}, {"id": "keep.mp4"},
                        ]},
                    ],
                    "_output": out,
                },
            }
            with patch(
                "fabrica.tools.video_dedup.DEFAULT_KEYFRAME_DIR", kf,
            ), patch(
                "fabrica.tools.video_dedup.DEFAULT_FEATURE_DIR", feat,
            ):
                counts = tool.cleanup_task(result, {h_keep})

            self.assertEqual(counts["keyframes"], 1)
            self.assertFalse(os.path.exists(os.path.join(kf, h_orphan)))
            self.assertTrue(os.path.exists(os.path.join(kf, h_keep)))
            self.assertEqual(counts["features"], 1)
            self.assertFalse(
                os.path.exists(os.path.join(feat, f"{h_orphan}.npy"))
            )
            self.assertTrue(
                os.path.exists(os.path.join(feat, f"{h_keep}.npy"))
            )
            self.assertEqual(counts["output"], 1)
            self.assertFalse(os.path.exists(out))

    def test_cleanup_orphans_removes_unreferenced(self):
        """cleanup_orphans 删除目录中未被任何任务引用的条目。"""
        tool = VideoDedupTool()
        with tempfile.TemporaryDirectory() as tmp:
            kf = os.path.join(tmp, "keyframes")
            feat = os.path.join(tmp, "features")
            os.makedirs(kf)
            os.makedirs(feat)
            h_keep = _vid_hash("keep.mp4")
            h_orphan = _vid_hash("orphan.mp4")
            os.makedirs(os.path.join(kf, h_keep))
            os.makedirs(os.path.join(kf, h_orphan))
            open(os.path.join(feat, f"{h_keep}.npy"), "w").close()
            open(os.path.join(feat, f"{h_orphan}.npy"), "w").close()
            with patch(
                "fabrica.tools.video_dedup.DEFAULT_KEYFRAME_DIR", kf,
            ), patch(
                "fabrica.tools.video_dedup.DEFAULT_FEATURE_DIR", feat,
            ), patch(
                "fabrica.tools.video_dedup.DEFAULT_REPORT_DIR",
                os.path.join(tmp, "reports"),
            ):
                counts = tool.cleanup_orphans({h_keep})

            self.assertEqual(counts["keyframes"], 1)
            self.assertFalse(os.path.exists(os.path.join(kf, h_orphan)))
            self.assertTrue(os.path.exists(os.path.join(kf, h_keep)))
            self.assertEqual(counts["features"], 1)
            self.assertFalse(
                os.path.exists(os.path.join(feat, f"{h_orphan}.npy"))
            )
            self.assertTrue(
                os.path.exists(os.path.join(feat, f"{h_keep}.npy"))
            )

    def test_extract_outputs_collects_report_path(self):
        """extract_outputs 应提取 report['_output'] 绝对路径。"""
        tool = VideoDedupTool()
        self.assertEqual(tool.extract_outputs(None), set())
        self.assertEqual(tool.extract_outputs("x"), set())
        self.assertEqual(tool.extract_outputs({"report": {}}), set())
        result = {"report": {"_output": "/tmp/r.json"}}
        self.assertEqual(tool.extract_outputs(result), {"/tmp/r.json"})

    def test_resolve_output_uses_reports_dir(self):
        """_resolve_output 默认写入受管 reports 目录并按任务命名；绝对路径原样使用。"""
        tool = VideoDedupTool()
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "fabrica.tools.video_dedup.DEFAULT_REPORT_DIR", tmp,
            ):
                # 空输出 -> 受管目录 + task_id
                p = tool._resolve_output("", "task-1")
                self.assertEqual(p, os.path.join(tmp, "task-1.json"))
                # 相对路径（历史默认值）也归入受管目录，不落 cwd
                p2 = tool._resolve_output("dedup_result.json", "task-2")
                self.assertEqual(p2, os.path.join(tmp, "task-2.json"))
                # 绝对路径原样使用
                custom_abs = os.path.join(tmp, "custom.json")
                p3 = tool._resolve_output(custom_abs, "task-3")
                self.assertEqual(p3, custom_abs)

    def test_cleanup_orphans_removes_unreferenced_report(self):
        """cleanup_orphans 删除 reports 目录中未被引用的 .json，保留被引用的。"""
        tool = VideoDedupTool()
        with tempfile.TemporaryDirectory() as tmp:
            kf = os.path.join(tmp, "keyframes")
            feat = os.path.join(tmp, "features")
            reports = os.path.join(tmp, "reports")
            os.makedirs(kf)
            os.makedirs(feat)
            os.makedirs(reports)
            keep = os.path.join(reports, "keep.json")
            orphan = os.path.join(reports, "orphan.json")
            open(keep, "w").close()
            open(orphan, "w").close()
            with patch(
                "fabrica.tools.video_dedup.DEFAULT_KEYFRAME_DIR", kf,
            ), patch(
                "fabrica.tools.video_dedup.DEFAULT_FEATURE_DIR", feat,
            ), patch(
                "fabrica.tools.video_dedup.DEFAULT_REPORT_DIR", reports,
            ):
                counts = tool.cleanup_orphans(set(), {keep})

            self.assertEqual(counts["output"], 1)
            self.assertTrue(os.path.exists(keep))
            self.assertFalse(os.path.exists(orphan))


if __name__ == "__main__":
    unittest.main()