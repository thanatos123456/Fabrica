"""级联调度 Pipeline 测试（T5.4）。

测试目标：fabrica/tools/video_dedup/pipeline.py
覆盖：五阶段编排、L1 去重、L2/L3 判重、L3 降级、容错、取消、
聚类展开、输出文件与 scan_videos。
用 mock 注入 storage/index/extractor，避免真实视频、FAISS、CLIP。
"""

import json
import os
import tempfile
import threading
import types
import unittest
from unittest import mock

import numpy as np

from fabrica.tools.video_dedup.models import VideoInfo
from fabrica.tools.video_dedup.pipeline import scan_videos


# ============================================================================
# 辅助
# ============================================================================

def _make_frames(n, base=0):
    """构造 n 个带 image 属性的假抽样帧。"""
    return [
        types.SimpleNamespace(image=mock.Mock(), idx=base + i, ts=float(i))
        for i in range(n)
    ]


def _make_video(vid, path=None):
    """构造 VideoInfo。"""
    return VideoInfo(
        id=vid,
        path=path or vid,
        size=100,
        duration=1.0,
        width=320,
        height=240,
        file_hash="",
        frame_count=0,
    )


def _seq(n):
    """构造 pHash 序列。"""
    return np.arange(n, dtype=np.uint64)


def _norm_feats(n):
    """构造 L2 归一化特征。"""
    arr = np.random.default_rng(0).standard_normal((n, 512)).astype(np.float32)
    return arr / np.maximum(np.linalg.norm(arr, axis=-1, keepdims=True), 1e-8)


# ============================================================================
# 测试
# ============================================================================

class BasePipelineTest(unittest.TestCase):
    """公共 setUp：注入 mock storage/index，patch 模块级函数抽样与哈希。"""

    def setUp(self):
        import fabrica.tools.video_dedup.pipeline as pipeline

        self.pipeline = pipeline
        self.storage = mock.Mock()
        self.index = mock.Mock()
        self.cfg = {
            "input_dir": "/video",
            "output": None,
            "recursive": False,
            "device": "cpu",
        }
        # 默认 patch：扫描返回 3 个视频，无 L1 重复，均可抽帧
        self.videos = [_make_video("v1"), _make_video("v2"), _make_video("v3")]
        self.frames = _make_frames(5)
        self.patchers = []
        self.patchers.append(
            mock.patch.object(self.pipeline, "scan_videos",
                              return_value=self.videos)
        )
        self.patchers.append(
            mock.patch.object(self.pipeline, "sample_frames",
                              return_value=(self.frames, 1.0))
        )
        self.patchers.append(
            mock.patch.object(self.pipeline, "video_phash_sequence",
                              return_value=_seq(5))
        )
        self.patchers.append(
            mock.patch.object(self.pipeline, "file_hash",
                              return_value="abc123")
        )
        self.storage.videos_without_hash.return_value = self.videos
        self.storage.group_by_hash.return_value = {}
        # T6.2: get_video / get_match 供 _enrich_groups 使用
        self.storage.get_video.side_effect = lambda vid: _make_video(vid)
        self.storage.get_match.return_value = None
        # T6.3: load_phash 供 _compute_matched_frames 使用
        self.storage.load_phash.return_value = _seq(5)
        self.index.generate_candidates.return_value = []
        self.pipeline_cls = pipeline.CascadePipeline
        for p in self.patchers:
            p.start()
        self.addCleanup(self._stop_patchers)

    def _stop_patchers(self):
        for p in self.patchers:
            p.stop()

    def _run(self, extractor=None, cancel_event=None):
        pipe = self.pipeline_cls(
            storage=self.storage, index=self.index, extractor=extractor
        )
        return pipe.run_pipeline(self.cfg, cancel_event=cancel_event)


class TestCompleteFlow(BasePipelineTest):
    """完整流程测试。"""

    def test_basic_flow_report(self):
        """3 个视频无重复时报告字段正确。"""
        report = self._run()
        self.assertFalse(report["cancelled"])
        self.assertEqual(report["total_videos"], 3)
        self.assertEqual(report["l1_groups"], [])
        self.assertEqual(report["l2_pairs"], [])
        self.assertEqual(report["l3_pairs"], [])
        self.assertEqual(report["final_groups"], [])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["keyframes"], {})
        self.assertEqual(report["matched_frames"], [])
        # 每个视频都注册并抽帧
        self.storage.register_videos.assert_called_once_with(self.videos)
        self.assertEqual(self.storage.save_phash.call_count, 3)

    def test_l2_dedup(self):
        """候选对 sequence_score >= 阈值进 l2_pairs 并 save_match(level=2)。"""
        self.index.generate_candidates.return_value = [("v1", "v2")]
        with mock.patch.object(
            self.pipeline, "sequence_score", return_value=0.95
        ):
            report = self._run()
        self.assertEqual(report["l2_pairs"], [["v1", "v2", 0.95]])
        self.storage.save_match.assert_any_call("v1", "v2", 2, 0.95)


class TestL1Dedup(BasePipelineTest):
    """L1 文件哈希去重测试。"""

    def test_representatives_only_enter_l2(self):
        """同哈希组的重复成员不进入 L2。"""
        self.storage.group_by_hash.return_value = {"h": ["v1", "v2"]}
        report = self._run()
        self.assertEqual(report["l1_groups"], [["v1", "v2"]])
        # v1 为代表进入 L2，v2 重复被排除
        called_ids = [c.args[0] for c in self.storage.save_phash.call_args_list]
        self.assertIn("v1", called_ids)
        self.assertNotIn("v2", called_ids)


class TestL3(BasePipelineTest):
    """L3 深度特征测试。"""

    def test_l3_downgrade_when_no_extractor(self):
        """无 extractor 时跳过 L3，流程仍完成。"""
        self.index.generate_candidates.return_value = [("v1", "v2")]
        with mock.patch.object(
            self.pipeline, "sequence_score", return_value=0.6
        ):
            report = self._run(extractor=None)
        self.assertEqual(report["l3_pairs"], [])
        self.assertFalse(report["cancelled"])

    def test_l3_dedup(self):
        """suspect 对深度特征 >= 阈值进 l3_pairs 并 save_match(level=3)。"""
        self.index.generate_candidates.return_value = [("v1", "v2")]
        extractor = mock.Mock()
        extractor.extract.side_effect = lambda imgs: _norm_feats(len(imgs))
        with mock.patch.object(
            self.pipeline, "sequence_score", return_value=0.6
        ), mock.patch.object(
            self.pipeline, "deep_sequence_score", return_value=0.9
        ):
            report = self._run(extractor=extractor)
        self.assertEqual(len(report["l3_pairs"]), 1)
        a, b, score = report["l3_pairs"][0]
        self.assertEqual((a, b), ("v1", "v2"))
        self.assertGreaterEqual(score, 0.85)
        self.storage.save_match.assert_any_call("v1", "v2", 3, 0.9)


class TestFaultTolerance(BasePipelineTest):
    """容错测试。"""

    def test_sampling_error_is_skipped(self):
        """某个视频抽帧失败时记入 errors，其余正常处理。"""
        def fake_sample(path, **kwargs):
            if path == "v2":
                raise RuntimeError("decode failed")
            return self.frames, 1.0

        with mock.patch.object(
            self.pipeline, "sample_frames", side_effect=fake_sample
        ):
            report = self._run()
        self.assertTrue(any("v2" in e for e in report["errors"]))
        # 其余两个视频仍处理
        self.assertEqual(self.storage.save_phash.call_count, 2)


class TestCancel(BasePipelineTest):
    """取消测试。"""

    def test_cancel_before_scan(self):
        """cancel_event 已置位时报告 cancelled=True 并提前返回。"""
        ev = threading.Event()
        ev.set()
        report = self._run(cancel_event=ev)
        self.assertTrue(report["cancelled"])
        self.storage.register_videos.assert_not_called()


class TestCluster(BasePipelineTest):
    """聚类展开测试。"""

    def test_expand_l1_group_in_final(self):
        """L2 判重代表的 L1 组被展开到 final_groups。"""
        self.storage.group_by_hash.return_value = {"h": ["v1", "v10"]}
        self.index.generate_candidates.return_value = [("v1", "v2")]
        with mock.patch.object(
            self.pipeline, "sequence_score", return_value=0.95
        ):
            report = self._run()
        # T6.2: final_groups 为结构化 dict，检查组内是否包含 v1/v10/v2
        found = any(
            {"v1", "v10", "v2"}.issubset(
                {v["id"] for v in group["videos"]}
            )
            for group in report["final_groups"]
        )
        self.assertTrue(found)


class TestProgressAlignment(BasePipelineTest):
    """进度上报与日志对齐的回归测试（进度不得超前实际处理）。"""

    def test_l2_progress_reflects_completed_videos(self):
        """L2 进度按已完成的视频数单调推进（33/67/100），并行下仍确定。"""
        events = []

        def on_progress(percent, msg, stage):
            events.append((stage, percent))

        pipe = self.pipeline_cls(
            storage=self.storage, index=self.index, extractor=None
        )
        pipe.run_pipeline(self.cfg, progress_cb=on_progress)
        # 仅取 L2 阶段进度，3 个视频 => 0/33/67/100，单调递增
        l2 = [p for s, p in events if s == "L2 pHash 序列比对"]
        self.assertEqual(l2, [0, 33, 67, 100])

    def test_final_progress_reaches_100(self):
        """流程结束（L3 跳过）时进度最终到达 100。"""
        events = []
        pipe = self.pipeline_cls(
            storage=self.storage, index=self.index, extractor=None
        )
        pipe.run_pipeline(
            self.cfg, progress_cb=lambda p, m, s: events.append(p)
        )
        self.assertEqual(events[-1], 100)

    def test_l3_progress_reaches_100_when_extraction_fails(self):
        """L3 特征提取失败时进度仍推进并最终到达 100，不中断。"""
        self.index.generate_candidates.return_value = [("v1", "v2")]
        with mock.patch.object(
            self.pipeline, "sequence_score", return_value=0.6
        ):
            extractor = mock.Mock()
            extractor.extract.side_effect = RuntimeError("boom")
            events = []
            pipe = self.pipeline_cls(
                storage=self.storage, index=self.index, extractor=extractor
            )
            pipe.run_pipeline(
                self.cfg, progress_cb=lambda p, m, s: events.append(p)
            )
        self.assertEqual(events[-1], 100)


class TestOutputFile(BasePipelineTest):
    """输出文件测试。"""

    def test_write_json_report(self):
        """cfg 指定 output 时生成含 final_groups 的 JSON 文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            self.cfg["output"] = out
            self._run()
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("final_groups", data)
            self.assertEqual(data["total_videos"], 3)


class TestScanVideos(unittest.TestCase):
    """scan_videos 测试。"""

    def test_scan_collects_videos(self):
        """临时目录中的视频文件应被收集。"""
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.mp4", "b.mkv", "c.MOV", "note.txt", "d.avi"):
                open(os.path.join(tmp, name), "w").close()
            videos = scan_videos(tmp)
            exts = {os.path.splitext(v.path)[1].lower() for v in videos}
            self.assertEqual(exts, {".mp4", ".mkv", ".mov", ".avi"})
            self.assertEqual(len(videos), 4)

    def test_scan_subdirs_only_when_recursive(self):
        """非递归时不进入子目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "sub")
            os.makedirs(sub)
            open(os.path.join(sub, "x.mp4"), "w").close()
            self.assertEqual(len(scan_videos(tmp, recursive=False)), 0)
            self.assertEqual(len(scan_videos(tmp, recursive=True)), 1)


class TestSaveKeyframes(unittest.TestCase):
    """_save_keyframes 关键帧写盘测试。"""

    def test_save_keyframes_writes_real_jpeg_files(self):
        """应把采样帧真实保存为 JPEG 文件并返回可访问的 URL。"""
        from PIL import Image
        from fabrica.tools.video_dedup.pipeline import CascadePipeline
        from fabrica.tools.video_dedup.sampler import SampledFrame

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "fabrica.tools.video_dedup.pipeline.DEFAULT_KEYFRAME_DIR",
                os.path.join(tmp, "keyframes"),
            ):
                frames = [
                    SampledFrame(
                        idx=i,
                        ts=float(i),
                        image=Image.new("RGB", (8, 8), "red"),
                    )
                    for i in range(3)
                ]
                with mock.patch(
                    "fabrica.tools.video_dedup.pipeline.sample_frames",
                    return_value=(frames, 3.0),
                ):
                    groups = [{
                        "videos": [
                            {"id": "/tmp/v.mp4", "path": "/tmp/v.mp4"},
                        ],
                    }]
                    pipe = CascadePipeline()
                    kf = pipe._save_keyframes(groups, {}, [])
            self.assertIn("/tmp/v.mp4", kf)
            url = list(kf["/tmp/v.mp4"].values())[0]
            # URL 应指向真实存在的 JPEG 文件
            rel = url.replace("/keyframes/", "", 1)
            full = os.path.join(tmp, "keyframes", rel)
            self.assertTrue(os.path.isfile(full))
            with open(full, "rb") as fh:
                self.assertTrue(fh.read().startswith(b"\xff\xd8"))


class TestBlackFrameFiltering(unittest.TestCase):
    """黑帧过滤测试。"""

    def test_is_near_black(self):
        """接近纯黑的黑图返回 True，亮图返回 False。"""
        from PIL import Image
        from fabrica.tools.video_dedup.pipeline import CascadePipeline

        black = Image.new("RGB", (8, 8), (0, 0, 0))
        bright = Image.new("RGB", (8, 8), (200, 200, 200))
        self.assertTrue(CascadePipeline._is_near_black(black))
        self.assertFalse(CascadePipeline._is_near_black(bright))

    def test_select_keyframes_filters_black_frames(self):
        """含黑帧的采样帧经 _save_keyframes 保存后，黑帧不被保存。"""
        from PIL import Image
        from fabrica.tools.video_dedup.pipeline import (
            CascadePipeline, DEFAULT_KEYFRAME_DIR,
        )
        from fabrica.tools.video_dedup.sampler import SampledFrame

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "fabrica.tools.video_dedup.pipeline.DEFAULT_KEYFRAME_DIR",
                os.path.join(tmp, "keyframes"),
            ):
                frames = [
                    SampledFrame(
                        idx=i,
                        ts=float(i),
                        image=Image.new("RGB", (8, 8), "red"),
                    )
                    for i in range(3)
                ]
                # 把 idx=1 的帧替换为纯黑帧
                frames[1] = SampledFrame(
                    idx=1, ts=1.0,
                    image=Image.new("RGB", (8, 8), (0, 0, 0)),
                )
                with mock.patch(
                    "fabrica.tools.video_dedup.pipeline.sample_frames",
                    return_value=(frames, 3.0),
                ):
                    groups = [{
                        "videos": [
                            {"id": "/tmp/v.mp4", "path": "/tmp/v.mp4"},
                        ],
                    }]
                    pipe = CascadePipeline()
                    kf = pipe._save_keyframes(groups, {}, [])
            self.assertIn("/tmp/v.mp4", kf)
            url_map = kf["/tmp/v.mp4"]
            # 黑帧 idx=1 不应被保存
            self.assertNotIn(1, url_map)
            self.assertEqual(len(url_map), 2)

    def test_select_keyframes_falls_back_when_all_black(self):
        """全部接近纯黑时仍回退保存原始帧（不产生空列）。"""
        from PIL import Image
        from fabrica.tools.video_dedup.pipeline import (
            CascadePipeline, DEFAULT_KEYFRAME_DIR,
        )
        from fabrica.tools.video_dedup.sampler import SampledFrame

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "fabrica.tools.video_dedup.pipeline.DEFAULT_KEYFRAME_DIR",
                os.path.join(tmp, "keyframes"),
            ):
                frames = [
                    SampledFrame(
                        idx=i,
                        ts=float(i),
                        image=Image.new("RGB", (8, 8), (0, 0, 0)),
                    )
                    for i in range(3)
                ]
                with mock.patch(
                    "fabrica.tools.video_dedup.pipeline.sample_frames",
                    return_value=(frames, 3.0),
                ):
                    groups = [{
                        "videos": [
                            {"id": "/tmp/v.mp4", "path": "/tmp/v.mp4"},
                        ],
                    }]
                    pipe = CascadePipeline()
                    kf = pipe._save_keyframes(groups, {}, [])
            self.assertIn("/tmp/v.mp4", kf)
            # 全黑时回退，仍保存原始帧
            self.assertEqual(len(kf["/tmp/v.mp4"]), 3)


if __name__ == "__main__":
    unittest.main()