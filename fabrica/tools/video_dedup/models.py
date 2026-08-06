"""视频验重工具数据模型。

定义视频元信息、判重结果与重复分组的核心数据结构，
供 T4.1 工具类及后续 T4.2-T4.7 各模块共用。
"""

from dataclasses import dataclass, field
from typing import List


# ============================================================================
# VideoInfo 视频元信息
# ============================================================================

@dataclass
class VideoInfo:
    """单个视频的元信息。

    Attributes:
        id: 视频唯一标识。
        path: 视频文件路径。
        size: 文件大小（字节）。
        duration: 视频时长（秒）。
        width: 视频宽度（像素）。
        height: 视频高度（像素）。
        file_hash: 文件 MD5 哈希（L1），未计算时为空字符串。
        frame_count: 抽样帧数量（L2），未抽取时为 0。
    """

    id: str
    path: str
    size: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    file_hash: str = ""
    frame_count: int = 0


# ============================================================================
# MatchResult 判重结果
# ============================================================================

@dataclass
class MatchResult:
    """两个视频之间的判重结果。

    Attributes:
        video_a_id: 视频 A 的标识。
        video_b_id: 视频 B 的标识。
        level: 判重层级（1=文件哈希，2=pHash 序列，3=深度特征）。
        score: 相似度得分（0~1）。
    """

    video_a_id: str
    video_b_id: str
    level: int = 0
    score: float = 0.0


# ============================================================================
# DuplicateGroup 重复分组
# ============================================================================

@dataclass
class DuplicateGroup:
    """一组判定为重复的视频集合。

    Attributes:
        video_ids: 组内去重后的视频标识列表。
        level: 判重层级（1/2/3）。
        scores: 与代表性视频的相似度得分列表，顺序对应 video_ids。
    """

    video_ids: List[str] = field(default_factory=list)
    level: int = 0
    scores: List[float] = field(default_factory=list)