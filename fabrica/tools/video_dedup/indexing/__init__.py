"""索引模块导出。

统一导出 pHash 二进制索引能力：
- PHashIndex: FAISS 二进制索引，支持最近邻检索与候选对生成
"""

from fabrica.tools.video_dedup.indexing.phash_index import PHashIndex

__all__ = ["PHashIndex"]