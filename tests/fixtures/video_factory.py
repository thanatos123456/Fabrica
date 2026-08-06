"""视频夹具工厂（T5.6）。

提供内容可区分的测试视频生成与派生版本生成：
- create_test_video: 生成"4×4 二值块图案 + 移动强调点"视频，
  块图案由 content 派生，使不同 content 产生不同 pHash（可区分不同视频）。
- create_derived_video: 对源视频施加水印/裁剪/缩放/转码等变换，保留内容，
  使衍生版本与源版本 pHash 相似（可判重）。

供集成测试与端到端测试使用。
"""

import zlib
from typing import Tuple

import av
import numpy as np
from PIL import Image, ImageDraw


# ============================================================================
# 单帧生成
# ============================================================================

def _solid_pattern(
    size: Tuple[int, int],
    seed: int,
    i: int,
    total: int,
) -> np.ndarray:
    """构造一帧"垂直渐变 + 移动对比色块"图像。

    无几何结构，用于"真不同"内容：与几何图案在 CLIP/pHash 特征上
    差异明显，避免与重复组视频冲突（误判）。

    Args:
        size: (width, height)。
        seed: 内容种子，决定渐变色。
        i: 当前帧下标。
        total: 总帧数。

    Returns:
        RGB 帧数组，shape (H, W, 3) uint8。
    """
    W, H = size[0], size[1]
    rng = np.random.default_rng(seed)
    c0 = rng.integers(30, 225, 3).astype(np.float32)
    c1 = rng.integers(30, 225, 3).astype(np.float32)
    # 垂直渐变（顶部 c0 → 底部 c1）
    t = np.linspace(0.0, 1.0, H)[:, None, None]
    grad = (c0[None, None, :] * (1 - t) + c1[None, None, :] * t)
    frame = np.clip(grad, 0, 255).astype(np.uint8)
    frame = np.repeat(frame, W, axis=1)
    # 移动对比色块，增强时序变化
    block = (255 - c0.astype(np.float32)).astype(np.uint8)
    bw, bh = max(12, W // 5), max(12, H // 5)
    denom = max(1, total)
    bx = int((W - bw) * (0.5 + 0.3 * np.sin(2 * np.pi * i / denom)))
    by = int((H - bh) * (0.5 + 0.3 * np.cos(2 * np.pi * i / denom)))
    bx = max(0, min(bx, W - bw))
    by = max(0, min(by, H - bh))
    frame[by:by + bh, bx:bx + bw] = block
    return frame


def _noise_pattern(
    size: Tuple[int, int],
    seed: int,
    i: int,
    total: int,
) -> np.ndarray:
    """构造一帧"随机噪声"图像。

    不同帧、不同 content 的噪声互不相同，pHash 指纹高度随机，
    与几何图案（pattern）及彼此都不相似，用于标注为"真不同"内容，
    避免与重复组视频冲突（误判）。

    Args:
        size: (width, height)。
        seed: 内容种子。
        i: 当前帧下标。
        total: 总帧数。

    Returns:
        RGB 帧数组，shape (H, W, 3) uint8。
    """
    W, H = size[0], size[1]
    rng = np.random.default_rng(seed * max(1, total) + i)
    return rng.integers(0, 256, (H, W, 3), dtype=np.uint8)


def _make_pattern(
    size: Tuple[int, int],
    seed: int,
    i: int,
    total: int,
    style: str = "pattern",
) -> np.ndarray:
    """构造一帧"8×8 二值块图案"图像。

    style='pattern'（默认）时生成"8×8 黑白块 + 移动强调点"图案：
    - 64 个单元格各自为纯黑(0)或纯白(255)，由 seed 的 64 位决定。
    - 8×8 网格直接对应 pHash 的 8×8 DCT 系数块，每个单元格影响
      一个 DCT 基函数，不同模式几乎不可能产生相同 pHash。
    - 派生版本（resize/watermark/crop/transcode）保留块结构，
      pHash 与 CLIP 深度特征均相似（可判重）。
    - 移动强调点（灰色圆点，值为 128）增强时序变化，供 pHash 序列对齐。

    设计说明：
    - pHash 基于灰度 DCT，忽略颜色；因此用纯黑白结构而非彩色形状。
    - 4×4 块在 pHash 8×8 DCT 空间映射不充分，仍会发生碰撞；
      8×8 块与 DCT 系数一一对应，消除碰撞。

    style='noise' 时生成随机噪声（见 _noise_pattern），仅供部分测试使用。

    Args:
        size: (width, height)。
        seed: 内容种子，决定 64 个单元格的黑白状态。
        i: 当前帧下标。
        total: 总帧数。
        style: 内容样式，'pattern'（默认）或 'noise'。

    Returns:
        RGB 帧数组，shape (H, W, 3) uint8。
    """
    if style == "noise":
        return _noise_pattern(size, seed, i, total)
    W, H = size[0], size[1]
    rng = np.random.default_rng(seed)
    cols, rows = 8, 8
    cell_w = W // cols
    cell_h = H // rows
    # 全黑底
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    for c in range(cols):
        for r in range(rows):
            if rng.random() < 0.5:
                y0 = r * cell_h
                y1 = (r + 1) * cell_h if r < rows - 1 else H
                x0 = c * cell_w
                x1 = (c + 1) * cell_w if c < cols - 1 else W
                frame[y0:y1, x0:x1] = 255  # 白色块
    # 移动强调点（灰色圆点，值为 128），增强时序变化
    ar = max(4, int(min(W, H) * 0.03))
    denom = max(1, total)
    ax = int(W * (0.5 + 0.3 * np.sin(2 * np.pi * i / denom)))
    ay = int(H * (0.5 + 0.3 * np.cos(2 * np.pi * i / denom)))
    ax = max(ar, min(ax, W - ar))
    ay = max(ar, min(ay, H - ar))
    img = Image.fromarray(frame)
    d = ImageDraw.Draw(img)
    d.ellipse([ax - ar, ay - ar, ax + ar, ay + ar], fill=(128, 128, 128))
    return np.asarray(img)


# ============================================================================
# 生成测试视频
# ============================================================================

def create_test_video(
    path: str,
    duration: float = 3.0,
    fps: int = 25,
    resolution: Tuple[int, int] = (320, 240),
    content: str = "video",
    style: str = "pattern",
) -> str:
    """生成内容确定的测试视频。

    Args:
        path: 输出视频路径。
        duration: 时长（秒）。
        fps: 帧率。
        resolution: (width, height)。
        content: 内容标识，不同值产生不同画面。
        style: 内容样式，'pattern'（4×4 二值块图案，默认）或
            'noise'（随机噪声，仅供特殊测试使用）。

    Returns:
        生成的视频文件路径。
    """
    seed = zlib.crc32(content.encode("utf-8")) & 0xFFFFFFFF
    total = int(duration * fps)
    with av.open(path, "w") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height = resolution
        for i in range(total):
            frame = _make_pattern(resolution, seed, i, total, style=style)
            video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
            for packet in stream.encode(video_frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


def create_derived_video(
    src: str,
    dst: str,
    watermark: bool = False,
    crop: bool = False,
    resize: bool = False,
    transcode: bool = False,
    wm_size: int = 30,
    wm_alpha: float = 0.3,
    wm_val: int = 200,
    crop_frac: float = 0.96,
) -> str:
    """从源视频生成派生版本（保留内容）。

    Args:
        src: 源视频路径。
        dst: 输出视频路径。
        watermark: 在角落叠加半透明水印块。
        crop: 中心温和裁切 crop_frac 比例（裁掉边缘字幕/黑边）。
        resize: 缩放至 80%。
        transcode: 改用 libx264 编码。
        wm_size: 水印块边长（像素）。
        wm_alpha: 水印不透明度（0~1，1 为完全不透明）。
        wm_val: 水印颜色值（0~255，RGB 三通道同值）。
        crop_frac: 裁切后相对原图的比例。

    Returns:
        生成的派生视频路径。
    """
    in_container = av.open(src)
    stream = in_container.streams.video[0]
    in_frames = [
        f.to_ndarray(format="rgb24") for f in in_container.decode(stream)
    ]
    in_container.close()

    out_frames = []
    for arr in in_frames:
        if crop:
            h, w = arr.shape[:2]
            ch, cw = max(1, int(h * crop_frac)), max(1, int(w * crop_frac))
            y0, x0 = (h - ch) // 2, (w - cw) // 2
            arr = arr[y0:y0 + ch, x0:x0 + cw]
        if resize:
            pil = Image.fromarray(arr)
            w2, h2 = int(pil.size[0] * 0.8), int(pil.size[1] * 0.8)
            arr = np.asarray(pil.resize((w2, h2)))
        if watermark:
            arr = arr.copy()
            h, w = arr.shape[:2]
            blk = arr[max(0, h - wm_size):h, max(0, w - wm_size):w]
            # 半透明叠加：按 wm_alpha 混合，保留部分原内容
            arr[max(0, h - wm_size):h, max(0, w - wm_size):w] = (
                blk * (1 - wm_alpha) + np.array([wm_val] * 3) * wm_alpha
            ).astype(np.uint8)
        out_frames.append(arr)

    out_container = av.open(dst, "w")
    codec = "libx264" if transcode else "mpeg4"
    ostream = out_container.add_stream(codec, rate=25)
    ostream.width, ostream.height = out_frames[0].shape[1], out_frames[0].shape[0]
    for arr in out_frames:
        video_frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
        for packet in ostream.encode(video_frame):
            out_container.mux(packet)
    for packet in ostream.encode(None):
        out_container.mux(packet)
    out_container.close()
    return dst