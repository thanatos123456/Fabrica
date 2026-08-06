"""Fabrica 测试根配置。

在所有测试导入前注入 aurora 公共库路径与项目根目录。
pytest 会先加载父级 conftest，子目录 conftest 无需重复此逻辑。
"""

import asyncio
import os
import sys
import types

import pytest

# 从本文件位置推导项目根目录
# tests/conftest.py → 2 层 dirname → Fabrica/
_FABRICA_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
# Fabrica 的父目录是 nexus，nexus 的父目录即 OmniPivot
_NEXUS_ROOT = os.path.dirname(_FABRICA_ROOT)
_OMNPIPIVOT_ROOT = os.path.dirname(_NEXUS_ROOT)

# aurora 路径
_AURORA_PATH = os.path.join(
    _OMNPIPIVOT_ROOT, "aurora", "python"
)
_AURORA_ROOT = os.path.join(_OMNPIPIVOT_ROOT, "aurora")

# 注入 aurora 公共库路径
if os.path.isdir(_AURORA_PATH):
    if _AURORA_PATH not in sys.path:
        sys.path.insert(0, _AURORA_PATH)

# 注入 Fabrica 项目根目录
if _FABRICA_ROOT not in sys.path:
    sys.path.insert(0, _FABRICA_ROOT)

# 创建虚拟 aurora 包（aurora/__init__.py 不存在，需手动构造）
# 让 from aurora.python.xxx import ... 能正确解析
if "aurora" not in sys.modules:
    _aurora_pkg = types.ModuleType("aurora")
    _aurora_pkg.__path__ = [_AURORA_ROOT]
    sys.modules["aurora"] = _aurora_pkg

if "aurora.python" not in sys.modules:
    _aurora_python_pkg = types.ModuleType("aurora.python")
    _aurora_python_pkg.__path__ = [_AURORA_PATH]
    sys.modules["aurora.python"] = _aurora_python_pkg

# 修正 nemesis 模块导出别名：src 代码使用 NemesisBaseException，
# 但 aurora/python/nemesis/__init__.py 导出为 NemesisException/BaseException
try:
    import aurora.python.nemesis as _nemesis
    if not hasattr(_nemesis, "NemesisBaseException"):
        if hasattr(_nemesis, "NemesisException"):
            _nemesis.NemesisBaseException = (
                _nemesis.NemesisException
            )
        elif hasattr(_nemesis, "BaseException"):
            _nemesis.NemesisBaseException = (
                _nemesis.BaseException
            )
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _restore_event_loop():
    """每个测试结束后恢复主线程事件循环。

    兼容 Python 3.10：asyncio.run() 会在结束时调用
    asyncio.set_event_loop(None)，将主线程事件循环置空。
    若后续测试依赖主线程事件循环（如 starlette TestClient），
    会因 "no current event loop" 而失败。此处恢复，保证测试隔离。
    """
    yield
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
