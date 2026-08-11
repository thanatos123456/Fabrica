"""DeepIndex 深度特征索引测试。

测试目标：fabrica/tools/video_dedup/indexing/deep_index.py
覆盖：add/search 最近邻检索、generate_candidates 命中计数与 sim_thresh 过滤
"""

import unittest

import numpy as np

from fabrica.tools.video_dedup.indexing import DeepIndex


def _unit(e: int, dim: int = 8) -> np.ndarray:
    """构造第 e 个标准基向量（L2 归一化，用于产生确定余弦值）。"""
    vec = np.zeros(dim, dtype=np.float32)
    vec[e] = 1.0
    return vec


class TestDeepIndex(unittest.TestCase):
    """DeepIndex 索引测试集。"""

    def test_add_and_search_returns_nearest(self):
        """search 应返回余弦相似度最高的最近邻。"""
        index = DeepIndex(dim=8, k=4)
        index.add("v1", _unit(0))
        index.add("v2", _unit(1))
        index.add("v3", _unit(2))
        scores, indices = index.search(_unit(0))
        # v1 与查询向量同向（内积 1.0），为唯一最高相似度最近邻（offset 0）
        self.assertEqual(int(indices[0][0]), 0)
        self.assertAlmostEqual(float(scores[0][0]), 1.0)

    def test_generate_candidates_counts_hits(self):
        """相似特征应计为命中并生成候选对，正交特征不命中。"""
        index = DeepIndex(dim=8, k=4)
        index.add("v1", _unit(0))
        index.add("v2", _unit(0))
        index.add("v3", _unit(1))
        pairs = index.generate_candidates(
            ["v1", "v2", "v3"], hit_threshold=1, sim_thresh=0.5
        )
        self.assertIn(("v1", "v2"), pairs)
        self.assertNotIn(("v1", "v3"), pairs)

    def test_generate_candidates_respects_sim_thresh(self):
        """sim_thresh 高于命中相似度时应过滤掉候选对。"""
        index = DeepIndex(dim=8, k=4)
        index.add("v1", _unit(0))
        index.add("v2", _unit(0))
        # v1 与 v2 相似度 1.0，但把阈值设为 1.5（>内积上界）应无命中
        pairs = index.generate_candidates(
            ["v1", "v2"], hit_threshold=1, sim_thresh=1.5
        )
        self.assertEqual(pairs, [])

    def test_generate_candidates_respects_hit_threshold(self):
        """命中帧数低于 hit_threshold 时应排除候选对。"""
        index = DeepIndex(dim=8, k=4)
        # 单帧相似（v1 与 v2 同向），双向命中计数共 2 次
        index.add("v1", _unit(0))
        index.add("v2", _unit(0))
        # hit_threshold=1 时命中（2 >= 1）
        pairs_one = index.generate_candidates(
            ["v1", "v2"], hit_threshold=1, sim_thresh=0.5
        )
        self.assertIn(("v1", "v2"), pairs_one)
        # hit_threshold=3 时不命中（2 < 3）
        pairs_three = index.generate_candidates(
            ["v1", "v2"], hit_threshold=3, sim_thresh=0.5
        )
        self.assertNotIn(("v1", "v2"), pairs_three)

    def test_add_1d_feats_is_supported(self):
        """单帧特征（1D 数组）应被统一为 [1, dim]。"""
        index = DeepIndex(dim=8, k=4)
        index.add("v1", _unit(0))
        self.assertEqual(index._videos["v1"].shape, (1, 8))


if __name__ == "__main__":
    unittest.main()