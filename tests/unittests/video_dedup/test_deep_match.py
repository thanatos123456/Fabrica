"""深度特征比对器测试（T5.2）。

测试目标：fabrica/tools/video_dedup/matching/deep_match.py
覆盖：deep_sequence_score 的命中判定、短序列基准、空输入、
1D 输入、阈值效果与矩阵内积等价性。
"""

import unittest

import numpy as np

from fabrica.tools.video_dedup.matching.deep_match import (
    DEFAULT_SIM_THRESH,
    LEVEL3_THRESHOLD,
    deep_sequence_score,
)


# ============================================================================
# 辅助
# ============================================================================

def _normalize(arr):
    """返回 L2 归一化后的副本。"""
    arr = np.asarray(arr, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=-1, keepdims=True)
    return arr / np.maximum(norms, 1e-8)


def _feats(rows):
    """构造 [n, dim] 均值向量并 L2 归一化。"""
    rng = np.random.default_rng(0)
    base = rng.standard_normal((1, 16))
    feats = np.repeat(base, rows, axis=0) + rng.standard_normal((rows, 16)) * 0.01
    return _normalize(feats)


def _brute(a, b, sim_thresh):
    """逐帧暴力内积比对（参考实现）。"""
    short, long_ = (a, b) if a.shape[0] <= b.shape[0] else (b, a)
    hits = 0
    for i in range(short.shape[0]):
        best = max(float(short[i] @ long_[j]) for j in range(long_.shape[0]))
        if best >= sim_thresh:
            hits += 1
    return hits / short.shape[0]


# ============================================================================
# 测试
# ============================================================================

class TestDeepSequenceScore(unittest.TestCase):
    """deep_sequence_score 函数测试集。"""

    def test_identical_sequence_returns_1(self):
        """完全相同的特征序列应返回 1.0。"""
        feats = _feats(5)
        self.assertEqual(deep_sequence_score(feats, feats), 1.0)

    def test_orthogonal_returns_0(self):
        """正交（余弦为 0）的序列应返回 0.0。"""
        a = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
        b = np.array([[0.0, 1.0], [0.0, 1.0]], dtype=np.float32)
        self.assertEqual(deep_sequence_score(a, b), 0.0)

    def test_partial_match_returns_ratio(self):
        """4 帧中 2 帧命中应返回 0.5。"""
        e1 = np.array([1.0, 0.0], dtype=np.float32)
        e2 = np.array([0.0, 1.0], dtype=np.float32)
        a = np.stack([e1, e1, e1, e1])  # 4 帧全 e1
        b = np.stack([e1, e1, e2, e2])  # 2 帧 e1、2 帧 e2
        # 每帧在对方中都能找到完全相同的帧，命中全部 -> 不应测这个
        # 改用只含 e2 的序列 B，使 A 中只有 e1 与 B 无关 -> 命中 0
        b_only_e2 = np.stack([e2, e2, e2, e2])
        self.assertEqual(deep_sequence_score(a, b_only_e2), 0.0)
        # 半命中：A 中 2 帧 e1、2 帧 e2，B 全 e2 -> 命中 0.5
        a_half = np.stack([e1, e1, e2, e2])
        self.assertEqual(deep_sequence_score(a_half, b_only_e2), 0.5)

    def test_empty_input_returns_0(self):
        """任一序列为空应返回 0.0。"""
        empty = np.zeros((0, 16), dtype=np.float32)
        feats = _feats(3)
        self.assertEqual(deep_sequence_score(empty, feats), 0.0)
        self.assertEqual(deep_sequence_score(feats, empty), 0.0)

    def test_short_sequence_is_basis(self):
        """以短序列为基准：a 长于 b 时结果与以 b 为基准一致。"""
        a = _feats(8)
        b = _feats(3)
        b_long = _feats(8)
        a_short = _feats(3)
        # b(3) 与 b_long(8) 同源，a(8) 与 a_short(3) 同源
        self.assertEqual(
            deep_sequence_score(b, a), deep_sequence_score(a, b)
        )
        self.assertEqual(
            deep_sequence_score(a_short, b_long),
            deep_sequence_score(b_long, a_short),
        )

    def test_1d_single_frame(self):
        """1D 单帧输入与自身比较应返回 1.0。"""
        vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        self.assertEqual(deep_sequence_score(vec, vec), 1.0)

    def test_higher_threshold_lowers_score(self):
        """sim_thresh 调高应降低得分。"""
        feats = _feats(6)
        low = deep_sequence_score(feats, feats, sim_thresh=0.90)
        high = deep_sequence_score(feats, feats, sim_thresh=0.99)
        self.assertGreaterEqual(low, high)

    def test_custom_threshold_hit_ratio(self):
        """自定义 sim_thresh 时命中比例正确。"""
        e1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        e2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        a = np.stack([e1, e1, e2, e2])
        b = np.stack([e1, e2, e2, e2])
        # 阈值 0.0：全都命中 -> 1.0
        self.assertEqual(deep_sequence_score(a, b, sim_thresh=0.0), 1.0)
        # 阈值 0.5：全命中（1 或 0 余弦）-> 1.0
        self.assertEqual(deep_sequence_score(a, b, sim_thresh=0.5), 1.0)

    def test_matches_brute_force(self):
        """矩阵内积结果应与逐帧暴力比对一致。"""
        rng = np.random.default_rng(1)
        a_raw = _normalize(rng.standard_normal((5, 16)))
        b_raw = _normalize(rng.standard_normal((7, 16)))
        for thresh in (0.0, 0.3, 0.6, 0.9):
            self.assertEqual(
                deep_sequence_score(a_raw, b_raw, sim_thresh=thresh),
                _brute(a_raw, b_raw, sim_thresh=thresh),
            )

    def test_l3_threshold_constant(self):
        """LEVEL3_THRESHOLD 应为 0.85。"""
        self.assertEqual(LEVEL3_THRESHOLD, 0.85)

    def test_default_sim_thresh_constant(self):
        """DEFAULT_SIM_THRESH 应为 0.92。"""
        self.assertEqual(DEFAULT_SIM_THRESH, 0.92)


if __name__ == "__main__":
    unittest.main()