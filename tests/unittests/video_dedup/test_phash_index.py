"""FAISS 二进制索引测试。

测试目标：fabrica/tools/video_dedup/indexing/phash_index.py
覆盖：PHashIndex 的 add / search / generate_candidates
"""

import unittest

import numpy as np

from fabrica.tools.video_dedup.indexing import PHashIndex


class TestPHashIndex(unittest.TestCase):
    """PHashIndex 索引测试集。"""

    def setUp(self):
        rng = np.random.default_rng(0)
        self.seqs = {
            f"v{i}": rng.integers(0, 2**64, 10, dtype=np.uint64)
            for i in range(3)
        }

    def _build_index(self):
        idx = PHashIndex()
        for vid, seq in self.seqs.items():
            idx.add(vid, seq)
        return idx

    def test_search_returns_expected_shape(self):
        """search 应返回 [n_frames, k] 的 distances/indices。"""
        idx = self._build_index()
        distances, indices = idx.search(self.seqs["v0"], k=5)
        self.assertEqual(distances.shape, (10, 5))
        self.assertEqual(indices.shape, (10, 5))

    def test_identical_sequence_distance_zero(self):
        """完全相同的序列应返回汉明距离 0。"""
        idx = self._build_index()
        distances, _ = idx.search(self.seqs["v0"], k=1)
        self.assertEqual(int(distances[0][0]), 0)

    def test_generate_candidates_finds_shared_frames(self):
        """共享多数帧的视频应被识别为候选对。"""
        idx = PHashIndex()
        rng = np.random.default_rng(1)
        seq_a = np.arange(10, dtype=np.uint64)
        seq_b = np.concatenate(
            [seq_a[:8], rng.integers(0, 2**64, 2, dtype=np.uint64)]
        )
        seq_c = rng.integers(0, 2**64, 10, dtype=np.uint64)
        idx.add("A", seq_a)
        idx.add("B", seq_b)
        idx.add("C", seq_c)
        candidates = idx.generate_candidates(
            ["A", "B", "C"], hit_threshold=3
        )
        self.assertIn(("A", "B"), candidates)

    def test_unrelated_videos_not_candidates(self):
        """相互无关的视频不应产生候选对。"""
        idx = PHashIndex()
        rng = np.random.default_rng(2)
        seq_a = rng.integers(
            0, 2**64, 10, dtype=np.uint64
        )
        seq_b = rng.integers(
            0, 2**64, 10, dtype=np.uint64
        )
        idx.add("A", seq_a)
        idx.add("B", seq_b)
        candidates = idx.generate_candidates(
            ["A", "B"], hit_threshold=3
        )
        self.assertNotIn(("A", "B"), candidates)

    def test_search_empty_query(self):
        """空查询序列应返回空结果而不抛异常。"""
        idx = self._build_index()
        empty = np.array([], dtype=np.uint64)
        distances, indices = idx.search(empty, k=5)
        self.assertEqual(len(distances), 0)
        self.assertEqual(len(indices), 0)

    def test_generate_candidates_empty_video_list(self):
        """空视频列表应返回空候选列表。"""
        idx = self._build_index()
        self.assertEqual(idx.generate_candidates([]), [])


if __name__ == "__main__":
    unittest.main()