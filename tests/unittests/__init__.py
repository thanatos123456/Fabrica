"""Fabrica 单元测试包。

在包加载时注入 aurora 公共库路径与项目根目录，
确保 unittest discover 也能正确解析 aurora 导入。
"""

import os
import sys
import types

# 从本文件位置推导项目根目录
# tests/unittests/__init__.py → 2 层 dirname → Fabrica/
_FABRICA_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_NEXUS_ROOT = os.path.dirname(_FABRICA_ROOT)
_OMNPIPIVOT_ROOT = os.path.dirname(_NEXUS_ROOT)

# aurora 路径
_AURORA_PATH = os.path.join(_OMNPIPIVOT_ROOT, "aurora", "python")
_AURORA_ROOT = os.path.join(_OMNPIPIVOT_ROOT, "aurora")

# 注入 aurora 公共库路径
if os.path.isdir(_AURORA_PATH):
    if _AURORA_PATH not in sys.path:
        sys.path.insert(0, _AURORA_PATH)

# 注入 Fabrica 项目根目录
if _FABRICA_ROOT not in sys.path:
    sys.path.insert(0, _FABRICA_ROOT)

# 创建虚拟 aurora 包
if "aurora" not in sys.modules:
    _aurora_pkg = types.ModuleType("aurora")
    _aurora_pkg.__path__ = [_AURORA_ROOT]
    sys.modules["aurora"] = _aurora_pkg

if "aurora.python" not in sys.modules:
    _aurora_python_pkg = types.ModuleType("aurora.python")
    _aurora_python_pkg.__path__ = [_AURORA_PATH]
    sys.modules["aurora.python"] = _aurora_python_pkg

# 修正 nemesis 模块导出别名
try:
    import aurora.python.nemesis as _nemesis
    if not hasattr(_nemesis, "NemesisBaseException"):
        if hasattr(_nemesis, "NemesisException"):
            _nemesis.NemesisBaseException = _nemesis.NemesisException
        elif hasattr(_nemesis, "BaseException"):
            _nemesis.NemesisBaseException = _nemesis.BaseException
except ImportError:
    pass
