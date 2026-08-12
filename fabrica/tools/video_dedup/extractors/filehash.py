"""L1 文件哈希提取器（T4.3）。

计算视频文件的 MD5 哈希，用于识别字节级完全相同的视频。
1MB 分块读取，避免大文件一次性载入内存造成 OOM。
"""

import hashlib


# 默认分块大小：8MB（加大读块，减少 read 系统调用次数）
DEFAULT_BLOCK_SIZE = 8 * 1024 * 1024


def file_hash(
    path: str,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> str:
    """计算文件的 MD5 哈希。

    以 block_size（默认 1MB）分块流式读取，避免大文件内存溢出。

    Args:
        path: 文件路径。
        block_size: 分块读取大小（字节），默认 1MB。

    Returns:
        文件 MD5 哈希的十六进制字符串。

    Raises:
        FileNotFoundError: 文件不存在时抛出。
    """
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()