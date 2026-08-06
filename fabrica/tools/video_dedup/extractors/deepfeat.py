"""L3 CLIP 深度特征提取器（T5.1）。

对视频帧提取深度语义特征，用于最终裁决（L3）。
使用 OpenCLIP 加载 CLIP 模型，输出 [n, 512] 的 L2 归一化特征向量，
L2 归一化后余弦相似度等价于内积，可直接用 FAISS 内积索引加速。

open_clip / torch 为可选依赖：未安装时 import 本模块不抛异常，
仅 `extract()` 调用时抛出 RuntimeError，供上层 pipeline 捕获后降级跳过。

用法：
    from fabrica.tools.video_dedup.extractors import CLIPExtractor

    extractor = CLIPExtractor(batch_size=16)
    feats = extractor.extract([pil_img1, pil_img2])  # [n, 512] float32
"""

from typing import List, Optional

import numpy as np

from fabrica.utils.device import get_device

# 可选依赖：open_clip / torch 仅在需要深度特征时才导入
# 未安装时降级到不可用状态，不抛异常；对应名称绑定为 None 便于测试 patch
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    torch = None
    _TORCH_AVAILABLE = False

try:
    import open_clip
    _CLIP_AVAILABLE = _TORCH_AVAILABLE
except ImportError:
    open_clip = None
    _CLIP_AVAILABLE = False


# ============================================================================
# 常量
# ============================================================================

DEFAULT_MODEL_NAME = "ViT-B-32"                 # CLIP 模型名称
DEFAULT_PRETRAINED = "laion2b_s34b_b79k"        # 预训练权重
DEFAULT_BATCH_SIZE = 64                         # 默认推理 batch 大小
FEATURE_DIM = 512                               # CLIP ViT-B-32 特征维度


# ============================================================================
# CLIPExtractor
# ============================================================================

class CLIPExtractor:
    """CLIP 深度特征提取器。

    懒加载模型：__init__ 只记录配置，首次 extract() 时才加载
    OpenCLIP 模型（首次会下载权重 ~350MB，缓存到 ~/.cache/clip/）。

    Attributes:
        model_name: OpenCLIP 模型名称。
        pretrained: 预训练权重标识。
        device: 计算设备（"cpu" / "cuda"）。
        batch_size: 推理 batch 大小。
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        pretrained: str = DEFAULT_PRETRAINED,
        device: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        """初始化提取器配置。

        Args:
            model_name: OpenCLIP 模型名称，默认 ViT-B-32。
            pretrained: 预训练权重标识，默认 laion2b_s34b_b79k。
            device: 计算设备；为 None 时用 get_device() 自动检测。
            batch_size: 推理 batch 大小。
        """
        self.model_name = model_name
        self.pretrained = pretrained
        # 统一经 get_device() 解析：'auto' 会被解析为实际设备（cuda/cpu），
        # 避免 'auto' 原样传入 torch.device 导致构造失败。
        self.device = get_device(device or "auto")
        self.batch_size = batch_size
        self._model = None
        self._preprocess = None

    @classmethod
    def is_available(cls) -> bool:
        """OpenCLIP 是否可用。

        Returns:
            open_clip / torch 均已安装时返回 True，否则 False。
        """
        return _CLIP_AVAILABLE

    def _ensure_model(self):
        """懒加载 OpenCLIP 模型（幂等，缓存复用）。

        Raises:
            RuntimeError: open_clip / torch 未安装时抛出。
        """
        if self._model is not None:
            return
        if not _CLIP_AVAILABLE:
            raise RuntimeError(
                "OpenCLIP 未安装，无法进行 L3 深度特征提取"
            )
        model, _, preprocess = open_clip.create_model_and_transforms(
            self.model_name,
            pretrained=self.pretrained,
            device=self.device,
        )
        model.eval()
        self._model = model
        self._preprocess = preprocess

    def extract(self, pil_images: List) -> np.ndarray:
        """批量提取帧的深度特征。

        Args:
            pil_images: PIL 图像列表。

        Returns:
            np.ndarray，shape [n, FEATURE_DIM]，dtype float32，
            每行已 L2 归一化。空输入返回 shape (0, FEATURE_DIM)。

        Raises:
            RuntimeError: open_clip / torch 未安装时抛出。
        """
        if not pil_images:
            return np.zeros((0, FEATURE_DIM), dtype=np.float32)

        self._ensure_model()

        tensors = torch.stack(
            [self._preprocess(im) for im in pil_images]
        )
        feats: List[np.ndarray] = []
        with torch.no_grad():
            for i in range(0, len(tensors), self.batch_size):
                batch = tensors[i:i + self.batch_size].to(self.device)
                f = self._model.encode_image(batch)
                # L2 归一化，clamp_min 防除零
                f = f / f.norm(dim=-1, keepdim=True).clamp_min(1e-8)
                feats.append(f.cpu().numpy())
        return np.concatenate(feats, axis=0).astype(np.float32)