#!/usr/bin/env python3
"""Fabrica 路径工具与通用辅助函数模块。

提供平台无关的路径操作、文件大小格式化、时间格式化、
文件哈希计算和可迭代对象分块等通用能力。

用法：
    from fabrica.utils.helpers import (
        PathUtils, format_size, format_duration,
        compute_file_hash, chunked,
    )

    PathUtils.ensure_dir("/tmp/fabrica")
    print(format_size(1073741824))  # "1.0 GB"
    print(format_duration(3661))    # "1h 1m 1s"
"""

import hashlib
import os
import re
import time
import uuid
from datetime import datetime
from itertools import islice
from typing import Any, Iterator, Optional, Union


# ============================================================================
# 路径工具类
# ============================================================================

class PathUtils:
    """路径操作工具集。

    提供临时目录创建、数据目录获取、目录确保和文件名清理等
    静态方法。所有方法均为无状态操作。
    """

    @staticmethod
    def ensure_dir(path: str) -> str:
        """确保目录存在，不存在则创建。

        Args:
            path: 目录路径。

        Returns:
            传入的目录路径（便于链式调用）。
        """
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def get_temp_dir(
        base_dir: str,
        prefix: str = "fabrica",
    ) -> str:
        """在 base_dir 下创建唯一的临时目录。

        目录名格式为 {prefix}_{timestamp}_{random}，确保并发安全。

        Args:
            base_dir: 临时目录的父目录。
            prefix: 目录名前缀，用于标识用途。

        Returns:
            新创建的临时目录绝对路径。
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        random_suffix = uuid.uuid4().hex[:8]
        dir_name = f"{prefix}_{timestamp}_{random_suffix}"
        temp_path = os.path.join(base_dir, dir_name)
        os.makedirs(temp_path, exist_ok=True)
        return temp_path

    @staticmethod
    def get_data_dir(base_dir: str, tool_name: str) -> str:
        """获取工具持久化数据目录。

        路径格式为 base_dir/tool_name，目录不存在时自动创建。

        Args:
            base_dir: 数据根目录。
            tool_name: 工具名称。

        Returns:
            工具数据目录绝对路径。
        """
        data_path = os.path.join(base_dir, tool_name)
        os.makedirs(data_path, exist_ok=True)
        return data_path

    @staticmethod
    def safe_filename(filename: str) -> str:
        """清理文件名中的非法字符。

        替换 Windows/Unix 文件名非法字符（\\ / : * ? " < > |）
        为下划线，并去除首尾空格和点。

        Args:
            filename: 原始文件名。

        Returns:
            清理后的安全文件名。
        """
        # 替换非法字符为下划线
        safe = re.sub(r'[\\/:*?"<>|]', '_', filename)
        # 去除首尾空格和点
        safe = safe.strip(' .')
        return safe


# ============================================================================
# 格式化函数
# ============================================================================

def format_size(
    size: Union[int, float],
    decimal_places: int = 1,
) -> str:
    """格式化文件大小为可读字符串。

    Args:
        size: 文件大小（字节数）。
        decimal_places: 保留的小数位数，默认 1。

    Returns:
        格式化后的大小字符串，如 "1.0 GB"。
    """
    # 文件大小单位列表
    units = ["B", "KB", "MB", "GB", "TB"]
    current = float(size)
    for unit in units:
        if current < 1024.0:
            return f"{current:.{decimal_places}f} {unit}"
        current /= 1024.0
    # 超过 TB 则以 PB 为单位
    return f"{current:.{decimal_places}f} PB"


def format_duration(seconds: Union[int, float]) -> str:
    """格式化持续时间为可读字符串。

    格式为 "Xh Ym Zs"，不足的单位省略。
    0 秒返回 "0s"。

    Args:
        seconds: 秒数。

    Returns:
        格式化后的时间字符串，如 "1h 1m 1s"。
    """
    if seconds <= 0:
        return "0s"
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0:
        parts.append(f"{secs}s")
    return " ".join(parts)


def format_timestamp(dt: Optional[datetime]) -> str:
    """格式化时间戳为字符串。

    Args:
        dt: datetime 对象。为 None 时返回空字符串。

    Returns:
        格式化后的时间字符串，格式为 "%Y-%m-%d %H:%M:%S"。
    """
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================================
# 文件哈希计算
# ============================================================================

def compute_file_hash(
    path: str,
    algo: str = "md5",
) -> str:
    """计算文件内容的哈希值。

    分块读取文件（1MB 每块），避免大文件内存溢出。

    Args:
        path: 文件路径。
        algo: 哈希算法名称，支持 "md5" / "sha1" / "sha256" / "sha512"。

    Returns:
        文件哈希的十六进制字符串。

    Raises:
        FileNotFoundError: 文件不存在时抛出。
    """
    # 1MB 分块读取，避免大文件 OOM
    block_size = 1024 * 1024
    hasher = hashlib.new(algo)
    with open(path, "rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


# ============================================================================
# 可迭代对象分块
# ============================================================================

def chunked(iterable: Any, size: int) -> Iterator:
    """将可迭代对象按指定大小分块。

    惰性生成器实现，支持任意可迭代对象（列表、生成器等），
    避免一次性加载到内存。

    Args:
        iterable: 可迭代对象。
        size: 每块的大小，必须为正整数。

    Yields:
        长度不超过 size 的列表块。
    """
    if size <= 0:
        raise ValueError(f"块大小必须为正整数，实际: {size}")
    iterator = iter(iterable)
    while True:
        chunk = list(islice(iterator, size))
        if not chunk:
            break
        yield chunk
