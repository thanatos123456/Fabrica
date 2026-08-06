"""工具函数测试模块。

测试目标：fabrica/utils/helpers.py
覆盖：PathUtils、format_size、format_duration、format_timestamp、
      compute_file_hash、chunked
"""

import hashlib
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from itertools import islice

from fabrica.utils.helpers import (
    PathUtils,
    format_size,
    format_duration,
    format_timestamp,
    compute_file_hash,
    chunked,
)


# ============================================================================
# PathUtils.ensure_dir 测试
# ============================================================================

class TestPathUtilsEnsureDir(unittest.TestCase):
    """PathUtils.ensure_dir 测试集。"""

    def setUp(self):
        """创建临时目录作为测试根目录。"""
        self.test_root = tempfile.mkdtemp()

    def tearDown(self):
        """清理临时目录。"""
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root)

    def test_create_new_dir(self):
        """应创建新目录。"""
        path = os.path.join(self.test_root, "new_dir")
        result = PathUtils.ensure_dir(path)
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(result, path)

    def test_existing_dir_no_error(self):
        """目录已存在时不应报错。"""
        path = os.path.join(self.test_root, "existing")
        os.makedirs(path)
        result = PathUtils.ensure_dir(path)
        self.assertTrue(os.path.isdir(path))

    def test_returns_path(self):
        """应返回传入的路径。"""
        path = os.path.join(self.test_root, "return_test")
        result = PathUtils.ensure_dir(path)
        self.assertEqual(result, path)


# ============================================================================
# PathUtils.get_temp_dir 测试
# ============================================================================

class TestPathUtilsGetTempDir(unittest.TestCase):
    """PathUtils.get_temp_dir 测试集。"""

    def setUp(self):
        self.test_root = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root)

    def test_creates_unique_dir(self):
        """应创建唯一临时目录。"""
        dir1 = PathUtils.get_temp_dir(self.test_root, "test")
        dir2 = PathUtils.get_temp_dir(self.test_root, "test")
        self.assertTrue(os.path.isdir(dir1))
        self.assertTrue(os.path.isdir(dir2))
        self.assertNotEqual(dir1, dir2)

    def test_dir_name_contains_prefix(self):
        """目录名应包含前缀。"""
        temp_dir = PathUtils.get_temp_dir(self.test_root, "mytool")
        dir_name = os.path.basename(temp_dir)
        self.assertIn("mytool", dir_name)


# ============================================================================
# PathUtils.get_data_dir 测试
# ============================================================================

class TestPathUtilsGetDataDir(unittest.TestCase):
    """PathUtils.get_data_dir 测试集。"""

    def setUp(self):
        self.test_root = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root)

    def test_creates_data_dir(self):
        """应创建数据目录。"""
        data_dir = PathUtils.get_data_dir(self.test_root, "video_dedup")
        self.assertTrue(os.path.isdir(data_dir))

    def test_path_ends_with_tool_name(self):
        """路径应以工具名结尾。"""
        data_dir = PathUtils.get_data_dir(self.test_root, "my_tool")
        self.assertTrue(data_dir.endswith("my_tool"))


# ============================================================================
# PathUtils.safe_filename 测试
# ============================================================================

class TestPathUtilsSafeFilename(unittest.TestCase):
    """PathUtils.safe_filename 测试集。"""

    def test_removes_illegal_chars(self):
        """应替换非法字符为下划线。"""
        result = PathUtils.safe_filename("test/file:name?.txt")
        for ch in '\\/:*?"<>|':
            self.assertNotIn(ch, result)

    def test_strips_dots_and_spaces(self):
        """应去除首尾空格和点。"""
        result = PathUtils.safe_filename("  .test.  ")
        self.assertFalse(result.startswith("."))
        self.assertFalse(result.endswith("."))
        self.assertFalse(result.startswith(" "))

    def test_normal_filename_unchanged(self):
        """正常文件名应保持不变。"""
        result = PathUtils.safe_filename("normal_file.txt")
        self.assertEqual(result, "normal_file.txt")


# ============================================================================
# format_size 测试
# ============================================================================

class TestFormatSize(unittest.TestCase):
    """format_size 函数测试集。"""

    def test_zero_bytes(self):
        """0 字节应返回 '0.0 B'。"""
        self.assertEqual(format_size(0), "0.0 B")

    def test_kb(self):
        """1536 字节应返回 '1.5 KB'。"""
        self.assertEqual(format_size(1536), "1.5 KB")

    def test_mb(self):
        """1MB 应返回 '1.0 MB'。"""
        self.assertEqual(format_size(1048576), "1.0 MB")

    def test_gb(self):
        """1GB 应返回 '1.0 GB'。"""
        self.assertEqual(format_size(1073741824), "1.0 GB")

    def test_tb(self):
        """1TB 应返回 '1.0 TB'。"""
        self.assertEqual(format_size(1099511627776), "1.0 TB")

    def test_custom_decimal_places(self):
        """自定义小数位数应生效。"""
        self.assertEqual(
            format_size(1073741824, decimal_places=2),
            "1.00 GB",
        )


# ============================================================================
# format_duration 测试
# ============================================================================

class TestFormatDuration(unittest.TestCase):
    """format_duration 函数测试集。"""

    def test_zero_seconds(self):
        """0 秒应返回 '0s'。"""
        self.assertEqual(format_duration(0), "0s")

    def test_seconds_only(self):
        """仅秒数应正确格式化。"""
        self.assertEqual(format_duration(45), "45s")

    def test_minutes_and_seconds(self):
        """分秒应正确格式化。"""
        self.assertEqual(format_duration(65), "1m 5s")

    def test_hours_minutes_seconds(self):
        """时分秒应正确格式化。"""
        self.assertEqual(format_duration(3661), "1h 1m 1s")

    def test_negative_returns_zero(self):
        """负数应返回 '0s'。"""
        self.assertEqual(format_duration(-10), "0s")


# ============================================================================
# format_timestamp 测试
# ============================================================================

class TestFormatTimestamp(unittest.TestCase):
    """format_timestamp 函数测试集。"""

    def test_valid_datetime(self):
        """有效 datetime 应正确格式化。"""
        dt = datetime(2026, 8, 4, 12, 30, 45)
        self.assertEqual(
            format_timestamp(dt),
            "2026-08-04 12:30:45",
        )

    def test_none_returns_empty(self):
        """None 应返回空字符串。"""
        self.assertEqual(format_timestamp(None), "")


# ============================================================================
# compute_file_hash 测试
# ============================================================================

class TestComputeFileHash(unittest.TestCase):
    """compute_file_hash 函数测试集。"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.test_dir, "test.txt")
        with open(self.test_file, "w") as f:
            f.write("hello fabrica")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_md5_hash(self):
        """MD5 哈希应正确计算。"""
        expected = hashlib.md5(b"hello fabrica").hexdigest()
        self.assertEqual(compute_file_hash(self.test_file), expected)

    def test_sha256_hash(self):
        """SHA256 哈希应正确计算。"""
        expected = hashlib.sha256(b"hello fabrica").hexdigest()
        self.assertEqual(
            compute_file_hash(self.test_file, "sha256"),
            expected,
        )

    def test_same_file_same_hash(self):
        """同一文件多次计算应返回相同哈希。"""
        hash1 = compute_file_hash(self.test_file)
        hash2 = compute_file_hash(self.test_file)
        self.assertEqual(hash1, hash2)

    def test_different_files_different_hash(self):
        """不同文件应返回不同哈希。"""
        other_file = os.path.join(self.test_dir, "other.txt")
        with open(other_file, "w") as f:
            f.write("different content")
        hash1 = compute_file_hash(self.test_file)
        hash2 = compute_file_hash(other_file)
        self.assertNotEqual(hash1, hash2)

    def test_nonexistent_file_raises(self):
        """文件不存在时应抛出 FileNotFoundError。"""
        with self.assertRaises(FileNotFoundError):
            compute_file_hash("/nonexistent/path/file.txt")


# ============================================================================
# chunked 测试
# ============================================================================

class TestChunked(unittest.TestCase):
    """chunked 函数测试集。"""

    def test_normal_chunking(self):
        """正常分块应正确。"""
        result = list(chunked([1, 2, 3, 4, 5], 2))
        self.assertEqual(result, [[1, 2], [3, 4], [5]])

    def test_empty_iterable(self):
        """空可迭代对象应返回空列表。"""
        result = list(chunked([], 3))
        self.assertEqual(result, [])

    def test_size_larger_than_iterable(self):
        """块大小大于列表长度时应返回单个块。"""
        result = list(chunked([1, 2, 3], 10))
        self.assertEqual(result, [[1, 2, 3]])

    def test_generator_input(self):
        """应支持生成器输入。"""
        def gen():
            for i in range(5):
                yield i
        result = list(chunked(gen(), 2))
        self.assertEqual(result, [[0, 1], [2, 3], [4]])

    def test_invalid_size_raises(self):
        """无效块大小应抛出 ValueError。"""
        with self.assertRaises(ValueError):
            list(chunked([1, 2, 3], 0))
        with self.assertRaises(ValueError):
            list(chunked([1, 2, 3], -1))


if __name__ == "__main__":
    unittest.main()
