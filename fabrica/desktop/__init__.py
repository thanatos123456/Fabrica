"""Fabrica 桌面集成模块。

通过 pywebview 将 Web 前端包装为原生桌面窗口。
提供窗口启动、端口探测、浏览器回退和 JS API 桥接能力。

设计原则：
    - pywebview 可选导入：模块顶部用 try/except 导入 webview，无 GUI 环境
      （Linux/CI）下 webview 为 None，不影响 main.py 启动。
    - 线程隔离：uvicorn 服务运行在后台守护线程，pywebview 窗口运行在
      主线程（GUI 线程约束）。
    - 优雅退出：窗口关闭回调触发 server.should_exit，主线程 join 等待清理。
"""

import os
import socket
import time
import platform
import subprocess
import webbrowser
from typing import Callable, Optional

try:
    import webview as _webview
except ImportError:
    _webview = None

__all__ = [
    "launch_window",
    "launch_browser",
    "wait_for_server",
    "DesktopAPI",
]


# ============================================================================
# 端口就绪探测
# ============================================================================

def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """轮询探测服务端口是否可连接。

    Args:
        host: 服务地址。
        port: 服务端口。
        timeout: 最大等待时间（秒）。

    Returns:
        True 表示服务已就绪，False 表示超时。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# ============================================================================
# 浏览器回退模式
# ============================================================================

def launch_browser(host: str, port: int) -> None:
    """dev_mode 模式下自动打开系统浏览器（Linux 开发环境回退）。

    Args:
        host: 服务地址。
        port: 服务端口。
    """
    url = f"http://{host}:{port}"
    webbrowser.open(url)


# ============================================================================
# 桌面窗口启动
# ============================================================================

def launch_window(
    host: str,
    port: int,
    title: str = "Fabrica 工具集平台",
    width: int = 1280,
    height: int = 800,
    min_size: tuple[int, int] = (1024, 600),
    on_close: Callable[[], None] | None = None,
) -> None:
    """启动 pywebview 桌面窗口，阻塞主线程直到窗口关闭。

    Args:
        host: 服务监听地址（通常 127.0.0.1）。
        port: 服务监听端口。
        title: 窗口标题。
        width: 窗口初始宽度。
        height: 窗口初始高度。
        min_size: 窗口最小尺寸 (width, height)。
        on_close: 窗口关闭时的回调（用于触发服务停止）。
    """
    if _webview is None:
        raise RuntimeError("pywebview is not installed")

    url = f"http://{host}:{port}"

    api = DesktopAPI()

    _webview.create_window(
        title,
        url,
        width=width,
        height=height,
        min_size=min_size,
        js_api=api,
    )

    _webview.start()

    # 窗口关闭后触发回调
    if on_close is not None:
        on_close()


# ============================================================================
# DesktopAPI — JS 桥接层
# ============================================================================

class DesktopAPI:
    """暴露给前端 JS 的桌面 API（通过 pywebview js_api 桥接）。

    所有方法参数和返回值必须可 JSON 序列化。
    前端通过 window.pywebview.api.<method>() 异步调用。
    """

    def open_directory_dialog(self) -> Optional[str]:
        """打开原生目录选择对话框。

        Returns:
            选中目录的完整路径，取消选择时返回 None。
        """
        if _webview is None:
            return None
        result = _webview.windows[0].create_file_dialog(_webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def open_file_dialog(self) -> Optional[str]:
        """打开原生文件选择对话框（file 类型参数用）。

        Returns:
            选中文件的完整路径，取消选择时返回 None。
        """
        if _webview is None:
            return None
        result = _webview.windows[0].create_file_dialog(_webview.OPEN_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def open_in_explorer(self, path: str) -> bool:
        """在系统文件管理器中打开并选中指定文件/目录。

        Args:
            path: 文件或目录的完整路径。

        Returns:
            True 表示成功，False 表示失败。
        """
        try:
            if platform.system() == "Windows":
                if os.path.isfile(path):
                    subprocess.Popen(['explorer', '/select,', path])
                else:
                    subprocess.Popen(['explorer', path])
            elif platform.system() == "Linux":
                target = os.path.dirname(path) if os.path.isfile(path) else path
                subprocess.Popen(['xdg-open', target])
            return True
        except Exception:
            return False
