# -*- mode: python ; coding: utf-8 -*-
"""Fabrica Windows EXE 打包配置（PyInstaller onedir 模式）。

在 Windows 环境执行（PyInstaller 不支持交叉编译）：
    pyinstaller build_win.spec --clean

产物在 dist/fabrica/ 目录，整个目录分发给用户。

路径说明：
    - SPECPATH 为 PyInstaller 提供的 spec 所在目录（本文件位于
      <OmniPivot>/nexus/Fabrica/）。
    - 向上 2 级到达 OmniPivot 根，再进入 aurora/python 定位本地包。
"""

import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Tree 在 PyInstaller spec 上下文中是内建可用的，无需 import

# ---------------------------------------------------------------------------
# 路径计算
# ---------------------------------------------------------------------------
# spec 所在目录（<OmniPivot>/nexus/Fabrica/）
_FABRICA_ROOT = os.path.abspath(SPECPATH) # type: ignore
# OmniPivot 项目根（向上 2 级）
_OMNIPIVOT_ROOT = os.path.abspath(os.path.join(_FABRICA_ROOT, "..", ".."))
# aurora 本地包路径（fabrica 依赖 aurora.python.{helios,nemesis,phoenix,hestia}）
_AURORA_PYTHON = os.path.join(_OMNIPIVOT_ROOT, "aurora", "python")

# 在 spec 执行阶段提前注入路径，使 collect_data_files / collect_submodules
# 能 import 到 aurora.python.* 和 fabrica.* 模块（pathex 在 Analysis 阶段才生效）
sys.path.insert(0, _OMNIPIVOT_ROOT)
sys.path.insert(0, _AURORA_PYTHON)

# ---------------------------------------------------------------------------
# 数据文件收集
# ---------------------------------------------------------------------------
# 静态资源：手工收集为 (src_file, dst_dir) 元组列表
# PyInstaller 的 datas 期望 (源文件, 目标目录)，目标目录不能含文件名，
# 否则会创建 filename/filename 的额外目录层
_static_src = os.path.join(_FABRICA_ROOT, "fabrica", "server", "static")
_static_datas = []
if os.path.isdir(_static_src):
    for _f in glob.glob(
        os.path.join(_static_src, "**", "*"), recursive=True
    ):
        if os.path.isfile(_f):
            rel = os.path.relpath(_f, _static_src).replace(os.sep, "/")
            rel_dir = os.path.dirname(rel)
            dst = (
                os.path.join("fabrica", "server", "static", rel_dir)
                if rel_dir
                else os.path.join("fabrica", "server", "static")
            )
            _static_datas.append((_f, dst))
# open_clip 词汇表等数据文件（tokenizer 导入时即需要）
_open_clip_datas = collect_data_files("open_clip")
# 配置文件（config/config.yaml → dist 根目录）
_config_datas = [
    (os.path.join(_FABRICA_ROOT, "config", "config.yaml"), "."),
]
_datas = _static_datas + _open_clip_datas + _config_datas

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
    _aurora_hidden
    + _video_dedup_hidden
    + _third_party_hidden
    + [
        "pywebview",
        "pywebview.platforms.winforms",  # Windows EdgeWebView2 后端
    ]
)

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis( # type: ignore
    [os.path.join(_FABRICA_ROOT, "main.py")],
    pathex=[_FABRICA_ROOT, _OMNIPIVOT_ROOT, _AURORA_PYTHON],
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

pyz = PYZ(a.pure) # type: ignore

exe = EXE( # type: ignore
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="fabrica",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT( # type: ignore
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="fabrica",
)