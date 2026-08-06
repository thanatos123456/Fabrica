#!/usr/bin/env python3
"""Fabrica FastAPI 应用入口。

完整应用工厂实现在 `fabrica.server` 模块（见 T3.1）。
此处作为薄层转发，保持 `from fabrica.app import create_app` 的兼容性。
"""

from fabrica.server import create_app

__all__ = ["create_app"]