"""提取器模块导出。

统一导出 L1/L2/L3 提取能力，供上层调用：
- file_hash: L1 文件 MD5 哈希
- frame_phash / video_phash_sequence: L2 pHash 感知哈希
- CLIPExtractor: L3 CLIP 深度特征提取器
"""

from fabrica.tools.video_dedup.extractors.filehash import file_hash
from fabrica.tools.video_dedup.extractors.phash import (
    frame_phash,
    video_phash_sequence,
)
from fabrica.tools.video_dedup.extractors.deepfeat import CLIPExtractor

__all__ = [
    "file_hash",
    "frame_phash",
    "video_phash_sequence",
    "CLIPExtractor",
]