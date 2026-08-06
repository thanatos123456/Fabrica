# -*- mode: python ; coding: utf-8 -*-
"""Fabrica Windows EXE 打包配置（PyInstaller onedir 模式）。

在 Windows 环境执行（PyInstaller 不支持交叉编译）：
    pyinstaller build_win.spec --clean

产物在 dist/fabrica/ 目录，整个目录分发给用户。

路径说明：
    - SPECPATH 为 PyInstaller 提供的 spec 所在目录（本文件位于
      <OmniPivot>/nexus/Fabrica/）。
    - 向上 3 级到达 OmniPivot 根，再进入 aurora/python 定位本地包。
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# 路径计算
# ---------------------------------------------------------------------------
# spec 所在目录（<OmniPivot>/nexus/Fabrica/）
_FABRICA_ROOT = os.path.abspath(SPECPATH)
# OmniPivot 项目根（向上 3 级）
_OMNIPIVOT_ROOT = os.path.abspath(os.path.join(_FABRICA_ROOT, "..", "..", ".."))
# aurora 本地包路径（fabrica 依赖 aurora.python.{helios,nemesis,phoenix,hestia}）
_AURORA_PYTHON = os.path.join(_OMNIPIVOT_ROOT, "aurora", "python")

# ---------------------------------------------------------------------------
# 数据文件收集
# ---------------------------------------------------------------------------
# 静态资源（fabrica/server/static/ → 同路径）
_static_datas = collect_data_files("fabrica.server", includes=["static/**"])
# 配置文件（config/config.yaml → dist 根目录）
_config_datas = [
    (os.path.join(_FABRICA_ROOT, "config", "config.yaml"), "."),
]
_datas = _static_datas + _config_datas

# ---------------------------------------------------------------------------
# 隐藏导入
# ---------------------------------------------------------------------------
# 本地 aurora 包（helios/nemesis/phoenix/hestia）
_aurora_hidden = [
    "aurora.python.helios",
    "aurora.python.nemesis",
    "aurora.python.phoenix",
    "aurora.python.hestia",
]
# video_dedup 工具子模块（工具由 main.py 动态发现，需显式收集）
_video_dedup_hidden = collect_submodules("fabrica.tools.video_dedup")
# 第三方依赖（重/可选，显式声明）
_third_party_hidden = ["open_clip", "faiss", "av"]
_hiddenimports = (
    _aurora_hidden + _video_dedup_hidden + _third_party_hidden
)

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join(_FABRICA_ROOT, "main.py")],
    pathex=[_FABRICA_ROOT, _AURORA_PYTHON],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="fabrica",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 服务器程序需控制台输出日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="fabrica",
)