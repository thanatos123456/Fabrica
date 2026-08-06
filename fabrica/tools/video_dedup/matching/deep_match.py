"""深度特征比对器（T5.2）。

对进入 L3 的疑似视频对，用 CLIP 深度特征序列做余弦相似度比对。
输入为 [n, dim] 已 L2 归一化的特征向量（由 CLIPExtractor.extract 生成），
L2 归一化后余弦相似度等价于内积，可用矩阵乘法 `short @ long_.T` 加速。

判定阈值（供上层使用）：
- >= 0.85  判重（Level 3 最终裁决）
- < 0.85   不判重

用法：
    from fabrica.tools.video_dedup.matching import deep_sequence_score

    score = deep_sequence_score(feat_a, feat_b)   # 0~1
"""

from typing import Sequence

import numpy as np


# ============================================================================
# 判定阈值常量
# ============================================================================

DEFAULT_SIM_THRESH = 0.92   # 单帧余弦相似度命中阈值
LEVEL3_THRESHOLD = 0.85     # >= 0.85 判重（Level 3 最终裁决）


# ============================================================================
# 深度特征序列相似度
# ============================================================================

def deep_sequence_score(
    feat_a: Sequence,
    feat_b: Sequence,
    sim_thresh: float = DEFAULT_SIM_THRESH,
) -> float:
    """计算两条深度特征序列的相似度（0~1）。

    以短序列为基准，短序列每帧在长序列中找余弦相似度最高的帧；
    最大余弦相似度 >= sim_thresh 记为命中。命中比例 = 命中帧数 / 短序列长度。

    Args:
        feat_a: 特征序列 A（[n, dim] 已 L2 归一化的数组或列表）。
        feat_b: 特征序列 B。
        sim_thresh: 单帧余弦相似度命中阈值，默认 0.92。

    Returns:
        0~1 的相似度。任一序列为空时返回 0.0。
    """
    a = np.asarray(feat_a).astype(np.float32)
    b = np.asarray(feat_b).astype(np.float32)
    if a.size == 0 or b.size == 0:
        return 0.0

    # 兼容单帧 1D 输入
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if b.ndim == 1:
        b = b.reshape(1, -1)

    # 以短序列为基准
    if a.shape[0] > b.shape[0]:
        short, long_ = b, a
    else:
        short, long_ = a, b

    # 全量余弦相似度矩阵 [len(short), len(long)]
    sim = short @ long_.T
    # 每帧取最大相似度，命中判定
    best = sim.max(axis=1)
    hits = int((best >= sim_thresh).sum())
    return hits / short.shape[0]