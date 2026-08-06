"""异常体系测试模块。

测试目标：fabrica/utils/exceptions.py
覆盖：ErrorCode、FabricaError、14 个子异常类、exception_response、safe_call
"""

import unittest

from fabrica.utils.exceptions import (
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
    exception_response,
    safe_call,
)
from aurora.python.nemesis import BusinessException


# ============================================================================
# ErrorCode 测试
# ============================================================================

class TestErrorCode(unittest.TestCase):
    """ErrorCode 常量测试集。"""

    def test_all_error_codes_defined(self):
        """所有 16 个错误码均应已定义。"""
        expected_codes = [
            "SYSTEM_ERROR", "CONFIGURATION_ERROR",
            "DATABASE_ERROR", "NOT_IMPLEMENTED",
            "TOOL_NOT_FOUND", "TOOL_REGISTER_ERROR",
            "TOOL_RUN_ERROR", "TOOL_INIT_ERROR",
            "TASK_NOT_FOUND", "TASK_CANCEL_ERROR",
            "TASK_TIMEOUT", "TASK_STATE_ERROR",
            "PARAM_INVALID", "PARAM_MISSING",
            "PARAM_TYPE_ERROR", "PARAM_VALIDATION_ERROR",
        ]
        for code_name in expected_codes:
            with self.subTest(code=code_name):
                self.assertTrue(hasattr(ErrorCode, code_name))
                value = getattr(ErrorCode, code_name)
                self.assertEqual(value, code_name)

    def test_error_codes_are_strings(self):
        """所有错误码均应为字符串类型。"""
        codes = [
            ErrorCode.SYSTEM_ERROR,
            ErrorCode.TOOL_NOT_FOUND,
            ErrorCode.TASK_TIMEOUT,
            ErrorCode.PARAM_INVALID,
        ]
        for code in codes:
            with self.subTest(code=code):
                self.assertIsInstance(code, str)


# ============================================================================
# FabricaError 基类测试
# ============================================================================

class TestFabricaError(unittest.TestCase):
    """FabricaError 基类测试集。"""

    def test_default_values(self):
        """默认值应正确。"""
        err = FabricaError()
        self.assertEqual(err.message, "Fabrica错误")
        self.assertEqual(err.error_code, "FABRICA_ERROR")
        self.assertEqual(err.status_code, 400)
        self.assertEqual(err.details, {})

    def test_custom_message(self):
        """自定义消息应覆盖默认值。"""
        err = FabricaError(message="自定义错误")
        self.assertEqual(err.message, "自定义错误")

    def test_custom_error_code(self):
        """自定义错误码应覆盖默认值。"""
        err = FabricaError(error_code="CUSTOM_CODE")
        self.assertEqual(err.error_code, "CUSTOM_CODE")

    def test_custom_status_code(self):
        """自定义状态码应覆盖默认值。"""
        err = FabricaError(status_code=500)
        self.assertEqual(err.status_code, 500)

    def test_with_details(self):
        """details 参数应正确存储。"""
        details = {"field": "name", "reason": "empty"}
        err = FabricaError(details=details)
        self.assertEqual(err.details, details)

    def test_str_returns_message(self):
        """__str__ 应只返回消息文本。"""
        err = FabricaError(message="测试消息")
        self.assertEqual(str(err), "测试消息")

    def test_inheritance_from_business_exception(self):
        """FabricaError 应继承 BusinessException。"""
        self.assertTrue(issubclass(FabricaError, BusinessException))


# ============================================================================
# 工具相关异常测试
# ============================================================================

class TestToolExceptions(unittest.TestCase):
    """工具相关异常测试集。"""

    def test_tool_not_found_error(self):
        """ToolNotFoundError 默认值应正确。"""
        err = ToolNotFoundError()
        self.assertEqual(err.error_code, "TOOL_NOT_FOUND")
        self.assertEqual(err.status_code, 404)
        self.assertEqual(err.message, "工具不存在")

    def test_tool_register_error(self):
        """ToolRegisterError 默认值应正确。"""
        err = ToolRegisterError()
        self.assertEqual(err.error_code, "TOOL_REGISTER_ERROR")
        self.assertEqual(err.status_code, 400)

    def test_tool_run_error(self):
        """ToolRunError 默认值应正确。"""
        err = ToolRunError()
        self.assertEqual(err.error_code, "TOOL_RUN_ERROR")
        self.assertEqual(err.status_code, 500)

    def test_tool_init_error(self):
        """ToolInitError 默认值应正确。"""
        err = ToolInitError()
        self.assertEqual(err.error_code, "TOOL_INIT_ERROR")
        self.assertEqual(err.status_code, 500)


# ============================================================================
# 任务相关异常测试
# ============================================================================

class TestTaskExceptions(unittest.TestCase):
    """任务相关异常测试集。"""

    def test_task_not_found_error(self):
        """TaskNotFoundError 默认值应正确。"""
        err = TaskNotFoundError()
        self.assertEqual(err.error_code, "TASK_NOT_FOUND")
        self.assertEqual(err.status_code, 404)

    def test_task_cancel_error(self):
        """TaskCancelError 默认值应正确。"""
        err = TaskCancelError()
        self.assertEqual(err.error_code, "TASK_CANCEL_ERROR")
        self.assertEqual(err.status_code, 400)

    def test_task_timeout_error(self):
        """TaskTimeoutError 默认值应正确。"""
        err = TaskTimeoutError()
        self.assertEqual(err.error_code, "TASK_TIMEOUT")
        self.assertEqual(err.status_code, 408)

    def test_task_state_error(self):
        """TaskStateError 默认值应正确。"""
        err = TaskStateError()
        self.assertEqual(err.error_code, "TASK_STATE_ERROR")
        self.assertEqual(err.status_code, 400)


# ============================================================================
# 参数相关异常测试
# ============================================================================

class TestParamExceptions(unittest.TestCase):
    """参数相关异常测试集。"""

    def test_param_invalid_error(self):
        """ParamInvalidError 默认值应正确。"""
        err = ParamInvalidError()
        self.assertEqual(err.error_code, "PARAM_INVALID")
        self.assertEqual(err.status_code, 400)

    def test_param_missing_error(self):
        """ParamMissingError 默认值应正确。"""
        err = ParamMissingError()
        self.assertEqual(err.error_code, "PARAM_MISSING")
        self.assertEqual(err.status_code, 400)

    def test_param_type_error(self):
        """ParamTypeError 默认值应正确。"""
        err = ParamTypeError()
        self.assertEqual(err.error_code, "PARAM_TYPE_ERROR")
        self.assertEqual(err.status_code, 400)

    def test_param_validation_error(self):
        """ParamValidationError 默认值应正确。"""
        err = ParamValidationError()
        self.assertEqual(err.error_code, "PARAM_VALIDATION_ERROR")
        self.assertEqual(err.status_code, 400)


# ============================================================================
# 系统相关异常测试
# ============================================================================

class TestSystemExceptions(unittest.TestCase):
    """系统相关异常测试集。"""

    def test_config_error(self):
        """ConfigError 默认值应正确。"""
        err = ConfigError()
        self.assertEqual(err.error_code, "CONFIGURATION_ERROR")
        self.assertEqual(err.status_code, 500)

    def test_server_error(self):
        """ServerError 默认值应正确。"""
        err = ServerError()
        self.assertEqual(err.error_code, "SYSTEM_ERROR")
        self.assertEqual(err.status_code, 500)


# ============================================================================
# exception_response 测试
# ============================================================================

class TestExceptionResponse(unittest.TestCase):
    """exception_response 函数测试集。"""

    def test_response_for_fabrica_error(self):
        """FabricaError 应返回正确的响应字典。"""
        err = ParamInvalidError("参数无效")
        resp = exception_response(err)
        self.assertEqual(resp["error_code"], "PARAM_INVALID")
        self.assertEqual(resp["message"], "参数无效")
        self.assertEqual(resp["status_code"], 400)

    def test_response_with_traceback(self):
        """include_traceback=True 时应包含堆栈信息（如果有）。"""
        err = ToolNotFoundError("工具不存在")
        resp = exception_response(err, include_traceback=True)
        self.assertEqual(resp["error_code"], "TOOL_NOT_FOUND")
        # stacktrace 仅在异常有 cause 时存在，此处可能不包含
        self.assertIn("message", resp)

    def test_response_for_generic_exception(self):
        """非 FabricaError 异常应回退到 nemesis 原实现。"""
        err = ValueError("普通错误")
        resp = exception_response(err)
        self.assertIn("error_code", resp)
        self.assertIn("message", resp)
        self.assertIn("status_code", resp)


# ============================================================================
# safe_call 测试
# ============================================================================

class TestSafeCall(unittest.TestCase):
    """safe_call 函数测试集。"""

    def test_safe_call_normal(self):
        """正常调用应返回函数结果。"""

        def add(a, b):
            return a + b

        result = safe_call(add, 1, 2, fallback=0)
        self.assertEqual(result, 3)

    def test_safe_call_with_fallback(self):
        """异常时应返回 fallback 值。"""

        def raise_error():
            raise ValueError("test")

        result = safe_call(raise_error, fallback="default")
        self.assertEqual(result, "default")

    def test_safe_call_with_on_error(self):
        """异常时应调用 on_error 回调。"""
        called_with = []

        def risky():
            raise RuntimeError("boom")

        def on_error(exc, *args, **kwargs):
            called_with.append(str(exc))
            return "recovered"

        result = safe_call(risky, on_error=on_error)
        self.assertEqual(result, "recovered")
        self.assertEqual(len(called_with), 1)


if __name__ == "__main__":
    unittest.main()
