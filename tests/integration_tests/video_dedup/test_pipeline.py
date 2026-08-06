"""级联验重管线集成测试（T5.6）。

使用真实组件（VideoStorage + PHashIndex + sample_frames + phash + 序列比对）
与 PyAV 生成的真实视频，验证 CascadePipeline 的端到端判重行为：
- 同视频不同分辨率 / 加水印 / 裁剪 → 判为重复
- 不同内容视频 → 不判为重复
- 小样本（10 视频）含重复对 → 正确检出

L3 深度特征在无 open_clip 时自动降级，不影响 L1/L2。
"""

import os
import tempfile
import unittest

from tests.fixtures.video_factory import (
    create_derived_video,
    create_test_video,
)

from fabrica.tools.video_dedup.pipeline import CascadePipeline


def _run_pipeline(input_dir):
    """在临时数据库上运行完整管线，返回报告。"""
    with tempfile.TemporaryDirectory() as dbdir:
        db_path = os.path.join(dbdir, "dedup.db")
        cfg = {
            "input_dir": input_dir,
            "output": None,
            "recursive": False,
            "device": "cpu",
            "db_path": db_path,
        }
        return CascadePipeline().run_pipeline(cfg)


def _contains(group, name):
    """判断组内是否存在指定 basename。"""
    return any(os.path.basename(item) == name for item in group)


def _group_contains(report, a, b):
    """检查 a、b（basename）是否出现在同一个 final_group 中。"""
    return any(
        _contains(group, a) and _contains(group, b)
        for group in report["final_groups"]
    )


class BaseIntegrationTest(unittest.TestCase):
    """集成测试基类：临时目录。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.video_dir = os.path.join(self._tmp.name, "videos")
        os.makedirs(self.video_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _vpath(self, name):
        return os.path.join(self.video_dir, name)


class TestDerivedDuplicates(BaseIntegrationTest):
    """同内容派生版本应判为重复。"""

    def test_resize_is_duplicate(self):
        """同视频不同分辨率应判为重复。"""
        src = create_test_video(
            self._vpath("base.mp4"), content="resize_src"
        )
        create_derived_video(
            src, self._vpath("derived.mp4"), resize=True
        )
        report = _run_pipeline(self.video_dir)
        self.assertTrue(_group_contains(report, "base.mp4", "derived.mp4"))

    def test_watermark_is_duplicate(self):
        """加水印视频应判为重复。"""
        src = create_test_video(
            self._vpath("wm.mp4"), content="wm_src"
        )
        create_derived_video(
            src, self._vpath("wm_derived.mp4"), watermark=True
        )
        report = _run_pipeline(self.video_dir)
        self.assertTrue(_group_contains(report, "wm.mp4", "wm_derived.mp4"))

    def test_crop_is_duplicate(self):
        """裁剪视频应判为重复。"""
        src = create_test_video(
            self._vpath("crop.mp4"), content="crop_src"
        )
        create_derived_video(
            src, self._vpath("crop_derived.mp4"), crop=True
        )
        report = _run_pipeline(self.video_dir)
        self.assertTrue(_group_contains(report, "crop.mp4", "crop_derived.mp4"))


class TestDistinctVideos(BaseIntegrationTest):
    """不同内容视频不应判为重复。"""

    def test_different_content_not_duplicate(self):
        """两个不同 content 视频不应出现在同一组。"""
        create_test_video(self._vpath("a.mp4"), content="alpha")
        create_test_video(self._vpath("b.mp4"), content="bravo")
        report = _run_pipeline(self.video_dir)
        self.assertFalse(_group_contains(report, "a.mp4", "b.mp4"))


class TestSmallSample(BaseIntegrationTest):
    """小样本（10 视频）含重复对应正确检出。"""

    def test_ten_videos_with_duplicate_pair(self):
        """8 个不同视频 + 1 个衍生重复对，应检出该重复对。"""
        names = [f"v{i}.mp4" for i in range(8)]
        for i, name in enumerate(names):
            create_test_video(self._vpath(name), content=f"c{i}")
        # 第 9/10 个为重复对
        src = create_test_video(
            self._vpath("dup_a.mp4"), content="dup"
        )
        create_derived_video(
            src, self._vpath("dup_b.mp4"), resize=True
        )
        report = _run_pipeline(self.video_dir)
        self.assertEqual(report["total_videos"], 10)
        self.assertTrue(_group_contains(report, "dup_a.mp4", "dup_b.mp4"))
        # 其余 8 个不同视频互不归组
        for i in range(8):
            for j in range(i + 1, 8):
                self.assertFalse(
                    _group_contains(report, f"v{i}.mp4", f"v{j}.mp4")
                )


if __name__ == "__main__":
    unittest.main()