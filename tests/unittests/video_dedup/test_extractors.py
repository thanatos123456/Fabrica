"""提取器模块测试。

测试目标：fabrica/tools/video_dedup/extractors/
覆盖：filehash 的 file_hash；phash 的 frame_phash / video_phash_sequence
"""

import hashlib
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from tests.unittests.video_dedup.fixtures import make_image, sampled_frames

from fabrica.tools.video_dedup.extractors import (
    file_hash,
    frame_phash,
    video_phash_sequence,
)


def _hamming(a, b):
    """计算两个 64bit 指纹的汉明距离。"""
    return bin(int(a) ^ int(b)).count("1")


# ============================================================================
# file_hash 测试
# ============================================================================

class TestFileHash(unittest.TestCase):
    """file_hash 函数测试集。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "data.bin")
        with open(self.path, "wb") as f:
            f.write(bytes(range(256)) * 1000)

    def test_same_file_returns_same_hash(self):
        """同一文件多次调用应返回相同哈希。"""
        self.assertEqual(file_hash(self.path), file_hash(self.path))

    def test_matches_hashlib_reference(self):
        """结果应与 hashlib.md5 直接计算一致。"""
        with open(self.path, "rb") as f:
            expected = hashlib.md5(f.read()).hexdigest()
        self.assertEqual(file_hash(self.path), expected)

    def test_different_files_differ(self):
        """不同文件应返回不同哈希。"""
        other = os.path.join(self.tmpdir, "other.bin")
        with open(other, "wb") as f:
            f.write(bytes(range(256)) * 1000 + b"X")
        self.assertNotEqual(file_hash(self.path), file_hash(other))

    def test_custom_block_size_consistent(self):
        """自定义 block_size 应产生一致结果。"""
        self.assertEqual(
            file_hash(self.path, block_size=2),
            file_hash(self.path),
        )

    def test_missing_file_raises(self):
        """文件不存在应抛出 FileNotFoundError。"""
        with self.assertRaises(FileNotFoundError):
            file_hash(os.path.join(self.tmpdir, "nope.bin"))


# ============================================================================
# frame_phash 测试
# ============================================================================

class TestFramePhash(unittest.TestCase):
    """frame_phash 函数测试集。"""

    def test_same_image_same_value(self):
        """相同图像应返回相同 pHash。"""
        img = make_image()
        self.assertEqual(frame_phash(img), frame_phash(img))

    def test_returns_uint64(self):
        """返回值应为 np.uint64 类型。"""
        self.assertIsInstance(frame_phash(make_image()), np.uint64)

    def test_similar_closer_than_different(self):
        """相似图像汉明距离应小于不同图像。"""
        base = make_image()
        similar = make_image(color=(121, 81, 41))
        different = Image.effect_noise((128, 128), 200).convert("RGB")
        d_sim = _hamming(frame_phash(base), frame_phash(similar))
        d_diff = _hamming(frame_phash(base), frame_phash(different))
        self.assertLess(d_sim, d_diff)


# ============================================================================
# video_phash_sequence 测试
# ============================================================================

class TestVideoPhashSequence(unittest.TestCase):
    """video_phash_sequence 函数测试集。"""

    def test_shape_and_dtype(self):
        """返回数组应为 [n] 且 dtype uint64。"""
        seq = video_phash_sequence(sampled_frames(10))
        self.assertEqual(seq.shape, (10,))
        self.assertEqual(seq.dtype, np.uint64)

    def test_matches_per_frame_values(self):
        """序列应与逐帧 frame_phash 结果一致。"""
        frames = sampled_frames(5)
        seq = video_phash_sequence(frames)
        expected = np.array(
            [frame_phash(f.image) for f in frames], dtype=np.uint64
        )
        np.testing.assert_array_equal(seq, expected)


if __name__ == "__main__":
    unittest.main()