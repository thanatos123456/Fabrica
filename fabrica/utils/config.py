#!/usr/bin/env python3
"""Fabrica 配置管理模块。

基于 aurora/phoenix 框架，负责系统配置的加载和管理。
支持 YAML/JSON 格式。

用法：
    from fabrica.utils.config import configure_fabrica, get_config

    configure_fabrica()
    port = get_config("fabrica.server.port", 8520)
"""

import os
from typing import Any, Dict, Optional

from aurora.python.phoenix import (
    configure_phoenix,
    get_config_manager,
)

# ============================================================================
# 路径计算
# ============================================================================

# __file__ 位于 nexus/Fabrica/fabrica/utils/config.py
# 向上两级到达项目根目录 nexus/Fabrica/
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CURRENT_DIR))

# 全局配置管理器实例
_config_manager = None


# ============================================================================
# 配置初始化
# ============================================================================

def configure_fabrica(config_dir: str = "config") -> None:
    """初始化 Phoenix 配置模块。

    扫描指定目录下的 YAML/JSON 配置文件并加载。

    Args:
        config_dir: 配置目录名称（相对于项目根目录）。
            默认为 "config"，即 nexus/Fabrica/config/。
    """
    global _config_manager

    # 解析配置目录的绝对路径
    config_path = os.path.join(_PROJECT_ROOT, config_dir)

    # 配置 Phoenix 模块
    configure_phoenix({
        "config_dirs": [config_path],
        "file_extensions": [".yaml", ".yml", ".json"],
        "hot_reload": False,
        "env_prefix": "FABRICA_",
    })

    # 获取配置管理器实例
    _config_manager = get_config_manager()


# ============================================================================
# 配置获取
# ============================================================================

def get_config(key: str, default: Any = None) -> Any:
    """获取配置项。

    通过点分路径从配置中查找值。

    Args:
        key: 配置键名，格式为 "section.subsection.key"。
            例如 "fabrica.server.port"。
        default: 配置项不存在时的默认值。

    Returns:
        配置值或默认值。
    """
    # 自动初始化
    if _config_manager is None:
        configure_fabrica()

    try:
        # 获取 config 配置段（对应 config.yaml 文件）
        config_data = _config_manager.get_config("config")

        if not isinstance(config_data, dict):
            return default

        # 按 key 路径递归查找
        current = config_data
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default

        return current
    except Exception:
        return default


def get_all_config() -> Dict[str, Any]:
    """获取完整配置字典。

    Returns:
        完整的配置字典。异常时返回空字典。
    """
    # 自动初始化
    if _config_manager is None:
        configure_fabrica()

    try:
        config_data = _config_manager.get_config("config")
        if isinstance(config_data, dict):
            return config_data
        return {}
    except Exception:
        return {}


# ============================================================================
# 配置重载
# ============================================================================

def reload_config() -> None:
    """重新加载配置。

    从配置文件重新加载所有配置源。
    修改 config.yaml 后调用此方法可读到新值。
    """
    # 自动初始化
    if _config_manager is None:
        configure_fabrica()
        return

    try:
        _config_manager._load_all_configs()
    except Exception:
        pass