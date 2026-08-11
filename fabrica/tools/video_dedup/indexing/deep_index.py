"""L3 CLIP 深度特征浮点索引。

使用 faiss.IndexFlatIP 管理所有视频的深度特征帧向量，
支持余弦相似度最近邻检索与候选视频对生成。

架构：
- 索引中每一行代表一个视频的某一帧的 CLIP 特征向量（L2 归一化）。
- 维护帧级映射（offset -> video_id）与视频级映射（video_id -> 帧范围）。
- 特征向量已 L2 归一化，内积等价于余弦相似度，IndexFlatIP 即余弦索引。
- search 对特征序列逐帧检索最近邻；generate_candidates 统计视频对间
  相似度超过 sim_thresh 的命中帧数，超过阈值即判为候选对。

用法：
    from fabrica.tools.video_dedup.indexing import DeepIndex

    index = DeepIndex(dim=512)
    index.add("video_1", feats)                 # feats: np.ndarray [n, 512] float32
    scores, indices = index.search(feats, k=8)
    candidates = index.generate_candidates(["video_1", "video_2"])
"""

from collections import Counter
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np


# 深度特征维度（CLIP ViT-B-32 输出维度）
DEFAULT_DIM = 512
# 默认最近邻检索数
DEFAULT_K = 32
# 候选生成时帧级余弦相似度命中阈值
DEFAULT_SIM_THRESH = 0.92


class DeepIndex:
    """CLIP 深度特征浮点索引。

    存储所有视频的帧特征向量，支持余弦相似度最近邻检索与候选对生成。
    """

    def __init__(self, dim: int = DEFAULT_DIM, k: int = DEFAULT_K) -> None:
        """初始化索引。

        Args:
            dim: 特征向量维度，默认 512。
            k: 默认最近邻检索数。
        """
        self.index = faiss.IndexFlatIP(dim)
        self.k = k
        # 帧级映射：帧 offset -> 所属 video_id
        self._offset_to_video: Dict[int, str] = {}
        # 视频级映射：video_id -> 帧 offset 范围 [start, end)
        self._id_to_range: Dict[str, Tuple[int, int]] = {}
        # 视频级数据缓存：video_id -> 特征序列（供检索查询与打分复用）
        self._videos: Dict[str, np.ndarray] = {}
        self._total = 0  # 已加入的帧总数

    @staticmethod
    def _to_float32(feats: np.ndarray) -> np.ndarray:
        """将特征序列统一为 [n, dim] float32 数组。"""
        arr = np.asarray(feats, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr

    def add(self, video_id: str, feats: np.ndarray) -> None:
        """将视频的特征序列加入索引。

        Args:
            video_id: 视频唯一标识。
            feats: 该视频的特征序列（np.ndarray [n, dim] float32）。
        """
        arr = self._to_float32(feats)
        n = len(arr)
        start = self._total
        self.index.add(arr)
        # 记录映射
        self._id_to_range[video_id] = (start, start + n)
        for i in range(start, start + n):
            self._offset_to_video[i] = video_id
        self._videos[video_id] = arr
        self._total += n

    def search(
        self,
        feats: np.ndarray,
        k: Optional[int] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """检索特征序列中每帧的最近邻。

        Args:
            feats: 查询的特征序列（np.ndarray [n, dim] float32）。
            k: 返回最近邻数，默认用初始化时的 k。

        Returns:
            (scores, indices)，shape 均为 [n_frames, k]。
            scores 为内积（=余弦相似度），indices 为 -1 表示无结果。
        """
        k = k if k is not None else self.k
        xq = self._to_float32(feats)
        scores, indices = self.index.search(xq, k)
        return scores, indices

    def generate_candidates(
        self,
        video_ids: List[str],
        hit_threshold: int = 1,
        k: Optional[int] = None,
        sim_thresh: float = DEFAULT_SIM_THRESH,
    ) -> List[Tuple[str, str]]:
        """生成候选视频对。

        对给定 video_ids 中每个视频的每一帧，检索最近 k 帧特征，
        仅将余弦相似度不低于 sim_thresh 的近邻计为命中，统计视频对
        间命中帧数，超过 hit_threshold 的判为候选对。

        Args:
            video_ids: 参与候选生成的视频 id 列表。
            hit_threshold: 命中帧数阈值。
            k: 最近邻检索数，默认用初始化时的 k。
            sim_thresh: 帧级余弦相似度命中阈值。

        Returns:
            排序后的候选视频对列表，形式为 (id_a, id_b) 且 id_a < id_b。
        """
        k = k if k is not None else self.k
        hits: Counter = Counter()
        for vid in video_ids:
            feats = self._videos.get(vid)
            if feats is None or len(feats) == 0:
                continue
            scores, indices = self.search(feats, k)
            # 对当前视频的每一帧，统计命中的其他视频
            for frame_scores, frame_hits in zip(scores, indices):
                for score, offset in zip(frame_scores, frame_hits):
                    offset = int(offset)
                    if offset < 0:
                        continue
                    # 相似度过低的近邻不计为命中，避免无关视频误判候选
                    if float(score) < sim_thresh:
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