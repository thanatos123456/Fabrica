"""L2 pHash 感知哈希提取器（T4.4）。

对视频每一帧计算感知哈希（DCT pHash），生成 64bit 指纹序列，
供 FAISS 二进制索引（T4.5）与序列对齐打分（T4.6）使用。

用法：
    from fabrica.tools.video_dedup.extractors import (
        frame_phash, video_phash_sequence,
    )

    h = frame_phash(pil_image)          # np.uint64
    seq = video_phash_sequence(frames)  # np.ndarray [n] uint64
"""

from typing import List

import imagehash
import numpy as np

from fabrica.tools.video_dedup.sampler import SampledFrame


DEFAULT_HASH_SIZE = 8  # pHash 边长，8x8 = 64 bit 指纹


def frame_phash(
    pil_img: "Image.Image",
    hash_size: int = DEFAULT_HASH_SIZE,
) -> np.uint64:
    """计算单帧图像的 pHash，返回 64bit 整数。

    使用 imagehash.phash 计算 DCT 感知哈希，转为 np.uint64
    以适配 FAISS 二进制索引。

    Args:
        pil_img: PIL 图像。
        hash_size: pHash 边长，默认 8（生成 64bit 指纹）。

    Returns:
        np.uint64 类型的感知哈希值。
    """
    hash_obj = imagehash.phash(pil_img, hash_size=hash_size)
    # 新版 imagehash 的 ImageHash 不再支持 int() 转换，
    # 手动将 8x8 的 bool 位数组打包为一个 uint64 整数。
    bits = hash_obj.hash.flatten().astype(np.uint8)
    return np.uint64(np.packbits(bits).view(np.uint64)[0])


def video_phash_sequence(
    sampled_frames: List[SampledFrame],
    hash_size: int = DEFAULT_HASH_SIZE,
) -> np.ndarray:
    """计算视频所有采样帧的 pHash 序列。

    Args:
        sampled_frames: SampledFrame 列表（来自 sampler.sample_frames）。
        hash_size: pHash 边长，默认 8。

    Returns:
        np.ndarray，shape [n_frames]，dtype np.uint64。
    """
    return np.array(
        [frame_phash(f.image, hash_size) for f in sampled_frames],
        dtype=np.uint64,
    )