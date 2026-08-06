"""pHash FAISS 二进制索引（T4.5）。

使用 faiss.IndexBinaryFlat 管理所有视频的 pHash 帧指纹，
支持汉明距离最近邻检索与候选视频对生成。

架构：
- 索引中每一行代表一个视频的某一帧的 64bit pHash 指纹。
- 维护帧级映射（offset -> video_id）与视频级映射（video_id -> 帧范围）。
- search 对 phash 序列逐帧检索最近邻；generate_candidates 统计视频对间
  命中帧数，超过阈值即判为候选对。

用法：
    from fabrica.tools.video_dedup.indexing import PHashIndex

    index = PHashIndex()
    index.add("video_1", phash_seq)          # phash_seq: np.ndarray [n] uint64
    distances, indices = index.search(phash_seq, k=8)
    candidates = index.generate_candidates(["video_1", "video_2"])
"""

from collections import Counter
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np


# FAISS 二进制索引维度（bit 数）。64bit pHash 指纹 => d=64。
DEFAULT_DIM = 64
# 每行字节数：64bit / 8
BYTES_PER_FINGERPRINT = 8

# 候选生成时帧汉明距离命中阈值
# 说明：T5.7 调参将默认 8 提升到 16，以覆盖水印/裁剪等派生版本
# 在 pHash 上较高的帧间汉明距离；同时 k 默认增至 32，避免采样帧数
# （每视频约 8 帧）占满最近邻导致跨视频真匹配被挤出 top-k。
DEFAULT_FRAME_THRESH = 16


class PHashIndex:
    """pHash 二进制索引。

    存储所有视频的帧指纹，支持汉明距离最近邻检索与候选对生成。
    """

    def __init__(self, d: int = DEFAULT_DIM, k: int = 32) -> None:
        """初始化索引。

        Args:
            d: FAISS 二进制索引维度（bit），默认 64。
            k: 默认最近邻检索数。
        """
        self.index = faiss.IndexBinaryFlat(d)
        self.k = k
        # 帧级映射：帧 offset -> 所属 video_id
        self._offset_to_video: Dict[int, str] = {}
        # 视频级映射：video_id -> 帧 offset 范围 [start, end)
        self._id_to_range: Dict[str, Tuple[int, int]] = {}
        # 视频级数据缓存：video_id -> phash_seq（供检索查询）
        self._videos: Dict[str, np.ndarray] = {}
        self._total = 0  # 已加入的帧总数

    def _to_bytes(self, phash_seq: np.ndarray) -> np.ndarray:
        """将 uint64 phash 序列转为 FAISS 二进制输入（[n, 8] uint8）。"""
        arr = np.asarray(phash_seq).astype(np.uint64)
        return arr.view(np.uint8).reshape(-1, BYTES_PER_FINGERPRINT)

    def add(self, video_id: str, phash_seq: np.ndarray) -> None:
        """将视频的 pHash 序列加入索引。

        Args:
            video_id: 视频唯一标识。
            phash_seq: 该视频的 pHash 序列（np.ndarray [n] uint64）。
        """
        n = len(phash_seq)
        start = self._total
        xb = self._to_bytes(phash_seq)
        self.index.add(xb)
        # 记录映射
        self._id_to_range[video_id] = (start, start + n)
        for i in range(start, start + n):
            self._offset_to_video[i] = video_id
        self._videos[video_id] = np.asarray(phash_seq).astype(np.uint64)
        self._total += n

    def search(
        self,
        phash_seq: np.ndarray,
        k: Optional[int] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """检索 phash 序列中每帧的最近邻。

        Args:
            phash_seq: 查询的 pHash 序列（np.ndarray [n] uint64）。
            k: 返回最近邻数，默认用初始化时的 k。

        Returns:
            (distances, indices)，shape 均为 [n_frames, k]。
            indices 为 -1 表示无结果。
        """
        k = k if k is not None else self.k
        xq = self._to_bytes(phash_seq)
        distances, indices = self.index.search(xq, k)
        return distances, indices

    def generate_candidates(
        self,
        video_ids: List[str],
        hit_threshold: int = 3,
        k: Optional[int] = None,
        frame_thresh: int = DEFAULT_FRAME_THRESH,
    ) -> List[Tuple[str, str]]:
        """生成候选视频对。

        对给定 video_ids 中每个视频的每一帧，检索最近 k 帧指纹，
        仅将汉明距离不超过 frame_thresh 的近邻计为命中，统计视频对
        间命中帧数，超过 hit_threshold 的判为候选对。

        Args:
            video_ids: 参与候选生成的视频 id 列表。
            hit_threshold: 命中帧数阈值。
            k: 最近邻检索数，默认用初始化时的 k。
            frame_thresh: 帧汉明距离命中阈值，默认 8。

        Returns:
            排序后的候选视频对列表，形式为 (id_a, id_b) 且 id_a < id_b。
        """
        k = k if k is not None else self.k
        hits: Counter = Counter()
        for vid in video_ids:
            seq = self._videos.get(vid)
            if seq is None or len(seq) == 0:
                continue
            distances, indices = self.search(seq, k)
            # 对当前视频的每一帧，统计命中的其他视频
            for frame_dists, frame_hits in zip(distances, indices):
                for dist, offset in zip(frame_dists, frame_hits):
                    offset = int(offset)
                    if offset < 0:
                        continue
                    # 距离过大的近邻不计为命中，避免无关视频误判候选
                    if int(dist) > frame_thresh:
                        continue
                    hit_vid = self._offset_to_video.get(offset)
                    if hit_vid is None or hit_vid == vid:
                        continue
                    pair = tuple(sorted((vid, hit_vid)))
                    hits[pair] += 1
        # 只保留命中帧数达到阈值的视频对
        return sorted(
            pair for pair, count in hits.items() if count >= hit_threshold
        )