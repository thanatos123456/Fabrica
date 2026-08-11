"""VideoStorage 深度特征 .npy 存储测试（T5.5）。

测试目标：fabrica/tools/video_dedup/storage.py 的 save_deep / load_deep /
feature_dir / _safe_feature_name。
用临时 feature_dir 与 :memory: 数据库隔离测试。
"""

import os
import tempfile
import unittest

import numpy as np

from fabrica.tools.video_dedup.storage import (
    DEEP_FEATURE_DIM,
    VideoStorage,
)
from fabrica.tools.video_dedup.models import VideoInfo


def _feats(n):
    rng = np.random.default_rng(0)
    return rng.standard_normal((n, DEEP_FEATURE_DIM)).astype(np.float32)


class DeepStorageTest(unittest.TestCase):
    """深度特征存储测试基类（临时目录）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.feature_dir = os.path.join(self._tmp.name, "feats")
        self.storage = VideoStorage(
            db_path=":memory:", feature_dir=self.feature_dir
        )
        # 注册一个视频以便断言 deep_done
        self.storage.register_videos(
            [
                VideoInfo(
                    id="v1", path="v1", size=100, duration=1.0,
                    width=320, height=240, file_hash="h", frame_count=5,
                )
            ]
        )

    def tearDown(self):
        self.storage.close()
        self._tmp.cleanup()


class TestSaveLoadDeep(DeepStorageTest):
    """save_deep / load_deep 往返测试。"""

    def test_roundtrip(self):
        """save_deep 后 load_deep 返回相同数据。"""
        arr = _feats(5)
        self.storage.save_deep("v1", arr)
        loaded = self.storage.load_deep("v1")
        np.testing.assert_array_equal(loaded, arr)
        self.assertEqual(loaded.dtype, np.float32)

    def test_file_exists_with_naming(self):
        """保存后生成 {md5(video_id)}.npy 文件。"""
        self.storage.save_deep("v1", _feats(3))
        expected = VideoStorage._safe_feature_name("v1")
        self.assertTrue(
            os.path.exists(os.path.join(self.feature_dir, expected))
        )

    def test_load_missing_returns_empty(self):
        """不存在文件返回 (0, DEEP_FEATURE_DIM) 空数组。"""
        loaded = self.storage.load_deep("missing")
        self.assertEqual(loaded.shape, (0, DEEP_FEATURE_DIM))
        self.assertEqual(loaded.dtype, np.float32)

    def test_deep_done_flag(self):
        """save_deep 后 videos.deep_done = 1。"""
        self.storage.save_deep("v1", _feats(2))
        row = self.storage._conn.execute(
            "SELECT deep_done FROM videos WHERE id = 'v1'"
        ).fetchone()
        self.assertEqual(row["deep_done"], 1)

    def test_overwrite(self):
        """同 id 二次保存返回新值。"""
        self.storage.save_deep("v1", _feats(4))
        first = self.storage.load_deep("v1")
        new_arr = _feats(6)
        self.storage.save_deep("v1", new_arr)
        second = self.storage.load_deep("v1")
        self.assertEqual(second.shape, (6, DEEP_FEATURE_DIM))
        np.testing.assert_array_equal(second, new_arr)
        self.assertNotEqual(second.shape, first.shape)


class TestFeatureDir(DeepStorageTest):
    """feature_dir 配置测试。"""

    def test_explicit_feature_dir(self):
        """显式指定 feature_dir 生效。"""
        self.assertEqual(self.storage.feature_dir, self.feature_dir)

    def test_directory_created(self):
        """feature_dir 目录自动创建。"""
        self.assertTrue(os.path.isdir(self.feature_dir))


class TestSafeFeatureName(unittest.TestCase):
    """_safe_feature_name 测试。"""

    def test_returns_npy_extension(self):
        """返回值以 .npy 结尾。"""
        name = VideoStorage._safe_feature_name("v1")
        self.assertTrue(name.endswith(".npy"))

    def test_no_path_separators_or_colon(self):
        """文件名不含路径分隔符或冒号。"""
        for vid in ["/data/video.mp4", "a\\b.mp4", "H:\\wallpaper\\x.mp4"]:
            name = VideoStorage._safe_feature_name(vid)
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertNotIn(":", name)

    def test_deterministic(self):
        """相同输入产生相同输出。"""
        self.assertEqual(
            VideoStorage._safe_feature_name("v1"),
            VideoStorage._safe_feature_name("v1"),
        )

    def test_different_inputs_different_names(self):
        """不同输入产生不同输出。"""
        self.assertNotEqual(
            VideoStorage._safe_feature_name("v1"),
            VideoStorage._safe_feature_name("v2"),
        )

    def test_windows_path_safe(self):
        """Windows 盘符路径生成安全文件名（回归测试）。

        修复前：H:\\wallpaper\\x.mp4 → H:_wallpaper_x.mp4.npy，
        os.path.join 将 H: 解释为盘符切换，文件创建在错误盘符位置。
        修复后：使用 MD5 哈希，无盘符问题。
        """
        name = VideoStorage._safe_feature_name("H:\\wallpaper\\x.mp4")
        self.assertNotIn(":", name)
        self.assertNotIn("\\", name)
        self.assertTrue(name.endswith(".npy"))
        # 文件名应为 32 字符 MD5 + .npy
        self.assertEqual(len(name), 36)


class TestPathIdRoundtrip(DeepStorageTest):
    """路径型 video_id 往返一致性。"""

    def test_path_id_roundtrip(self):
        """含路径分隔符的 id 保存后能正确加载。"""
        vid = "/data/movies/新闻联播.mp4"
        arr = _feats(4)
        self.storage.save_deep(vid, arr)
        loaded = self.storage.load_deep(vid)
        np.testing.assert_array_equal(loaded, arr)


if __name__ == "__main__":
    unittest.main()