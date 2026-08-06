"""CLIP 深度特征提取器测试（T5.1）。

测试目标：fabrica/tools/video_dedup/extractors/deepfeat.py
覆盖：CLIPExtractor 的懒加载、extract 输出形状/归一化/分批、
依赖缺失降级与设备回落。open_clip 用 mock 隔离，不触发真实模型加载。
"""

import unittest
from unittest import mock

import numpy as np
import torch

from fabrica.tools.video_dedup.extractors.deepfeat import (
    CLIPExtractor,
    FEATURE_DIM,
)
from tests.unittests.video_dedup.fixtures import make_image


# ============================================================================
# mock 辅助
# ============================================================================

class FakeModel:
    """假 CLIP 模型：encode_image 返回真实 torch 张量。

    返回的值略大于 1 的随机向量，便于验证 L2 归一化后 norm ≈ 1。
    """

    def __init__(self, dim=FEATURE_DIM):
        self.dim = dim
        self.call_count = 0
        self.eval_called = False

    def eval(self):
        self.eval_called = True
        return self

    def encode_image(self, batch: torch.Tensor):
        self.call_count += 1
        # 每行长度 ~2.0，归一化后可验证 -> 1.0
        feat = torch.rand(batch.shape[0], self.dim) * 2.0
        return feat


def _fake_preprocess(img):
    """假预处理：返回 [3, 224, 224] 张量。"""
    return torch.rand(3, 224, 224)


def _install_fake_open_clip(module, model=None):
    """在 deepfeat 模块中注入假 open_clip。

    Args:
        module: deepfeat 模块对象。
        model: FakeModel 实例；为 None 时自动创建。
    """
    model = model or FakeModel()
    fake_open_clip = mock.Mock()
    fake_open_clip.create_model_and_transforms.return_value = (
        model, None, _fake_preprocess
    )
    return model, fake_open_clip


# ============================================================================
# 测试
# ============================================================================

class TestCLIPExtractorAvailability(unittest.TestCase):
    """is_available 与依赖缺失降级测试。"""

    def test_is_available_true_when_clip_installed(self):
        """open_clip 可用时 is_available 返回 True。"""
        with mock.patch(
            "fabrica.tools.video_dedup.extractors.deepfeat._CLIP_AVAILABLE",
            True,
        ):
            self.assertTrue(CLIPExtractor.is_available())

    def test_is_available_false_when_clip_missing(self):
        """open_clip 缺失时 is_available 返回 False。"""
        with mock.patch(
            "fabrica.tools.video_dedup.extractors.deepfeat._CLIP_AVAILABLE",
            False,
        ):
            self.assertFalse(CLIPExtractor.is_available())

    def test_extract_raises_when_clip_missing(self):
        """依赖缺失时 extract 应抛 RuntimeError。"""
        with mock.patch(
            "fabrica.tools.video_dedup.extractors.deepfeat._CLIP_AVAILABLE",
            False,
        ):
            ex = CLIPExtractor()
            with self.assertRaises(RuntimeError):
                ex.extract([make_image()])


class TestCLIPExtractorInit(unittest.TestCase):
    """构造函数测试。"""

    def test_device_defaults_to_cpu(self):
        """device 为 None 时应回落 get_device()（本机无 GPU -> cpu）。"""
        ex = CLIPExtractor()
        self.assertEqual(ex.device, "cpu")

    def test_device_explicit(self):
        """显式指定 device 应被保留。"""
        ex = CLIPExtractor(device="cpu")
        self.assertEqual(ex.device, "cpu")

    def test_init_does_not_load_model(self):
        """__init__ 不应触发模型加载。"""
        model, fake = _install_fake_open_clip(
            __import__(
                "fabrica.tools.video_dedup.extractors.deepfeat",
                fromlist=["deepfeat"],
            )
        )
        with mock.patch(
            "fabrica.tools.video_dedup.extractors.deepfeat._CLIP_AVAILABLE",
            True,
        ), mock.patch(
            "fabrica.tools.video_dedup.extractors.deepfeat.open_clip",
            fake,
        ):
            CLIPExtractor()
        fake.create_model_and_transforms.assert_not_called()


class TestCLIPExtractorExtract(unittest.TestCase):
    """extract 核心逻辑测试。"""

    def setUp(self):
        self.module = __import__(
            "fabrica.tools.video_dedup.extractors.deepfeat",
            fromlist=["deepfeat"],
        )
        self.model = FakeModel()
        self.fake_clip = mock.Mock()
        self.fake_clip.create_model_and_transforms.return_value = (
            self.model, None, _fake_preprocess
        )
        self._clip_patch = mock.patch.object(
            self.module, "open_clip", self.fake_clip
        )
        self._avail_patch = mock.patch.object(
            self.module, "_CLIP_AVAILABLE", True
        )
        self._clip_patch.start()
        self._avail_patch.start()

    def tearDown(self):
        self._clip_patch.stop()
        self._avail_patch.stop()

    def _images(self, n):
        return [make_image() for _ in range(n)]

    def test_extract_lazy_loads_model_once(self):
        """首次 extract 才加载模型，且只加载一次（缓存复用）。"""
        ex = CLIPExtractor()
        ex.extract(self._images(3))
        ex.extract(self._images(2))
        self.assertEqual(
            self.fake_clip.create_model_and_transforms.call_count, 1
        )
        self.assertTrue(self.model.eval_called)

    def test_extract_empty_returns_empty(self):
        """空输入应返回 (0, FEATURE_DIM) float32，不触发模型加载。"""
        ex = CLIPExtractor()
        out = ex.extract([])
        self.assertEqual(out.shape, (0, FEATURE_DIM))
        self.assertEqual(out.dtype, np.float32)
        self.fake_clip.create_model_and_transforms.assert_not_called()

    def test_extract_shape_and_dtype(self):
        """返回 shape [n, 512]、dtype float32。"""
        ex = CLIPExtractor(batch_size=2)
        out = ex.extract(self._images(5))
        self.assertEqual(out.shape, (5, FEATURE_DIM))
        self.assertEqual(out.dtype, np.float32)

    def test_extract_output_l2_normalized(self):
        """输出每行 L2 范数应 ≈ 1.0。"""
        ex = CLIPExtractor(batch_size=16)
        out = ex.extract(self._images(6))
        norms = np.linalg.norm(out, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)

    def test_extract_batches_correctly(self):
        """batch_size=2 时 5 张图按 3 批处理，结果仍为 5 行。"""
        ex = CLIPExtractor(batch_size=2)
        out = ex.extract(self._images(5))
        self.assertEqual(out.shape[0], 5)
        self.assertEqual(self.model.call_count, 3)  # ceil(5/2)

    def test_extract_single_batch(self):
        """batch_size 大于输入数量时只处理 1 批。"""
        ex = CLIPExtractor(batch_size=64)
        ex.extract(self._images(3))
        self.assertEqual(self.model.call_count, 1)


if __name__ == "__main__":
    unittest.main()