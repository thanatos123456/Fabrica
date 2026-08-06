"""Fabrica 公共基础设施模块。

提供日志系统、设备检测、路径工具和通用辅助函数。
"""

from .logger import (
    LoggerManager,
    get_logger,
    setup_logging,
    logger,
)
from .device import (
    is_cuda_available,
    get_device,
    get_device_info,
    get_batch_size_hint,
)
from .helpers import (
    PathUtils,
    format_size,
    format_duration,
    format_timestamp,
    compute_file_hash,
    chunked,
)
from .config import (
    configure_fabrica,
    get_config,
    get_all_config,
    reload_config,
)
from .exceptions import (
    ErrorCode,
    FabricaError,
    ToolNotFoundError,
    ToolRegisterError,
    ToolRunError,
    ToolInitError,
    TaskNotFoundError,
    TaskCancelError,
    TaskTimeoutError,
    TaskStateError,
    ParamInvalidError,
    ParamMissingError,
    ParamTypeError,
    ParamValidationError,
    ConfigError,
    ServerError,
    safe_call,
    exception_response,
)

__all__ = [
    # 日志模块
    "LoggerManager",
    "get_logger",
    "setup_logging",
    "logger",
    # 设备检测模块
    "is_cuda_available",
    "get_device",
    "get_device_info",
    "get_batch_size_hint",
    # 路径工具与通用函数
    "PathUtils",
    "format_size",
    "format_duration",
    "format_timestamp",
    "compute_file_hash",
    "chunked",
    # 配置管理模块
    "configure_fabrica",
    "get_config",
    "get_all_config",
    "reload_config",
    # 异常体系模块
    "ErrorCode",
    "FabricaError",
    "ToolNotFoundError",
    "ToolRegisterError",
    "ToolRunError",
    "ToolInitError",
    "TaskNotFoundError",
    "TaskCancelError",
    "TaskTimeoutError",
    "TaskStateError",
    "ParamInvalidError",
    "ParamMissingError",
    "ParamTypeError",
    "ParamValidationError",
    "ConfigError",
    "ServerError",
    "safe_call",
    "exception_response",
]
