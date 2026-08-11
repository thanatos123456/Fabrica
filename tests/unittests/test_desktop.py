"""fabrica/desktop 桌面集成模块测试。

测试目标：
    - wait_for_server: 端口就绪探测
    - launch_browser: 浏览器回退模式
    - DesktopAPI: JS 桥接层（open_directory_dialog / open_file_dialog / open_in_explorer）
"""

import os
import socket
import sys
import unittest
from unittest.mock import patch, MagicMock

# 确保项目根目录在 sys.path 中
_FABRICA_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _FABRICA_ROOT not in sys.path:
    sys.path.insert(0, _FABRICA_ROOT)

from fabrica.desktop import wait_for_server, launch_browser, DesktopAPI


# ============================================================================
# wait_for_server 测试
# ============================================================================

class TestWaitForServer(unittest.TestCase):
    """wait_for_server 函数测试集。"""

    def test_port_open_returns_true(self):
        """端口开放时应快速返回 True。"""
        # 创建一个临时监听 socket
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        try:
            result = wait_for_server('127.0.0.1', port, timeout=2.0)
            self.assertTrue(result)
        finally:
            listener.close()

    def test_port_closed_returns_false(self):
        """端口未开放时应超时返回 False。"""
        # 找一个未被使用的端口
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()

        result = wait_for_server('127.0.0.1', port, timeout=0.5)
        self.assertFalse(result)


# ============================================================================
# launch_browser 测试
# ============================================================================

class TestLaunchBrowser(unittest.TestCase):
    """launch_browser 函数测试集。"""

    @patch('fabrica.desktop.webbrowser.open')
    def test_opens_correct_url(self, mock_open):
        """应使用正确的 URL 打开浏览器。"""
        launch_browser('127.0.0.1', 8520)
        mock_open.assert_called_once_with('http://127.0.0.1:8520')

    @patch('fabrica.desktop.webbrowser.open')
    def test_opens_with_custom_host_port(self, mock_open):
        """应使用自定义 host 和 port 拼接 URL。"""
        launch_browser('0.0.0.0', 9000)
        mock_open.assert_called_once_with('http://0.0.0.0:9000')


# ============================================================================
# DesktopAPI 测试
# ============================================================================

class TestDesktopAPI(unittest.TestCase):
    """DesktopAPI 类测试集。"""

    def setUp(self):
        self.api = DesktopAPI()

    @patch('fabrica.desktop._webview')
    def test_open_directory_dialog_returns_path(self, mock_webview):
        """选择目录时应返回完整路径。"""
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = ['/tmp/videos']
        mock_webview.windows = [mock_window]
        mock_webview.FOLDER_DIALOG = mock_webview.FOLDER_DIALOG

        result = self.api.open_directory_dialog()
        self.assertEqual(result, '/tmp/videos')
        mock_window.create_file_dialog.assert_called_once_with(
            mock_webview.FOLDER_DIALOG
        )

    @patch('fabrica.desktop._webview')
    def test_open_directory_dialog_cancelled(self, mock_webview):
        """取消选择时应返回 None。"""
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = None
        mock_webview.windows = [mock_window]

        result = self.api.open_directory_dialog()
        self.assertIsNone(result)

    @patch('fabrica.desktop._webview')
    def test_open_directory_dialog_empty_result(self, mock_webview):
        """空结果列表时应返回 None。"""
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = []
        mock_webview.windows = [mock_window]

        result = self.api.open_directory_dialog()
        self.assertIsNone(result)

    @patch('fabrica.desktop._webview')
    def test_open_file_dialog_returns_path(self, mock_webview):
        """选择文件时应返回完整路径。"""
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = ['/tmp/video.mp4']
        mock_webview.windows = [mock_window]
        mock_webview.OPEN_DIALOG = mock_webview.OPEN_DIALOG

        result = self.api.open_file_dialog()
        self.assertEqual(result, '/tmp/video.mp4')
        mock_window.create_file_dialog.assert_called_once_with(
            mock_webview.OPEN_DIALOG
        )

    @patch('fabrica.desktop._webview')
    def test_open_file_dialog_cancelled(self, mock_webview):
        """取消选择时应返回 None。"""
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = None
        mock_webview.windows = [mock_window]

        result = self.api.open_file_dialog()
        self.assertIsNone(result)

    @patch('fabrica.desktop.subprocess.Popen')
    @patch('fabrica.desktop.platform.system', return_value='Windows')
    @patch('fabrica.desktop.os.path.isfile', return_value=True)
    def test_open_in_explorer_windows_file(
        self, mock_isfile, mock_system, mock_popen
    ):
        """Windows 下对文件应使用 explorer /select,。"""
        result = self.api.open_in_explorer(r'C:\videos\test.mp4')
        self.assertTrue(result)
        mock_popen.assert_called_once_with(
            ['explorer', '/select,', r'C:\videos\test.mp4']
        )

    @patch('fabrica.desktop.subprocess.Popen')
    @patch('fabrica.desktop.platform.system', return_value='Windows')
    @patch('fabrica.desktop.os.path.isfile', return_value=False)
    def test_open_in_explorer_windows_directory(
        self, mock_isfile, mock_system, mock_popen
    ):
        """Windows 下对目录应直接使用 explorer 打开。"""
        result = self.api.open_in_explorer(r'C:\videos')
        self.assertTrue(result)
        mock_popen.assert_called_once_with(['explorer', r'C:\videos'])

    @patch('fabrica.desktop.subprocess.Popen')
    @patch('fabrica.desktop.platform.system', return_value='Linux')
    @patch('fabrica.desktop.os.path.isfile', return_value=True)
    @patch('fabrica.desktop.os.path.dirname', return_value='/tmp')
    def test_open_in_explorer_linux_file(
        self, mock_dirname, mock_isfile, mock_system, mock_popen
    ):
        """Linux 下对文件应使用 xdg-open 打开所在目录。"""
        result = self.api.open_in_explorer('/tmp/video.mp4')
        self.assertTrue(result)
        mock_popen.assert_called_once_with(['xdg-open', '/tmp'])

    @patch('fabrica.desktop.subprocess.Popen')
    @patch('fabrica.desktop.platform.system', return_value='Linux')
    @patch('fabrica.desktop.os.path.isfile', return_value=False)
    def test_open_in_explorer_linux_directory(
        self, mock_isfile, mock_system, mock_popen
    ):
        """Linux 下对目录应直接使用 xdg-open 打开。"""
        result = self.api.open_in_explorer('/tmp/videos')
        self.assertTrue(result)
        mock_popen.assert_called_once_with(['xdg-open', '/tmp/videos'])

    @patch('fabrica.desktop.subprocess.Popen', side_effect=Exception("fail"))
    @patch('fabrica.desktop.platform.system', return_value='Windows')
    @patch('fabrica.desktop.os.path.isfile', return_value=True)
    def test_open_in_explorer_exception_returns_false(
        self, mock_isfile, mock_system, mock_popen
    ):
        """异常时应返回 False。"""
        result = self.api.open_in_explorer(r'C:\videos\test.mp4')
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
