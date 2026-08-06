"""Fabrica 工具集平台。

Fabrica 是一个可扩展的桌面工具集平台，提供统一的工具插件管理能力。
拉丁语 "Fabrica" 意为「工坊」，汇聚各类实用功能。
"""

from .app import create_app

__version__ = "0.1.0"

__all__ = ["create_app", "__version__"]
