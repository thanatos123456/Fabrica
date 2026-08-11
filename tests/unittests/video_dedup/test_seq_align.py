"""序列对齐打分器测试。

测试目标：fabrica/tools/video_dedup/matching/seq_align.py
覆盖：hamming、sequence_score、判定阈值常量
"""

import unittest

import numpy as np

from fabrica.tools.video_dedup.matching import (
    hamming,
    sequence_score,
    LEVEL2_THRESHOLD,
    SUSPECT_THRESHOLD,
)


# ============================================================================
# hamming 测试
# ============================================================================

class TestHamming(unittest.TestCase):
    """hamming 函数测试集。"""

    def test_all_bits_differ_returns_64(self):
        """0 与全 1 指纹汉明距离应为 64。"""
        self.assertEqual(hamming(0x0, 0xFFFFFFFFFFFFFFFF), 64)

    def test_identical_returns_zero(self):
        """相同指纹汉明距离应为 0。"""
        self.assertEqual(hamming(0xDEADBEEF, 0xDEADBEEF), 0)

    def test_single_bit_differs(self):
        """仅一位不同应返回 1。"""
        self.assertEqual(hamming(0x0, 0x1), 1)

    def test_accepts_uint64(self):
        """应接受 np.uint64 输入。"""
        self.assertEqual(
            hamming(np.uint64(0), np.uint64(0xFFFFFFFFFFFFFFFF)), 64
        )


# ============================================================================
# sequence_score 测试
# ============================================================================

class TestSequenceScore(unittest.TestCase):
    """sequence_score 函数测试集。"""

    def test_identical_sequences_return_one(self):
        """完全相同序列应返回 1.0。"""
        seq = np.arange(20, dtype=np.uint64)
        self.assertEqual(sequence_score(seq, seq), 1.0)

    def test_subsequence_returns_one(self):
        """子序列与完整序列应返回 1.0（短序列命中全部帧）。"""
        seq = np.arange(20, dtype=np.uint64)
        self.assertEqual(sequence_score(seq[:10], seq), 1.0)

    def test_random_sequences_below_half(self):
        """随机不同序列应返回 < 0.5。"""
        rng = np.random.default_rng(1)
        x = rng.integers(0, 2**64, 30, dtype=np.uint64)
        y = rng.integers(0, 2**64, 30, dtype=np.uint64)
        self.assertLess(sequence_score(x, y), 0.5)

    def test_empty_sequence_returns_zero(self):
        """任一序列为空应返回 0.0。"""
        seq = np.arange(10, dtype=np.uint64)
        self.assertEqual(
            sequence_score(np.array([], dtype=np.uint64), seq), 0.0
        )

    def test_frame_thresh_parameter_affects_score(self):
        """frame_thresh 越大命中率越高（分数越高）。"""
        rng = np.random.default_rng(2)
        x = rng.integers(0, 2**64, 20, dtype=np.uint64)
        y = rng.integers(0, 2**64, 20, dtype=np.uint64)
        strict = sequence_score(x, y, frame_thresh=0)
        loose = sequence_score(x, y, frame_thresh=32)
        self.assertGreaterEqual(loose, strict)

    def test_temporal_alignment(self):
        """时序对齐：乱序命中应显著降低得分。"""
        a1 = np.uint64(0x1111111111111111)
        a2 = np.uint64(0x2222222222222222)
        a3 = np.uint64(0x3333333333333333)
        short = np.array([a1, a2, a3], dtype=np.uint64)
        # 同序完全一致子序列 -> 1.0
        self.assertEqual(sequence_score(short, short, frame_thresh=0), 1.0)
        # 倒序：独立命中为 1.0，时序对齐下仅首帧可顺序命中 -> 显著降低
        long_rev = short[::-1]
        self.assertLess(
            sequence_score(short, long_rev, frame_thresh=0), 0.5
        )


# ============================================================================
# 判定阈值常量测试
# ============================================================================

class TestThresholdConstants(unittest.TestCase):
    """判重阈值常量测试集。"""

    def test_level2_threshold(self):
        """L2 直接判重阈值应为 0.90。"""
        self.assertEqual(LEVEL2_THRESHOLD, 0.90)

    def test_suspect_threshold(self):
        """L3 疑似判定阈值应为 0.50。"""
        self.assertEqual(SUSPECT_THRESHOLD, 0.50)

    def test_thresholds_ordering(self):
        """L2 阈值应高于疑似阈值。"""
        self.assertGreater(LEVEL2_THRESHOLD, SUSPECT_THRESHOLD)


if __name__ == "__main__":
    unittest.main()