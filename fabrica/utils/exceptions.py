#!/usr/bin/env python3
"""Fabrica 异常定义模块。

基于 aurora/nemesis 框架，定义 Fabrica 统一的异常体系。
包括错误码常量和异常类，支持工具、任务、参数等场景。

用法：
    from fabrica.utils.exceptions import (
        ToolNotFoundError, safe_call, exception_response
    )

    raise ToolNotFoundError("工具不存在")
    result = safe_call(risky_func, fallback=None)
    resp = exception_response(exc)
"""

from typing import Any, Dict, Optional

from aurora.python.nemesis import (
    ErrorCode as BaseErrorCode,
    BusinessException,
    NemesisException,
    safe_call as _nemesis_safe_call,
    exception_response as _nemesis_exception_response,
)


# ============================================================================
# 错误码定义
# ============================================================================

class ErrorCode(BaseErrorCode):
    """Fabrica 错误码常量。

    继承 nemesis 的 BaseErrorCode，添加 Fabrica 特定错误码。
    分为 4 组：系统级、工具级、任务级、参数级。
    """

    # 系统错误码
    SYSTEM_ERROR = "SYSTEM_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

    # 工具错误码
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_REGISTER_ERROR = "TOOL_REGISTER_ERROR"
    TOOL_RUN_ERROR = "TOOL_RUN_ERROR"
    TOOL_INIT_ERROR = "TOOL_INIT_ERROR"

    # 任务错误码
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_CANCEL_ERROR = "TASK_CANCEL_ERROR"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    TASK_STATE_ERROR = "TASK_STATE_ERROR"

    # 参数错误码
    PARAM_INVALID = "PARAM_INVALID"
    PARAM_MISSING = "PARAM_MISSING"
    PARAM_TYPE_ERROR = "PARAM_TYPE_ERROR"
    PARAM_VALIDATION_ERROR = "PARAM_VALIDATION_ERROR"


# ============================================================================
# 基础异常类
# ============================================================================

class FabricaError(BusinessException):
    """Fabrica 系统基础异常。

    所有 Fabrica 异常的基类，继承 nemesis BusinessException。
    支持自定义错误消息、错误码、HTTP 状态码和额外详情。

    Attributes:
        message: 错误消息文本。
        error_code: 错误码字符串。
        status_code: HTTP 状态码。
        details: 额外详情字典。
    """

    error_code = "FABRICA_ERROR"
    status_code = 400
    message = "Fabrica错误"

    def __init__(
        self,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """初始化 Fabrica 异常。

        Args:
            message: 错误消息。为 None 时使用类级默认值。
            error_code: 错误码。为 None 时使用类级默认值。
            status_code: HTTP 状态码。为 None 时使用类级默认值。
            details: 额外详情字典。
            **kwargs: 传递给 nemesis BusinessException 的额外参数。
        """
        if message is None:
            message = self.__class__.message
        if error_code is None:
            error_code = self.__class__.error_code
        if status_code is None:
            status_code = self.__class__.status_code

        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            **kwargs,
        )
        self.details = details or {}

    def __str__(self) -> str:
        """字符串表示，只返回消息文本。"""
        return self.message


# ============================================================================
# 工具相关异常
# ============================================================================

class ToolNotFoundError(FabricaError):
    """工具未找到异常。"""
    error_code = ErrorCode.TOOL_NOT_FOUND
    status_code = 404
    message = "工具不存在"


class ToolRegisterError(FabricaError):
    """工具注册失败异常。"""
    error_code = ErrorCode.TOOL_REGISTER_ERROR
    status_code = 400
    message = "工具注册失败"


class ToolRunError(FabricaError):
    """工具运行错误异常。"""
    error_code = ErrorCode.TOOL_RUN_ERROR
    status_code = 500
    message = "工具运行错误"


class ToolInitError(FabricaError):
    """工具初始化失败异常。"""
    error_code = ErrorCode.TOOL_INIT_ERROR
    status_code = 500
    message = "工具初始化失败"


# ============================================================================
# 任务相关异常
# ============================================================================

class TaskNotFoundError(FabricaError):
    """任务未找到异常。"""
    error_code = ErrorCode.TASK_NOT_FOUND
    status_code = 404
    message = "任务不存在"


class TaskCancelError(FabricaError):
    """任务取消失败异常。"""
    error_code = ErrorCode.TASK_CANCEL_ERROR
    status_code = 400
    message = "任务取消失败"


class TaskTimeoutError(FabricaError):
    """任务执行超时异常。"""
    error_code = ErrorCode.TASK_TIMEOUT
    status_code = 408
    message = "任务执行超时"


class TaskStateError(FabricaError):
    """任务状态异常。"""
    error_code = ErrorCode.TASK_STATE_ERROR
    status_code = 400
    message = "任务状态异常"


# ============================================================================
# 参数相关异常
# ============================================================================

class ParamInvalidError(FabricaError):
    """参数无效异常。"""
    error_code = ErrorCode.PARAM_INVALID
    status_code = 400
    message = "参数无效"


class ParamMissingError(FabricaError):
    """参数缺失异常。"""
    error_code = ErrorCode.PARAM_MISSING
    status_code = 400
    message = "参数缺失"


class ParamTypeError(FabricaError):
    """参数类型错误异常。"""
    error_code = ErrorCode.PARAM_TYPE_ERROR
    status_code = 400
    message = "参数类型错误"


class ParamValidationError(FabricaError):
    """参数校验失败异常。"""
    error_code = ErrorCode.PARAM_VALIDATION_ERROR
    status_code = 400
    message = "参数校验失败"


# ============================================================================
# 系统相关异常
# ============================================================================

class ConfigError(FabricaError):
    """配置错误异常。"""
    error_code = ErrorCode.CONFIGURATION_ERROR
    status_code = 500
    message = "配置错误"


class ServerError(FabricaError):
    """服务器错误异常。"""
    error_code = ErrorCode.SYSTEM_ERROR
    status_code = 500
    message = "服务器错误"


# ============================================================================
# 工具函数
# ============================================================================

def exception_response(exception: Exception, include_traceback: bool = False) -> Dict[str, Any]:
    """将异常转换为统一格式的响应字典。

    针对 FabricaError（及其父类 NemesisBaseException）直接读取实例属性，
    避免 nemesis 简化接口的 global_exception_handler 无法识别完整版异常类
    导致返回 UNKNOWN_ERROR/500 的问题。其他异常回退到 nemesis 原实现。

    Args:
        exception: 异常实例。
        include_traceback: 是否包含堆栈跟踪信息。

    Returns:
        统一格式的响应字典，包含 error_code/message/status_code。
    """
    if isinstance(exception, NemesisException):
        # 完整版 NemesisBaseException 直接读取属性
        response: Dict[str, Any] = {
            "error_code": exception.error_code,
            "message": exception.message,
            "status_code": exception.status_code,
        }
        if include_traceback and getattr(exception, "stacktrace", None):
            response["traceback"] = exception.stacktrace
        return response
    # 其他异常回退到 nemesis 原实现
    return _nemesis_exception_response(exception, include_traceback=include_traceback)


def safe_call(func, *args, fallback=None, on_error=None, **kwargs):
    """安全调用函数，捕获所有异常。

    包装 nemesis 的 safe_call，语义保持一致。

    Args:
        func: 要调用的函数。
        *args: 位置参数。
        fallback: 异常发生时的回退值。
        on_error: 异常处理回调函数。
        **kwargs: 关键字参数。

    Returns:
        函数执行结果或回退值。
    """
    return _nemesis_safe_call(
        func, *args, fallback=fallback, on_error=on_error, **kwargs
    )


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    # 错误码
    "ErrorCode",
    # 基础异常
    "FabricaError",
    # 工具异常
    "ToolNotFoundError",
    "ToolRegisterError",
    "ToolRunError",
    "ToolInitError",
    # 任务异常
    "TaskNotFoundError",
    "TaskCancelError",
    "TaskTimeoutError",
    "TaskStateError",
    # 参数异常
    "ParamInvalidError",
    "ParamMissingError",
    "ParamTypeError",
    "ParamValidationError",
    # 系统异常
    "ConfigError",
    "ServerError",
    # 工具函数
    "safe_call",
    "exception_response",
]