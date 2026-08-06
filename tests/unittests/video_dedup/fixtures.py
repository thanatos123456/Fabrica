"""video_dedup 模块共享测试工具与辅助函数。

提供真实视频样例生成（PyAV）、图像生成与 SampledFrame 构造，
避免 test_sampler / test_extractors 等测试重复定义。
"""

from typing import List, Tuple

import av
import numpy as np
from PIL import Image

from fabrica.tools.video_dedup.sampler import SampledFrame


# ============================================================================
# 视频 / 图像样例生成
# ============================================================================

def make_video(
    path: str,
    duration: float = 5.0,
    fps: int = 25,
    size: Tuple[int, int] = (320, 240),
) -> str:
    """用 PyAV 生成一个纯色渐变视频文件。

    Args:
        path: 输出视频文件路径。
        duration: 视频时长（秒）。
        fps: 帧率。
        size: 视频尺寸 (width, height)。

    Returns:
        生成的视频文件路径。
    """
    with av.open(path, "w") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height = size
        total = int(duration * fps)
        for i in range(total):
            color = (i * 2) % 255
            frame = np.full(
                (size[1], size[0], 3), color, dtype=np.uint8
            )
            video_frame = av.VideoFrame.from_ndarray(
                frame, format="rgb24"
            )
            for packet in stream.encode(video_frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


def make_image(
    size: Tuple[int, int] = (128, 128),
    color: Tuple[int, int, int] = (120, 80, 40),
) -> Image.Image:
    """生成一张纯色 PIL 图像。

    Args:
        size: 图像尺寸 (width, height)。
        color: RGB 颜色。

    Returns:
        PIL RGB 图像。
    """
    return Image.new("RGB", size, color)


def sampled_frames(n: int) -> List[SampledFrame]:
    """生成 n 个采样帧。

    Args:
        n: 采样帧数量。

    Returns:
        SampledFrame 列表，image 为纯色图像。
    """
    return [
        SampledFrame(idx=i, ts=i * 0.1, image=make_image())
        for i in range(n)
    ]