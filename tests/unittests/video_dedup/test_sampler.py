"""抽帧模块测试。

测试目标：fabrica/tools/video_dedup/sampler.py
覆盖：compute_sample_timestamps、sample_frames
"""

import os
import tempfile
import unittest

from tests.unittests.video_dedup.fixtures import make_video

from fabrica.tools.video_dedup.sampler import (
    compute_sample_timestamps,
    sample_frames,
)


# ============================================================================
# compute_sample_timestamps 测试
# ============================================================================

class TestComputeSampleTimestamps(unittest.TestCase):
    """compute_sample_timestamps 纯函数测试集。"""

    def test_returns_min_frames_for_short_video(self):
        """短视频（<16s）应返回 min_frames 帧。"""
        ts = compute_sample_timestamps(5.0, min_frames=8)
        self.assertEqual(len(ts), 8)

    def test_timestamps_within_valid_range(self):
        """采样时间点应落在 [0.5, duration-0.5] 区间内。"""
        ts = compute_sample_timestamps(10.0, min_frames=10)
        for t in ts:
            self.assertGreaterEqual(t, 0.5)
            self.assertLessEqual(t, 9.5)

    def test_long_video_respects_max_frames(self):
        """长视频应不超过 max_frames 且不少于 min_frames。"""
        ts = compute_sample_timestamps(
            3600.0, min_frames=8, max_frames=100, target_fps=1.0
        )
        self.assertLessEqual(len(ts), 100)
        self.assertGreaterEqual(len(ts), 8)

    def test_returns_empty_for_too_short_video(self):
        """时长过短无法避开首尾时应返回空列表。"""
        self.assertEqual(compute_sample_timestamps(0.8), [])

    def test_timestamps_uniformly_spaced(self):
        """相邻采样时间点间距应一致。"""
        ts = compute_sample_timestamps(20.0, min_frames=16)
        gaps = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
        self.assertAlmostEqual(max(gaps), min(gaps), places=6)


# ============================================================================
# sample_frames 测试
# ============================================================================

class TestSampleFrames(unittest.TestCase):
    """sample_frames 抽帧函数测试集。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_video(self, name="sample.mp4", **kwargs):
        path = os.path.join(self.tmpdir, name)
        return make_video(path, **kwargs)

    def test_returns_frames_for_real_video(self):
        """真实视频应返回 min_frames 帧、正时长与正确尺寸。"""
        path = self._make_video(duration=5.0)
        frames, duration = sample_frames(
            path, min_frames=8, max_frames=100, target_fps=1.0
        )
        self.assertEqual(len(frames), 8)
        self.assertGreater(duration, 0.0)
        for f in frames:
            self.assertEqual(f.image.size, (224, 224))

    def test_resize_parameter_takes_effect(self):
        """resize 参数应控制输出帧尺寸。"""
        path = self._make_video(duration=2.0)
        frames, _ = sample_frames(path, resize=64, min_frames=4)
        self.assertEqual(frames[0].image.size, (64, 64))

    def test_corrupt_file_returns_empty(self):
        """损坏文件应返回空列表且不抛异常。"""
        corrupt = os.path.join(self.tmpdir, "bad.mp4")
        with open(corrupt, "wb") as f:
            f.write(b"not a video at all")
        frames, duration = sample_frames(corrupt)
        self.assertEqual(frames, [])
        self.assertEqual(duration, 0.0)

    def test_missing_file_returns_empty(self):
        """不存在的文件应返回空列表且不抛异常。"""
        frames, duration = sample_frames(
            os.path.join(self.tmpdir, "missing.mp4")
        )
        self.assertEqual(frames, [])
        self.assertEqual(duration, 0.0)


if __name__ == "__main__":
    unittest.main()