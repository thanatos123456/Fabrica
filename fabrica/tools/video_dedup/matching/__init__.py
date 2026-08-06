"""比对模块导出。

统一导出序列对齐、深度特征比对与聚类能力：
- hamming / sequence_score: pHash 序列对齐打分
- deep_sequence_score: CLIP 深度特征序列比对
- UnionFind / build_groups / expand_groups: 并查集聚类
- LEVEL2_THRESHOLD / SUSPECT_THRESHOLD: L2 判重阈值
- LEVEL3_THRESHOLD: L3 判重阈值
"""

from fabrica.tools.video_dedup.matching.seq_align import (
    LEVEL2_THRESHOLD,
    SUSPECT_THRESHOLD,
    hamming,
    sequence_score,
)
from fabrica.tools.video_dedup.matching.deep_match import (
    DEFAULT_SIM_THRESH,
    LEVEL3_THRESHOLD,
    deep_sequence_score,
)
from fabrica.tools.video_dedup.matching.cluster import (
    UnionFind,
    build_groups,
    expand_groups,
)

__all__ = [
    "hamming",
    "sequence_score",
    "deep_sequence_score",
    "UnionFind",
    "build_groups",
    "expand_groups",
    "DEFAULT_SIM_THRESH",
    "LEVEL2_THRESHOLD",
    "SUSPECT_THRESHOLD",
    "LEVEL3_THRESHOLD",
]