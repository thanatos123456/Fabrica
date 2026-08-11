"""视频抽帧模块（T4.2）。

使用 PyAV 对视频文件进行自适应采样，提取关键帧图像：
- 短视频（< 16s）密集抽帧，抽取 min_frames 帧
- 长视频按 target_fps 均匀采样，不超过 max_frames 帧
- 统一 resize 到 224x224
- 采样时间点均匀分布，避开首尾 0.5 秒

用法：
    from fabrica.tools.video_dedup.sampler import sample_frames

    frames, duration = sample_frames("/path/to/video.mp4")
    for f in frames:
        print(f.idx, f.ts, f.image.size)
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image
import av


# ============================================================================
# 常量
# ============================================================================

MIN_FRAMES = 16             # 最少采样帧数
MAX_FRAMES = 1000           # 最多采样帧数（保护上限，配合帧间隔动态采样）
TARGET_FPS = 1.0            # 长视频目标采样帧率（帧/秒，未指定 frame_interval 时）
FRAME_INTERVAL = 5.0        # 长视频采样帧间隔（秒/帧，与时长挂钩）
EDGE_MARGIN = 0.5           # 避开首尾的时间（秒）
SHORT_VIDEO_SECONDS = 16    # 短视频判定阈值（秒）
DEFAULT_RESIZE = (224, 224)  # resize 目标尺寸（宽, 高）


# ============================================================================
# SampledFrame 数据类
# ============================================================================

@dataclass
class SampledFrame:
    """单帧采样结果。

    Attributes:
        idx: 帧序号（从 0 开始）。
        ts: 采样时间戳（秒）。
        image: 采样帧图像（已 resize 为 RGB）。
    """

    idx: int
    ts: float
    image: Image.Image


# ============================================================================
# 采样时间点计算（纯函数）
# ============================================================================

def compute_sample_timestamps(
    duration: float,
    min_frames: int = MIN_FRAMES,
    max_frames: int = MAX_FRAMES,
    target_fps: float = TARGET_FPS,
    frame_interval: Optional[float] = None,
) -> List[float]:
    """计算视频采样时间点（秒）。

    时间点均匀分布在 [0.5, duration-0.5] 区间内，避开首尾。
    短视频（< 16s）采样 min_frames 帧；长视频按帧间隔采样：
    指定 frame_interval 时每 N 秒采一帧（与时长挂钩，长视频自动
    增加帧数），否则按 target_fps 采样，结果夹在
    [min_frames, max_frames] 之间。

    Args:
        duration: 视频时长（秒）。
        min_frames: 最少采样帧数。
        max_frames: 最多采样帧数。
        target_fps: 长视频目标采样帧率（未指定 frame_interval 时）。
        frame_interval: 长视频采样帧间隔（秒/帧），None 时回退 target_fps。

    Returns:
        float 秒组成的采样时间点列表。时长过短无法避开首尾时返回空列表。
    """
    if duration is None or duration <= 2 * EDGE_MARGIN:
        return []

    # 有效区间避开首尾 0.5s
    start = EDGE_MARGIN
    end = duration - EDGE_MARGIN
    span = end - start

    # 计算目标帧数
    if duration < SHORT_VIDEO_SECONDS:
        n = min_frames
    elif frame_interval and frame_interval > 0:
        # 帧间隔采样：与时长挂钩，长视频自动增加采样帧数
        n = int(duration / frame_interval)
    else:
        n = int(target_fps * duration)
    n = max(min_frames, min(n, max_frames))

    # 均匀分布（居中采样，避免撞端点）
    return [
        start + (i + 0.5) / n * span
        for i in range(n)
    ]


# ============================================================================
# 核心抽帧函数
# ============================================================================

def _decode_frame(
    container: av.container.InputContainer,
    stream,
    target_ts: float,
    resize: Tuple[int, int],
) -> Optional[av.VideoFrame]:
    """在指定时间点精确 seek 并解码一帧。

    Args:
        container: 已打开的 PyAV 输入容器。
        stream: 视频流。
        target_ts: 目标时间点（秒）。
        resize: 目标尺寸 (宽, 高)。

    Returns:
        解码并 resize 后的 PIL 图像；无法解码时返回 None。
    """
    # 将秒换算为流时间基
    target = int(round(target_ts / float(stream.time_base)))
    container.seek(
        target,
        stream=stream,
        backward=True,
        any_frame=False,
    )
    for frame in container.decode(stream):
        image = frame.to_image().convert("RGB")
        image = image.resize(resize, Image.BILINEAR)
        return image
    return None


def _resolve_duration(
    container: av.container.InputContainer,
    stream,
) -> float:
    """解析视频时长（秒）。

    优先使用流时长，其次容器时长，最后用平均帧率估算。

    Args:
        container: 已打开的 PyAV 输入容器。
        stream: 视频流。

    Returns:
        视频时长（秒），无法解析时返回 0.0。
    """
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return float(container.duration) / 1_000_000.0
    if stream.average_rate is not None and stream.frames > 0:
        return float(stream.frames) / float(stream.average_rate)
    return 0.0


def sample_frames(
    path: str,
    resize: Tuple[int, int] = DEFAULT_RESIZE,
    min_frames: int = MIN_FRAMES,
    max_frames: int = MAX_FRAMES,
    target_fps: float = TARGET_FPS,
    frame_interval: Optional[float] = None,
) -> Tuple[List[SampledFrame], float]:
    """从视频文件采样关键帧。

    使用 PyAV 精确 seek，只解码需要的帧。短视频密集采样，
    长视频按帧间隔（frame_interval，每 N 秒一帧）或 target_fps
    稀疏采样，统一 resize 到目标尺寸。

    Args:
        path: 视频文件路径。
        resize: 目标尺寸 (宽, 高)，默认 (224, 224)。
        min_frames: 最少采样帧数。
        max_frames: 最多采样帧数。
        target_fps: 长视频目标采样帧率（未指定 frame_interval 时）。
        frame_interval: 长视频采样帧间隔（秒/帧），None 时回退 target_fps。

    Returns:
        (frames, duration) 元组。frames 为 SampledFrame 列表；
        duration 为解析出的视频时长（秒）。损坏文件返回 ([], duration)
        或 ([], 0)，不抛出异常。
    """
    try:
        import av
        with av.open(path) as container:
            if not container.streams.video:
                return [], 0.0
            stream = container.streams.video[0]
            duration = _resolve_duration(container, stream)
            if duration <= 0.0:
                return [], 0.0

            timestamps = compute_sample_timestamps(
                duration,
                min_frames=min_frames,
                max_frames=max_frames,
                target_fps=target_fps,
                frame_interval=frame_interval,
            )

            frames: List[SampledFrame] = []
            for i, ts in enumerate(timestamps):
                image = _decode_frame(container, stream, ts, resize)
                if image is not None:
                    frames.append(SampledFrame(idx=i, ts=round(ts, 3), image=image))
            return frames, round(duration, 3)
    except Exception:
        # 损坏或无法解析的视频：返回空列表，不抛出异常
        return [], 0.0