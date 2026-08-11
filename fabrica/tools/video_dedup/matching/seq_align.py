"""pHash 序列对齐打分器（T4.6）。

对候选视频对的 pHash 序列计算相似度（0~1）。以短序列为基准，
短序列每帧在长序列中找汉明距离最小的帧，命中比例即为相似度。

判定阈值（供上层使用）：
- >= 0.90  直接判重（Level 2）
- [0.50, 0.90)  疑似（进入 L3）
- < 0.50   不判重

用法：
    from fabrica.tools.video_dedup.matching import hamming, sequence_score

    score = sequence_score(seq_a, seq_b)   # 0~1
"""

from typing import Sequence, Union

import numpy as np


# ============================================================================
# 判定阈值常量
# ============================================================================

LEVEL2_THRESHOLD = 0.90   # >= 0.90 直接判重（Level 2）
SUSPECT_THRESHOLD = 0.50  # [0.50, 0.90) 疑似，进入 L3；< 0.50 不判重
# T5.7 调参：默认帧汉明距离命中阈值由 8 提升到 16，
# 以覆盖水印/裁剪等派生版本在 pHash 上较高的帧间差异。
DEFAULT_FRAME_THRESH = 16


# ============================================================================
# 汉明距离
# ============================================================================

def hamming(a: Union[int, np.uint64], b: Union[int, np.uint64]) -> int:
    """计算两个 64bit 指纹的汉明距离。

    Args:
        a: 第一个指纹（int 或 np.uint64）。
        b: 第二个指纹（int 或 np.uint64）。

    Returns:
        十进制整数，表示两指纹不同的 bit 数。
    """
    return bin(int(a) ^ int(b)).count("1")


# ============================================================================
# 序列相似度
# ============================================================================

def _monotonic_hits(
    dists: np.ndarray,
    frame_thresh: int,
) -> int:
    """贪心双指针顺序匹配，统计在时间上单调对齐的命中帧数。

    对 short 序列的每一帧，在 long 序列中从当前指针位置向后找
    第一个汉明距离不超过 frame_thresh 的帧；找到则命中并让指针
    单调前进，找不到则指针保持不变（允许跳过该帧）。这样强制
    命中帧在 long 序列中按时间顺序递增，可拒绝不同视频偶然产生的
    乱序 pHash 命中。

    Args:
        dists: 汉明距离矩阵，shape [len(short), len(long)]。
        frame_thresh: 帧汉明距离命中阈值。

    Returns:
        在时间顺序上单调对齐的命中帧数。
    """
    n_short, n_long = dists.shape
    long_ptr = 0
    hits = 0
    for i in range(n_short):
        # 从当前指针向后找第一个可命中的帧（单调前进）
        for j in range(long_ptr, n_long):
            if int(dists[i, j]) <= frame_thresh:
                hits += 1
                long_ptr = j + 1
                break
    return hits


def sequence_score(
    seq_a: Sequence,
    seq_b: Sequence,
    frame_thresh: int = DEFAULT_FRAME_THRESH,
) -> float:
    """计算两条 pHash 序列的相似度（0~1）。

    以短序列为基准，短序列每帧在长序列中按时间顺序（单调递增）
    寻找汉明距离不超过 frame_thresh 的帧；命中比例 = 命中帧数 /
    短序列长度。时序对齐约束使真重复（时间结构一致）得分高，
    而不同视频的偶然乱序 pHash 命中得分显著降低。

    Args:
        seq_a: 序列 A（np.ndarray uint64 或 python 序列）。
        seq_b: 序列 B。
        frame_thresh: 帧汉明距离命中阈值，默认 16。

    Returns:
        0~1 的相似度。任一序列为空时返回 0.0。
    """
    a = np.asarray(seq_a).astype(np.uint64)
    b = np.asarray(seq_b).astype(np.uint64)
    if a.size == 0 or b.size == 0:
        return 0.0

    # 以短序列为基准
    if a.size > b.size:
        short, long = b, a
    else:
        short, long = a, b

    # 全量汉明距离矩阵 [len(short), len(long)]
    dists = np.bitwise_count(short[:, None] ^ long[None, :])
    hits = _monotonic_hits(dists, frame_thresh)
    return hits / short.size