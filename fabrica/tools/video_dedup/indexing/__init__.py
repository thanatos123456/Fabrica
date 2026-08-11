"""索引模块导出。

统一导出 pHash 二进制索引与深度特征浮点索引能力：
- PHashIndex: FAISS 二进制索引，支持最近邻检索与候选对生成
- DeepIndex: FAISS 浮点索引（余弦），用于 L3 深度特征候选生成
"""

from fabrica.tools.video_dedup.indexing.deep_index import DeepIndex
from fabrica.tools.video_dedup.indexing.phash_index import PHashIndex

__all__ = ["DeepIndex", "PHashIndex"]