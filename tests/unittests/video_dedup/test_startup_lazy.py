"""启动优化回归测试（懒加载重库）。

验证导入 video_dedup 工具包时不会加载 pipeline 及其背后的重库
（torch / open_clip / faiss / av），从而保证 discover()/启动不被重库拖慢。
"""

import os
import subprocess
import sys
import unittest

import fabrica

# 需在导入工具包时保持未加载的重库
HEAVY_LIBS = ("faiss", "torch", "open_clip", "av")


def _fabrica_root() -> str:
    """返回包含 fabrica 包的目录。"""
    return os.path.dirname(os.path.dirname(fabrica.__file__))


class TestLazyImport(unittest.TestCase):
    """导入工具包不应加载重库。"""

    def test_tool_package_does_not_bind_pipeline_at_import(self):
        """导入工具包不应在包命名空间绑定 CascadePipeline（即不触发重库加载）。"""
        import fabrica.tools.video_dedup as vd

        self.assertFalse(
            hasattr(vd, "CascadePipeline"),
            "video_dedup 包不应在 import 时绑定 CascadePipeline（重库应懒加载）",
        )

    def test_import_tool_package_does_not_load_heavy_libs(self):
        """干净子进程中导入工具包，faiss/torch/open_clip/av 不得进入 sys.modules。

        子进程需复刻 tests/conftest.py 的 aurora 虚拟包引导，使 aurora 可导入。
        """
        omni_root = os.path.dirname(os.path.dirname(_fabrica_root()))
        bootstrap = f"""
import os, sys, types
_omni = {omni_root!r}
_aurora_path = os.path.join(_omni, "aurora", "python")
_aurora_root = os.path.join(_omni, "aurora")
if _aurora_path not in sys.path:
    sys.path.insert(0, _aurora_path)
if "aurora" not in sys.modules:
    m = types.ModuleType("aurora"); m.__path__ = [_aurora_root]; sys.modules["aurora"] = m
if "aurora.python" not in sys.modules:
    m = types.ModuleType("aurora.python"); m.__path__ = [_aurora_path]; sys.modules["aurora.python"] = m
try:
    import aurora.python.nemesis as _nemesis
    if not hasattr(_nemesis, "NemesisBaseException"):
        if hasattr(_nemesis, "NemesisException"):
            _nemesis.NemesisBaseException = _nemesis.NemesisException
        elif hasattr(_nemesis, "BaseException"):
            _nemesis.NemesisBaseException = _nemesis.BaseException
except ImportError:
    pass
import importlib
importlib.import_module("fabrica.tools.video_dedup")
heavy = [lib for lib in {HEAVY_LIBS!r} if lib in sys.modules]
print("HEAVY_IMPORTED=" + ",".join(heavy))
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        proc = subprocess.run(
            [sys.executable, "-c", bootstrap],
            capture_output=True,
            text=True,
            cwd=_fabrica_root(),
            env=env,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(
            proc.stdout.strip(),
            "HEAVY_IMPORTED=",
            msg="导入 video_dedup 工具包不应加载重库",
        )


if __name__ == "__main__":
    unittest.main()
