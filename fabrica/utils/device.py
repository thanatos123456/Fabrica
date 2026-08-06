#!/usr/bin/env python3
"""Fabrica 设备检测模块。

提供自动检测可用计算设备（CPU/GPU）的能力。
PyTorch 为可选依赖，未安装时所有 GPU 检测返回 False，
get_device("auto") 回退到 "cpu"，不会抛出异常。

用法：
    from fabrica.utils.device import get_device, get_device_info

    device = get_device("auto")  # "cuda" 或 "cpu"
    info = get_device_info()      # 设备详情字典
"""

from typing import Any, Dict

# 模块级检测 PyTorch 可用性
# PyTorch 是可选依赖（仅在视频验重 L3 深度特征提取时需要），
# 未安装时降级到 CPU 模式，不抛异常
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


# ============================================================================
# 核心检测函数
# ============================================================================

def is_cuda_available() -> bool:
    """检测 CUDA 是否可用。

    Returns:
        CUDA 可用时返回 True，否则返回 False。
    """
    if not _TORCH_AVAILABLE:
        return False
    return torch.cuda.is_available()


def get_device(prefer: str = "auto") -> str:
    """获取当前计算设备名称。

    Args:
        prefer: 设备偏好，可选值：
            - "auto": 自动检测，CUDA 可用时返回 "cuda"，否则 "cpu"
            - "cpu": 强制使用 CPU
            - "cuda": 请求 CUDA，不可用时降级到 "cpu"

    Returns:
        设备名称字符串："cuda" 或 "cpu"。

    Raises:
        ValueError: prefer 不是 "auto"/"cpu"/"cuda" 时抛出。
    """
    if prefer == "cpu":
        return "cpu"
    if prefer == "cuda":
        if is_cuda_available():
            return "cuda"
        return "cpu"
    if prefer == "auto":
        if is_cuda_available():
            return "cuda"
        return "cpu"
    raise ValueError(
        f"不支持的设备偏好: {prefer!r}，"
        f"可选值: 'auto' / 'cpu' / 'cuda'"
    )


def get_device_info() -> Dict[str, Any]:
    """获取当前设备详细信息。

    始终返回 device 和 cuda_available 字段；
    当设备为 cuda 时，附加 CUDA 版本、设备名、设备数和显存信息。

    Returns:
        设备信息字典，包含以下字段：
            - device: 当前设备名称
            - cuda_available: CUDA 是否可用
            - cuda_version: CUDA 版本（仅 GPU 时存在）
            - cuda_device_name: GPU 设备名（仅 GPU 时存在）
            - cuda_device_count: GPU 设备数（仅 GPU 时存在）
            - cuda_total_memory_gb: GPU 总显存 GB（仅 GPU 时存在）
    """
    device = get_device("auto")
    info: Dict[str, Any] = {
        "device": device,
        "cuda_available": is_cuda_available(),
    }
    if device == "cuda":
        try:
            info["cuda_version"] = torch.version.cuda
            info["cuda_device_name"] = torch.cuda.get_device_name(0)
            info["cuda_device_count"] = torch.cuda.device_count()
            props = torch.cuda.get_device_properties(0)
            info["cuda_total_memory_gb"] = round(
                props.total_memory / (1024 ** 3), 2
            )
        except Exception:
            pass
    return info


def get_batch_size_hint() -> int:
    """根据当前设备返回建议的 batch_size。

    GPU 返回 64，CPU 返回 16。

    Returns:
        建议的 batch_size 整数。
    """
    device = get_device("auto")
    if device == "cuda":
        return 64
    return 16
