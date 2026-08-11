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

def _monotonic_hits(
    sim: np.ndarray,
    sim_thresh: float,
) -> int:
    """贪心双指针顺序匹配，统计在时间上单调对齐的命中帧数。

    对 short 序列的每一帧，在 long 序列中从当前指针位置向后找
    第一个余弦相似度不低于 sim_thresh 的帧；找到则命中并让指针
    单调前进，找不到则指针保持不变（允许跳过该帧）。时序对齐
    约束可拒绝不同视频偶然产生的乱序高相似命中。

    Args:
        sim: 余弦相似度矩阵，shape [len(short), len(long)]。
        sim_thresh: 单帧余弦相似度命中阈值。

    Returns:
        在时间顺序上单调对齐的命中帧数。
    """
    n_short, n_long = sim.shape
    long_ptr = 0
    hits = 0
    for i in range(n_short):
        # 从当前指针向后找第一个可命中的帧（单调前进）
        for j in range(long_ptr, n_long):
            if float(sim[i, j]) >= sim_thresh:
                hits += 1
                long_ptr = j + 1
                break
    return hits


def deep_sequence_score(
    feat_a: Sequence,
    feat_b: Sequence,
    sim_thresh: float = DEFAULT_SIM_THRESH,
) -> float:
    """计算两条深度特征序列的相似度（0~1）。

    以短序列为基准，短序列每帧在长序列中按时间顺序（单调递增）
    寻找余弦相似度不低于 sim_thresh 的帧；命中比例 = 命中帧数 /
    短序列长度。时序对齐约束使真重复（时间结构一致）得分高，
    而不同视频的偶然乱序高相似命中得分显著降低。

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
    hits = _monotonic_hits(sim, sim_thresh)
    return hits / short.shape[0]