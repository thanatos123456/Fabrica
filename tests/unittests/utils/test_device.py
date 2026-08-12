"""设备检测测试模块。

测试目标：fabrica/utils/device.py
覆盖：is_cuda_available、get_device、get_device_info、get_batch_size_hint
"""

import unittest
from unittest.mock import patch, MagicMock

from fabrica.utils import device
from fabrica.utils.device import (
    is_cuda_available,
    get_device,
    get_device_info,
    get_batch_size_hint,
)


# ============================================================================
# is_cuda_available 测试
# ============================================================================

class TestIsCudaAvailable(unittest.TestCase):
    """is_cuda_available 函数测试集。"""

    def test_returns_bool(self):
        """返回值应为布尔类型。"""
        result = is_cuda_available()
        self.assertIsInstance(result, bool)

    def test_returns_false_when_no_torch(self):
        """_TORCH_AVAILABLE=False 时应返回 False。"""
        with patch.object(device, "_TORCH_AVAILABLE", False):
            result = is_cuda_available()
            self.assertFalse(result)

    def test_returns_true_when_torch_cuda_available(self):
        """torch.cuda.is_available() 返回 True 时应返回 True。"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.object(device, "_TORCH_AVAILABLE", True):
            with patch.object(device, "_torch", mock_torch):
                result = is_cuda_available()
                self.assertTrue(result)


# ============================================================================
# get_device 测试
# ============================================================================

class TestGetDevice(unittest.TestCase):
    """get_device 函数测试集。"""

    def test_prefer_cpu_returns_cpu(self):
        """prefer='cpu' 应始终返回 'cpu'。"""
        result = get_device("cpu")
        self.assertEqual(result, "cpu")

    def test_prefer_auto_returns_cpu_or_cuda(self):
        """prefer='auto' 应返回 'cpu' 或 'cuda'。"""
        result = get_device("auto")
        self.assertIn(result, ("cpu", "cuda"))

    def test_prefer_auto_returns_cpu_when_no_cuda(self):
        """无 CUDA 时 prefer='auto' 应返回 'cpu'。"""
        with patch.object(device, "_TORCH_AVAILABLE", False):
            result = get_device("auto")
            self.assertEqual(result, "cpu")

    def test_prefer_cuda_returns_cpu_when_unavailable(self):
        """CUDA 不可用时 prefer='cuda' 应降级返回 'cpu'。"""
        with patch.object(device, "_TORCH_AVAILABLE", False):
            result = get_device("cuda")
            self.assertEqual(result, "cpu")

    def test_prefer_auto_returns_cuda_when_available(self):
        """CUDA 可用时 prefer='auto' 应返回 'cuda'。"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.object(device, "_TORCH_AVAILABLE", True):
            with patch.object(device, "_torch", mock_torch):
                result = get_device("auto")
                self.assertEqual(result, "cuda")

    def test_invalid_prefer_raises_value_error(self):
        """无效 prefer 值应抛出 ValueError。"""
        with self.assertRaises(ValueError):
            get_device("invalid")


# ============================================================================
# get_device_info 测试
# ============================================================================

class TestGetDeviceInfo(unittest.TestCase):
    """get_device_info 函数测试集。"""

    def test_returns_dict_with_required_fields(self):
        """返回字典应包含 device 和 cuda_available 字段。"""
        info = get_device_info()
        self.assertIsInstance(info, dict)
        self.assertIn("device", info)
        self.assertIn("cuda_available", info)

    def test_cpu_device_info(self):
        """CPU 模式下 device_info 应正确。"""
        with patch.object(device, "_TORCH_AVAILABLE", False):
            info = get_device_info()
            self.assertEqual(info["device"], "cpu")
            self.assertFalse(info["cuda_available"])

    def test_cuda_device_info_has_extra_fields(self):
        """CUDA 模式下应包含额外字段。"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.version.cuda = "12.0"
        mock_torch.cuda.get_device_name.return_value = "RTX 4090"
        mock_torch.cuda.device_count.return_value = 1
        mock_props = MagicMock()
        mock_props.total_memory = 24 * 1024 ** 3
        mock_torch.cuda.get_device_properties.return_value = mock_props
        with patch.object(device, "_TORCH_AVAILABLE", True):
            with patch.object(device, "_torch", mock_torch):
                info = get_device_info()
                self.assertEqual(info["device"], "cuda")
                self.assertTrue(info["cuda_available"])
                self.assertEqual(info["cuda_version"], "12.0")
                self.assertEqual(info["cuda_device_name"], "RTX 4090")
                self.assertEqual(info["cuda_device_count"], 1)


# ============================================================================
# get_batch_size_hint 测试
# ============================================================================

class TestGetBatchSizeHint(unittest.TestCase):
    """get_batch_size_hint 函数测试集。"""

    def test_returns_int(self):
        """返回值应为整数。"""
        result = get_batch_size_hint()
        self.assertIsInstance(result, int)

    def test_cpu_returns_16(self):
        """CPU 模式应返回 16。"""
        with patch.object(device, "_TORCH_AVAILABLE", False):
            result = get_batch_size_hint()
            self.assertEqual(result, 16)

    def test_gpu_returns_64(self):
        """GPU 模式应返回 64。"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.object(device, "_TORCH_AVAILABLE", True):
            with patch.object(device, "_torch", mock_torch):
                result = get_batch_size_hint()
                self.assertEqual(result, 64)


if __name__ == "__main__":
    unittest.main()
