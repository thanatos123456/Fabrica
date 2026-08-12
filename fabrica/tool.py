#!/usr/bin/env python3
"""Fabrica 平台核心模块（ToolBase + ParamDef + TaskContext 部分）。

定义所有工具插件必须遵循的统一接口规范，
以及参数定义系统、校验规则引擎和执行上下文。

生命周期：
    on_init()       —— 工具实例化后的初始化钩子
    validate(params) —— 执行前参数校验
    run(params, ctx) —— 主执行逻辑
    on_cancel()     —— 取消回调（可选）
    on_complete(result) —— 完成回调（可选）

参数定义：
    ParamDef        —— 参数定义数据类（内部使用）
    ParamDefSchema  —— Pydantic 模型（API 序列化）
    validate_param  —— 校验规则引擎（6 种规则）

执行上下文：
    TaskContext     —— 工具执行时的运行环境
        report_progress —— 进度报告
        log             —— 日志输出
        cancelled       —— 取消信号检查
        get_data_dir    —— 工具持久化数据目录

任务状态机：
    TaskStatus      —— 任务状态枚举（8 状态）
    TaskStateMachine —— 任务状态机，管理状态流转
        transition     —— 尝试状态转换，非法返回 False
        update_progress —— 更新进度
        to_summary     —— 返回 TaskSummary
        to_detail      —— 返回 TaskDetail

工具注册中心：
    ToolRegistry    —— 集中管理工具注册、发现、实例化和任务执行
        register     —— 装饰器注册工具类
        discover     —— 自动扫描目录发现工具
        run_tool     —— 提交任务执行（返回 task_id）
        cancel_task  —— 取消任务
        get_task     —— 获取任务详情
        list_tools   —— 列出已注册工具
        资源池管理    —— 基于 hestia 统一调度 CPU 密集型工具
            init_pool —— 应用启动时初始化资源池
            shutdown —— 应用关闭时优雅释放资源池
            get_pool —— 懒加载获取资源池
    tool            —— 全局单例 ToolRegistry 实例

用法：
    from fabrica.tool import ToolBase, ParamDef, TaskContext, tool

    class MyTool(ToolBase):
        name = "my_tool"
        params = [
            ParamDef(key="threshold", type="float",
                     validation={"min": 0, "max": 1}),
        ]

        async def on_init(self): ...
        async def validate(self, params): ...
        async def run(self, params, ctx):
            ctx.report_progress(50, "处理中")
            return {"result": "ok"}
"""

import asyncio
import importlib
import json
import os
import re
import sys
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field

from aurora.python.hestia import PoolConfig, ResourcePool
from fabrica.utils.exceptions import TaskTimeoutError
from fabrica.utils.helpers import PathUtils
from fabrica.utils.logger import logger


# ============================================================================
# 路径常量
# ============================================================================

# 任务历史 JSON 文件路径（兼容 PyInstaller 打包：exe 同级 data 目录）
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _FABRICA_DIR = os.path.dirname(sys.executable)
else:
    _FABRICA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK_HISTORY_PATH = os.path.join(_FABRICA_DIR, "data", "tasks.json")


# ============================================================================
# 参数类型枚举
# ============================================================================

class ParamType(str, Enum):
    """参数类型枚举。

    前端据此渲染对应的表单控件。
    继承 str, Enum 使枚举值可直接作为字符串使用。
    """

    STRING = "str"              # 字符串输入框
    INTEGER = "int"             # 整数输入框
    FLOAT = "float"             # 浮点数输入框
    BOOLEAN = "bool"            # 开关控件
    PATH = "path"               # 路径输入框
    FILE = "file"               # 文件选择器
    DIRECTORY = "dir"           # 目录选择器
    SELECT = "select"           # 下拉单选
    MULTI_SELECT = "multi_select"  # 下拉多选
    PASSWORD = "password"       # 密码输入框


# ============================================================================
# ParamDef 参数定义数据类
# ============================================================================

@dataclass
class ParamDef:
    """参数定义数据类。

    描述工具参数的元信息，前端据此自动渲染表单控件。
    使用 dataclass 实现，轻量且易于内部使用。

    Attributes:
        key: 参数键名（唯一标识）
        label: 显示标签
        type: 参数类型（见 ParamType 枚举）
        default: 默认值
        required: 是否必填
        description: 描述说明
        placeholder: 输入框占位文本
        options: 选项列表（select/multi_select 类型使用）
        validation: 校验规则字典（见 validate_param 支持的规则）
    """

    key: str
    label: str = ""
    type: str = "str"
    default: Any = None
    required: bool = False
    description: str = ""
    placeholder: str = ""
    options: List[Any] = field(default_factory=list)
    validation: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ParamDefSchema Pydantic 模型（API 序列化）
# ============================================================================

class ParamDefSchema(BaseModel):
    """参数定义 Pydantic 模型（用于 API 序列化）。

    镜像 ParamDef 字段，用于 API 请求/响应的序列化与反序列化。
    """

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(description="参数键名")
    label: str = Field(default="", description="显示标签")
    type: str = Field(default="str", description="参数类型")
    default: Any = Field(default=None, description="默认值")
    required: bool = Field(default=False, description="是否必填")
    description: str = Field(default="", description="描述说明")
    placeholder: str = Field(default="", description="输入框占位文本")
    options: List[Any] = Field(
        default_factory=list, description="选项列表"
    )
    validation: Dict[str, Any] = Field(
        default_factory=dict, description="校验规则字典"
    )

    @classmethod
    def from_param_def(cls, param_def: ParamDef) -> "ParamDefSchema":
        """从 ParamDef 数据类创建 Pydantic 模型实例。

        Args:
            param_def: ParamDef 数据类实例

        Returns:
            ParamDefSchema 实例
        """
        return cls(
            key=param_def.key,
            label=param_def.label,
            type=param_def.type,
            default=param_def.default,
            required=param_def.required,
            description=param_def.description,
            placeholder=param_def.placeholder,
            options=list(param_def.options),
            validation=dict(param_def.validation),
        )


# ============================================================================
# 校验规则引擎
# ============================================================================

def validate_param(value: Any, param_def: ParamDef) -> List[str]:
    """校验参数值是否符合参数定义的规则。

    支持 6 种校验规则：
        min: 数值最小值
        max: 数值最大值
        min_length: 字符串最小长度
        max_length: 字符串最大长度
        pattern: 正则匹配
        file_extensions: 文件扩展名白名单

    Args:
        value: 待校验的值
        param_def: 参数定义实例

    Returns:
        错误消息列表，空列表表示校验通过
    """
    errors: List[str] = []

    # None 值跳过所有校验（required 检查由调用方处理）
    if value is None:
        return errors

    rules = param_def.validation
    if not rules:
        return errors

    # ---- 数值校验：min / max ----
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in rules and value < rules["min"]:
            errors.append(f"低于最小值 {rules['min']}")
        if "max" in rules and value > rules["max"]:
            errors.append(f"超过最大值 {rules['max']}")

    # ---- 字符串校验：min_length / max_length / pattern ----
    if isinstance(value, str):
        if "min_length" in rules and len(value) < rules["min_length"]:
            errors.append(f"长度低于最小值 {rules['min_length']}")
        if "max_length" in rules and len(value) > rules["max_length"]:
            errors.append(f"长度超过最大值 {rules['max_length']}")
        if "pattern" in rules:
            pattern = rules["pattern"]
            if not re.match(pattern, value):
                errors.append(f"格式不匹配 {pattern}")

    # ---- 文件扩展名校验：file_extensions ----
    if "file_extensions" in rules and isinstance(value, str):
        # 提取文件扩展名（不含点号，小写）
        ext = value.rsplit(".", 1)[-1].lower() if "." in value else ""
        allowed = [
            e.lower().lstrip(".") for e in rules["file_extensions"]
        ]
        if ext not in allowed:
            errors.append(
                f"文件扩展名不允许，仅支持 {', '.join(allowed)}"
            )

    return errors


# ============================================================================
# ToolBase 抽象基类
# ============================================================================

class ToolBase(ABC):
    """工具插件抽象基类。

    所有 Fabrica 工具必须继承此类并实现抽象方法。
    子类通过覆盖类属性提供工具元信息，
    通过实现抽象方法定义工具行为。

    类属性:
        name: 工具唯一标识（字符串，子类必须覆盖）
        title: 工具显示名称
        description: 工具描述说明
        icon: 工具图标（图标名或 URL）
        params: 工具参数定义列表（List[ParamDef]）
        version: 工具版本号
        category: 工具分类标签
    """

    # ---- 类属性：工具元信息 ----
    name: Optional[str] = None
    title: Optional[str] = None
    description: str = ""
    icon: Optional[str] = None
    params: List["ParamDef"] = []
    version: str = "1.0.0"
    category: str = "misc"
    cpu_intensive: bool = False   # 是否 CPU 密集型（True 时提交线程池执行）

    # ---- 抽象方法：子类必须实现 ----

    @abstractmethod
    async def on_init(self) -> None:
        """初始化钩子。

        在工具实例化后、首次执行前调用。
        子类可在此执行资源加载、连接建立等初始化操作。

        Raises:
            ToolInitError: 初始化失败时应抛出（由子类决定）
        """

    @abstractmethod
    async def validate(self, params: Dict[str, Any]) -> None:
        """参数校验。

        在 run() 执行前调用，校验用户传入的参数。
        校验失败时应抛出 ParamInvalidError 等异常。

        Args:
            params: 用户传入的参数字典

        Raises:
            ParamInvalidError: 参数无效时
            ParamMissingError: 必填参数缺失时
        """

    @abstractmethod
    async def run(
        self,
        params: Dict[str, Any],
        ctx: Any,
    ) -> Any:
        """主执行逻辑。

        工具的核心业务逻辑，接收参数和执行上下文，
        返回执行结果。

        Args:
            params: 用户传入的参数字典
            ctx: 任务执行上下文（T2.3 实现 TaskContext）

        Returns:
            工具执行结果（类型由子类决定）

        Raises:
            ToolRunError: 执行失败时
        """

    # ---- 可选方法：子类可覆盖 ----

    async def on_cancel(self) -> None:
        """取消回调。

        当任务被取消时调用。子类可覆盖此方法
        执行资源清理、状态回滚等操作。
        默认实现为空操作。
        """

    async def on_complete(self, result: Any) -> None:
        """完成回调。

        当 run() 成功完成后调用。子类可覆盖此方法
        执行结果后处理、日志记录等操作。

        Args:
            result: run() 的返回值
        """


# ============================================================================
# TaskContext 执行上下文
# ============================================================================

@dataclass
class TaskContext:
    """工具执行上下文。

    封装工具执行时的运行环境，提供进度报告、日志输出、
    取消信号检查和持久化数据目录等功能。

    通过事件和回调机制与 ToolRegistry 解耦：
    - 取消信号使用 asyncio.Event 实现
    - 进度/日志通过回调函数上报，不直接依赖 ToolRegistry

    Attributes:
        task_id: 任务唯一标识。
        params: 任务参数。
        temp_dir: 临时目录路径。
        tool_name: 工具名称（用于 get_data_dir）。
        data_dir: 数据根目录，为 None 时使用默认 "data/tools"。
    """

    # ---- 公开字段 ----
    task_id: str
    params: Dict[str, Any]
    temp_dir: str
    tool_name: str = ""
    data_dir: Optional[str] = None

    # ---- 内部字段（回调与取消信号） ----
    _progress_callback: Optional[Callable[[int, str], None]] = field(
        default=None, repr=False
    )
    _log_callback: Optional[Callable[[str, str], None]] = field(
        default=None, repr=False
    )
    _cancel_event: asyncio.Event = field(
        default_factory=asyncio.Event, repr=False
    )

    @property
    def cancelled(self) -> bool:
        """检查取消信号是否已触发。

        Returns:
            True 表示任务已被取消，否则 False。
        """
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        """触发取消信号。

        设置 asyncio.Event，供工具在 run() 中轮询
        `cancelled` 属性判断是否应中止执行。
        """
        self._cancel_event.set()

    def report_progress(self, percent: int, message: str = "", stage: str = "") -> None:
        """报告执行进度。

        调用进度回调（若已设置），将进度和消息上报给
        ToolRegistry 或上层调用方。

        Args:
            percent: 进度百分比（0-100，当前阶段内）。
            message: 进度消息描述。
            stage: 当前阶段名称。
        """
        if self._progress_callback is not None:
            self._progress_callback(percent, message, stage)

    def log(self, level: str, message: str) -> None:
        """记录执行日志。

        调用日志回调（若已设置），将日志级别和消息上报。

        Args:
            level: 日志级别（如 "info"/"error"/"debug"）。
            message: 日志消息。
        """
        if self._log_callback is not None:
            self._log_callback(level, message)

    def get_data_dir(self) -> str:
        """获取工具持久化数据目录。

        返回 `<data_dir>/<tool_name>` 路径，目录不存在时自动创建。
        若 tool_name 为空，仅确保数据根目录存在。

        Returns:
            工具数据目录绝对路径。
        """
        base = self.data_dir or "data/tools"
        if self.tool_name:
            return PathUtils.get_data_dir(base, self.tool_name)
        return PathUtils.ensure_dir(base)


# ============================================================================
# 任务状态机
# ============================================================================

class TaskStatus(str, Enum):
    """任务状态枚举。

    描述任务执行实例的各个生命周期状态。
    继承 str, Enum 使枚举值可直接作为字符串使用。
    """

    PENDING = "pending"         # 任务创建，等待调度
    VALIDATING = "validating"   # 参数校验中
    VALID = "valid"             # 参数校验通过
    INVALID = "invalid"         # 参数校验失败
    RUNNING = "running"         # 执行中
    COMPLETED = "completed"     # 执行成功完成
    FAILED = "failed"           # 执行异常终止
    CANCELLED = "cancelled"     # 用户取消


# 终态集合：进入这些状态后不可再转换
_TERMINAL_STATUSES = {
    TaskStatus.INVALID,
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


class TaskSummary(BaseModel):
    """任务摘要模型（API 序列化）。

    描述任务的核心摘要信息，用于任务列表展示。
    """

    task_id: str = Field(description="任务唯一标识")
    tool_name: str = Field(description="工具名称")
    status: str = Field(description="任务状态")
    progress: float = Field(default=0.0, description="进度百分比 0-100")
    created_at: datetime = Field(description="任务创建时间")
    completed_at: Optional[datetime] = Field(
        default=None, description="任务完成时间"
    )


class TaskDetail(TaskSummary):
    """任务详情模型（API 序列化）。

    继承 TaskSummary，追加执行参数、结果、错误和日志信息。
    """

    params: Dict[str, Any] = Field(description="执行参数快照")
    result: Optional[Dict[str, Any]] = Field(
        default=None, description="执行结果"
    )
    error: Optional[str] = Field(default=None, description="错误信息")
    logs: List[Any] = Field(default_factory=list, description="执行日志")


class TaskStateMachine:
    """任务状态机。

    管理单个任务执行实例的状态流转，确保状态转换合法，
    提供状态查询和进度更新能力。

    状态转换矩阵（终态不可再转换）：
        PENDING -> VALIDATING
        VALIDATING -> VALID / INVALID
        VALID -> RUNNING
        RUNNING -> COMPLETED / FAILED / CANCELLED
    """

    def __init__(
        self,
        task_id: str,
        tool_name: str,
        params: Dict[str, Any],
    ) -> None:
        """初始化任务状态机。

        Args:
            task_id: 任务唯一标识。
            tool_name: 工具名称。
            params: 执行参数。
        """
        self.task_id = task_id
        self.tool_name = tool_name
        self.params = params
        self._status = TaskStatus.PENDING
        self._result: Optional[Dict[str, Any]] = None
        self._error: Optional[str] = None
        self._progress: float = 0.0
        self._logs: List[Dict[str, Any]] = []
        self._created_at = datetime.now()
        self._completed_at: Optional[datetime] = None
        self._cancel_event = asyncio.Event()

    @property
    def status(self) -> TaskStatus:
        """当前状态。"""
        return self._status

    @property
    def progress(self) -> float:
        """当前进度（0-100）。"""
        return self._progress

    @property
    def cancelled(self) -> bool:
        """任务是否被取消。

        Returns:
            True 表示任务已被取消，否则 False。
        """
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        """触发取消信号。

        设置 asyncio.Event，供后台执行协程检查
        `cancelled` 属性判断是否应中止执行。
        """
        self._cancel_event.set()

    def transition(self, new_status: TaskStatus) -> bool:
        """尝试状态转换。

        校验目标状态是否为当前状态的合法下一状态。
        合法则更新状态并返回 True，非法返回 False。

        Args:
            new_status: 目标状态。

        Returns:
            True 表示转换成功，False 表示转换非法。
        """
        if new_status in self._valid_transitions(self._status):
            self._status = new_status
            # 进入终态时记录完成时间
            if new_status in _TERMINAL_STATUSES:
                self._completed_at = datetime.now()
            return True
        return False

    def update_progress(self, percent: float) -> None:
        """更新进度。

        Args:
            percent: 进度百分比（0-100）。
        """
        self._progress = percent

    def append_log(self, level: str, message: str) -> None:
        """追加执行日志。

        记录日志级别、消息与时间戳，供任务详情页面展示。

        Args:
            level: 日志级别（如 "info"/"error"/"debug"）。
            message: 日志消息。
        """
        self._logs.append({
            "level": level,
            "message": message,
            "timestamp": datetime.now(),
        })

    @staticmethod
    def _valid_transitions(current: TaskStatus) -> set:
        """返回当前状态的所有合法下一状态。

        Args:
            current: 当前状态。

        Returns:
            合法下一状态集合。终态返回空集合。
        """
        _transitions = {
            TaskStatus.PENDING: {TaskStatus.VALIDATING},
            TaskStatus.VALIDATING: {TaskStatus.VALID, TaskStatus.INVALID},
            TaskStatus.VALID: {TaskStatus.RUNNING},
            TaskStatus.RUNNING: {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            },
        }
        return _transitions.get(current, set())

    def to_summary(self) -> TaskSummary:
        """转换为任务摘要。

        Returns:
            TaskSummary 实例。
        """
        return TaskSummary(
            task_id=self.task_id,
            tool_name=self.tool_name,
            status=self._status.value,
            progress=self._progress,
            created_at=self._created_at,
            completed_at=self._completed_at,
        )

    def to_detail(self) -> TaskDetail:
        """转换为任务详情。

        Returns:
            TaskDetail 实例。
        """
        return TaskDetail(
            **self.to_summary().model_dump(),
            params=self.params,
            result=self._result,
            error=self._error,
            logs=self._logs,
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为可 JSON 序列化的字典（用于任务历史持久化）。

        datetime 字段转为 ISO 字符串，便于 json 序列化。

        Returns:
            任务状态与结果的字典表示。
        """
        return {
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "params": self.params,
            "status": self._status.value,
            "progress": self._progress,
            "created_at": self._created_at.isoformat(),
            "completed_at": (
                self._completed_at.isoformat()
                if self._completed_at else None
            ),
            "result": self._result,
            "error": self._error,
            "logs": [
                {
                    "level": log["level"],
                    "message": log["message"],
                    "timestamp": log["timestamp"].isoformat(),
                }
                for log in self._logs
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskStateMachine":
        """从字典重建任务状态机（用于启动时加载任务历史）。

        Args:
            data: to_dict() 生成的字典。

        Returns:
            重建的任务状态机实例。
        """
        sm = cls(
            task_id=data["task_id"],
            tool_name=data["tool_name"],
            params=data.get("params", {}),
        )
        sm._status = TaskStatus(data["status"])
        sm._progress = data.get("progress", 0.0)
        sm._created_at = datetime.fromisoformat(data["created_at"])
        completed = data.get("completed_at")
        sm._completed_at = (
            datetime.fromisoformat(completed) if completed else None
        )
        sm._result = data.get("result")
        sm._error = data.get("error")
        sm._logs = [
            {
                "level": log.get("level"),
                "message": log.get("message"),
                "timestamp": datetime.fromisoformat(log["timestamp"]),
            }
            for log in data.get("logs", [])
        ]
        return sm


# ============================================================================
# 工具注册中心
# ============================================================================

class ToolMeta(BaseModel):
    """工具元信息模型（API 序列化）。

    描述工具的核心元信息，用于工具列表展示。
    """

    name: str = Field(description="工具唯一标识")
    title: str = Field(description="工具显示名称")
    description: str = Field(description="工具描述")
    icon: str = Field(description="工具图标")
    version: str = Field(description="工具版本号")
    category: str = Field(description="工具分类标签")


class ToolRegistry:
    """工具注册中心（单例模式）。

    集中管理所有工具类的注册、发现和实例化，提供工具列表、
    参数 Schema、任务执行等统一入口。

    单例模式：通过 __new__ 保证全局唯一实例。
    注册先于查询，注册阶段与查询阶段在时序上不重叠。
    """

    _instance = None

    def __new__(cls):
        """创建单例实例（首次调用时初始化内部状态）。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._instances = {}
            cls._instance._tool_dirs = []
            cls._instance._tasks = {}
            cls._instance._callbacks = {}
            cls._instance._on_init_done = set()
            cls._instance._initialized = False
            cls._instance._pool = None   # hestia 资源池实例（懒加载）
            # 工具发现完成事件：后台线程完成重库导入后置位，
            # 供 run_tool / list_tools 在首次使用时等待。
            cls._instance._discovery_done = threading.Event()
            # 是否已发起工具发现（用于决定 run_tool/list_tools 是否需等待）
            cls._instance._discovery_started = False
            # 任务历史持久化：文件路径 + 是否已从磁盘加载
            cls._instance._history_path = TASK_HISTORY_PATH
            cls._instance._history_loaded = False
        return cls._instance

    # ------------------------------------------------------------------
    # 注册与发现
    # ------------------------------------------------------------------

    def register(self, cls: type) -> type:
        """注册工具类（装饰器/直接调用）。

        工具类必须具有 name 属性，且不能重复注册。

        Args:
            cls: 工具类（继承 ToolBase）。

        Returns:
            原工具类（便于装饰器使用）。

        Raises:
            ValueError: name 缺失或工具已注册。
        """
        name = getattr(cls, "name", None)
        if name is None:
            raise ValueError(f"Tool class {cls.__name__} must have a 'name' attribute")
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = cls
        return cls

    def discover(self, tool_dirs: Optional[List] = None) -> int:
        """自动扫描目录，发现并注册工具。

        扫描指定目录下的子包（含 __init__.py），动态导入。
        导入过程中工具类通过 @tool.register 自动注册。

        Args:
            tool_dirs: 扫描目录列表。为 None 时沿用已设置的目录。

        Returns:
            成功导入的工具包数量。
        """
        if tool_dirs is not None:
            self._tool_dirs = [Path(d) for d in tool_dirs]
        self._discovery_started = True
        count = 0
        for tool_dir in self._tool_dirs:
            if not tool_dir.exists():
                continue
            for entry in tool_dir.iterdir():
                if entry.is_dir() and (entry / "__init__.py").exists():
                    try:
                        importlib.import_module(f"fabrica.tools.{entry.name}")
                        count += 1
                    except Exception as e:
                        logger.warning("加载工具 %s 失败: %s", entry.name, e)
        self._initialized = True
        self._discovery_done.set()
        return count

    def notify_ready(self) -> None:
        """标记工具发现已完成（后台发现线程调用）。

        用于在窗口先显示、重库导入后置完成时，唤醒
        等待中的 run_tool / list_tools。
        """
        self._discovery_done.set()

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        """等待工具发现完成（阻塞，通常由后台线程很快完成）。

        Args:
            timeout: 最长等待秒数；None 表示无限等待。

        Returns:
            发现是否已完成。
        """
        return self._discovery_done.wait(timeout=timeout)

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> "ToolBase":
        """获取工具实例（懒加载）。

        首次调用时创建实例并缓存。on_init() 在后台执行时调用。

        Args:
            name: 工具名称。

        Returns:
            工具实例。

        Raises:
            KeyError: 工具未注册。
        """
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        if name not in self._instances:
            self._instances[name] = self._tools[name]()
        return self._instances[name]

    def list_tools(self) -> List[ToolMeta]:
        """列出所有已注册工具的元信息。

        Returns:
            工具元信息列表。
        """
        # 等待后台发现完成，避免前台拿到空列表（仅在已发起发现时阻塞）
        if self._discovery_started:
            self._discovery_done.wait(timeout=60.0)
        return [self.get_tool_meta(name) for name in self._tools]

    def get_schema(self, name: str) -> List[ParamDef]:
        """获取工具的参数定义列表。

        Args:
            name: 工具名称。

        Returns:
            参数定义列表。

        Raises:
            KeyError: 工具未注册。
        """
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        return list(self._tools[name].params)

    def get_tool_meta(self, name: str) -> ToolMeta:
        """获取工具元信息。

        Args:
            name: 工具名称。

        Returns:
            工具元信息。

        Raises:
            KeyError: 工具未注册。
        """
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        cls = self._tools[name]
        return ToolMeta(
            name=cls.name,
            title=cls.title,
            description=cls.description,
            icon=cls.icon,
            version=cls.version,
            category=cls.category,
        )

    # ------------------------------------------------------------------
    # 任务执行
    # ------------------------------------------------------------------

    def run_tool(self, name: str, params: Dict[str, Any], cb: Optional[Dict] = None) -> str:
        """提交工具执行请求。

        创建任务状态机并后台异步执行，立即返回 task_id。

        Args:
            name: 工具名称。
            params: 执行参数。
            cb: 可选回调字典，格式如 {"progress": cb, "log": cb, ...}。

        Returns:
            任务唯一标识 task_id。

        Raises:
            KeyError: 工具未注册。
        """
        # 等待后台发现完成，确保工具已注册（仅在已发起发现时阻塞，测试直接
        # register 的场景不等待，避免无谓挂起）
        if self._discovery_started:
            self._discovery_done.wait(timeout=60.0)
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        task_id = str(uuid.uuid4())
        sm = TaskStateMachine(task_id, name, dict(params))
        self._tasks[task_id] = sm
        if cb:
            self._callbacks[task_id] = dict(cb)
        loop = asyncio.get_event_loop()
        loop.create_task(self._execute_tool(task_id, name, dict(params)))
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """取消运行中的任务。

        Args:
            task_id: 任务唯一标识。

        Returns:
            True 表示任务存在且已触发取消信号，False 表示任务不存在。
        """
        sm = self._tasks.get(task_id)
        if sm is None:
            return False
        sm.cancel()
        return True

    def get_task(self, task_id: str) -> TaskDetail:
        """获取任务状态和结果。

        Args:
            task_id: 任务唯一标识。

        Returns:
            任务详情。

        Raises:
            KeyError: 任务不存在。
        """
        self._ensure_history_loaded()
        sm = self._tasks.get(task_id)
        if sm is None:
            raise KeyError(f"Task '{task_id}' not found")
        return sm.to_detail()

    def list_tasks(self) -> List[TaskSummary]:
        """获取所有任务摘要列表。

        首次调用时先从磁盘加载持久化历史。

        Returns:
            任务摘要列表。
        """
        self._ensure_history_loaded()
        return [sm.to_summary() for sm in self._tasks.values()]

    def delete_task(self, task_id: str) -> bool:
        """删除任务记录。

        从注册中心移除任务状态机及其关联回调，并同步更新磁盘历史。

        Args:
            task_id: 任务唯一标识。

        Returns:
            True 表示删除成功，False 表示任务不存在。
        """
        if task_id not in self._tasks:
            return False
        sm = self._tasks[task_id]
        del self._tasks[task_id]
        self._callbacks.pop(task_id, None)
        self._save_tasks()
        self._cleanup_task_artifacts(sm)
        return True

    def _cleanup_task_artifacts(self, sm: "TaskStateMachine") -> None:
        """删除被删任务引用且不再被任何任务引用的磁盘产物。

        委托给工具自带的 cleanup_task 钩子执行（引用计数），
        异常仅记告警，不阻断任务删除。

        Args:
            sm: 被删除任务的状态机实例。
        """
        if sm.tool_name not in self._tools:
            return
        tool = self.get_tool(sm.tool_name)
        if not hasattr(tool, "cleanup_task"):
            return
        referenced = self._collect_referenced_ids(sm.tool_name)
        try:
            tool.cleanup_task(sm._result, referenced)
        except Exception as exc:  # noqa: BLE001
            logger.warning("任务产物清理失败: %s", exc)

    def _collect_referenced_ids(self, tool_name: str) -> Set[str]:
        """汇总所有同工具任务（含历史）当前引用的产物键集合。

        用于引用计数：仅删除不在该集合中的孤儿产物。

        Args:
            tool_name: 工具名。

        Returns:
            产物键（如 video_id 的 md5 散列）集合。
        """
        referenced: Set[str] = set()
        if tool_name not in self._tools:
            return referenced
        tool = self.get_tool(tool_name)
        extract = getattr(tool, "extract_refs", None)
        if extract is None:
            return referenced
        for sm in self._tasks.values():
            if sm.tool_name == tool_name:
                referenced |= set(extract(sm._result) or set())
        return referenced

    def _collect_referenced_outputs(self, tool_name: str) -> Set[str]:
        """汇总所有同工具任务当前引用的输出报告路径集合。

        用于全局清理时避免误删仍被任务引用的报告。

        Args:
            tool_name: 工具名。

        Returns:
            输出报告绝对路径集合。
        """
        referenced: Set[str] = set()
        if tool_name not in self._tools:
            return referenced
        tool = self.get_tool(tool_name)
        extract = getattr(tool, "extract_outputs", None)
        if extract is None:
            return referenced
        for sm in self._tasks.values():
            if sm.tool_name == tool_name:
                referenced |= set(extract(sm._result) or set())
        return referenced

    def cleanup_orphans(self) -> Dict[str, int]:
        """清理所有不再被任何任务引用的中间产物（全局入口）。

        遍历具备清理能力的工具，汇总其清理计数。

        Returns:
            {"keyframes": int, "features": int, "output": int} 计数。
        """
        self._ensure_history_loaded()
        totals: Dict[str, int] = {
            "keyframes": 0, "features": 0, "output": 0,
        }
        seen: Set[str] = set()
        for sm in self._tasks.values():
            if sm.tool_name not in self._tools:
                continue
            tool = self.get_tool(sm.tool_name)
            if not hasattr(tool, "cleanup_orphans"):
                continue
            if tool.name in seen:
                continue
            seen.add(tool.name)
            referenced = self._collect_referenced_ids(sm.tool_name)
            referenced_outputs = self._collect_referenced_outputs(sm.tool_name)
            try:
                counts = tool.cleanup_orphans(
                    referenced, referenced_outputs
                ) or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("全局产物清理失败: %s", exc)
                continue
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
        return totals

    # ------------------------------------------------------------------
    # 回调注册与注销
    # ------------------------------------------------------------------

    def register_progress_callback(self, task_id: str, cb: Callable) -> None:
        """注册进度回调。"""
        self._callbacks.setdefault(task_id, {})["progress"] = cb

    def register_log_callback(self, task_id: str, cb: Callable) -> None:
        """注册日志回调。"""
        self._callbacks.setdefault(task_id, {})["log"] = cb

    def register_complete_callback(self, task_id: str, cb: Callable) -> None:
        """注册完成回调。"""
        self._callbacks.setdefault(task_id, {})["complete"] = cb

    def register_error_callback(self, task_id: str, cb: Callable) -> None:
        """注册错误回调。"""
        self._callbacks.setdefault(task_id, {})["error"] = cb

    def unregister_progress_callback(self, task_id: str) -> None:
        """注销进度回调。"""
        self._callbacks.get(task_id, {}).pop("progress", None)

    def unregister_log_callback(self, task_id: str) -> None:
        """注销日志回调。"""
        self._callbacks.get(task_id, {}).pop("log", None)

    def unregister_complete_callback(self, task_id: str) -> None:
        """注销完成回调。"""
        self._callbacks.get(task_id, {}).pop("complete", None)

    def unregister_error_callback(self, task_id: str) -> None:
        """注销错误回调。"""
        self._callbacks.get(task_id, {}).pop("error", None)

    # ------------------------------------------------------------------
    # 任务历史持久化
    # ------------------------------------------------------------------

    def _ensure_history_loaded(self) -> None:
        """首次访问任务历史时从磁盘加载（仅执行一次）。

        启动后首次调用 list_tasks/get_task 时触发，将持久化的
        终态任务恢复进内存，使历史跨重启保留。
        """
        if self._history_loaded:
            return
        self._history_loaded = True
        self._load_tasks()

    def _load_tasks(self) -> None:
        """从磁盘 JSON 文件加载任务历史到内存。

        单个记录损坏时跳过并记录告警，不影响其余任务加载。
        """
        if self._history_path is None or not os.path.exists(
            self._history_path
        ):
            return
        try:
            with open(self._history_path, encoding="utf-8") as fh:
                data = json.load(fh)
            for item in data:
                try:
                    sm = TaskStateMachine.from_dict(item)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("跳过损坏的任务历史记录: %s", exc)
                    continue
                self._tasks[sm.task_id] = sm
            logger.info("已从磁盘加载 %d 条任务历史", len(data))
        except Exception as exc:  # noqa: BLE001
            logger.warning("任务历史加载失败: %s", exc)

    def _save_tasks(self) -> None:
        """将终态任务历史原子写入磁盘 JSON 文件。

        仅持久化终态任务（completed/failed/cancelled/invalid），
        写临时文件后 os.replace 原子替换，避免进程被杀损坏文件。
        """
        if self._history_path is None:
            return
        try:
            os.makedirs(
                os.path.dirname(self._history_path), exist_ok=True
            )
            data = [
                sm.to_dict()
                for sm in self._tasks.values()
                if sm.status in _TERMINAL_STATUSES
            ]
            tmp = self._history_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._history_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("任务历史持久化失败: %s", exc)

    # ------------------------------------------------------------------
    # 资源池管理（hestia）
    # ------------------------------------------------------------------

    def init_pool(self, config: Optional[PoolConfig] = None) -> None:
        """初始化 hestia 资源池（应用启动时调用）。

        默认配置：线程池，最大并发 2，任务超时 3600 秒。
        已存在资源池时先优雅关闭再重建。

        Args:
            config: 资源池配置，为 None 时使用默认配置。
        """
        if self._pool is not None:
            self._pool.shutdown()
        if config is None:
            config = PoolConfig(
                pool_type="thread",
                max_size=2,
                task_timeout=None,
            )
        self._pool = ResourcePool(logger, config)
        logger.info(
            "hestia 资源池已初始化: type=%s, max_size=%s, task_timeout=%s"
            % (config.pool_type, config.max_size, config.task_timeout)
        )

    def shutdown(self) -> None:
        """优雅关闭资源池（应用关闭时调用）。"""
        if self._pool is not None:
            self._pool.shutdown()
            self._pool = None
            logger.info("hestia 资源池已关闭")

    def get_pool(self) -> ResourcePool:
        """获取资源池，未初始化时懒加载。

        Returns:
            hestia ResourcePool 实例。
        """
        if self._pool is None:
            self.init_pool()
        return self._pool

    @staticmethod
    def _run_sync_in_thread(
        tool: "ToolBase",
        params: Dict[str, Any],
        ctx: TaskContext,
    ) -> Any:
        """在独立线程的事件循环中执行异步工具（供线程池调用）。

        线程池线程中不存在运行中的事件循环，因此可在其中
        使用 asyncio.run() 运行异步的 tool.run()。

        Args:
            tool: 工具实例。
            params: 执行参数。
            ctx: 任务执行上下文。

        Returns:
            工具执行结果。
        """
        result = asyncio.run(tool.run(params, ctx))
        return result

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _fire_callback(self, task_id: str, event_type: str, payload: Any) -> None:
        """触发指定类型的回调。

        Args:
            task_id: 任务唯一标识。
            event_type: 回调类型（progress/log/complete/error）。
            payload: 回调载荷。
        """
        cb = self._callbacks.get(task_id, {}).get(event_type)
        if cb is None:
            return
        if event_type in ("progress", "log"):
            cb(*payload)
        else:
            cb(payload)

    def _make_progress_cb(self, task_id: str) -> Callable:
        """构造进度回调包装器。

        持久化进度到任务状态机，并广播给外部回调（如 WebSocket）。
        """
        def _cb(percent: int, message: str, stage: str = "") -> None:
            sm = self._tasks.get(task_id)
            if sm is not None:
                sm.update_progress(percent)
            self._fire_callback(task_id, "progress", (percent, message, stage))
        return _cb

    def _make_log_cb(self, task_id: str) -> Callable:
        """构造日志回调包装器。

        持久化日志到任务状态机，并广播给外部回调（如 WebSocket）。
        """
        def _cb(level: str, message: str) -> None:
            sm = self._tasks.get(task_id)
            if sm is not None:
                sm.append_log(level, message)
            self._fire_callback(task_id, "log", (level, message))
        return _cb

    async def _execute_tool(self, task_id: str, name: str, params: Dict[str, Any]) -> None:
        """后台执行工具（异步）。

        完整流程：校验参数 → 创建上下文 → 执行 → 结果/异常处理。

        Args:
            task_id: 任务唯一标识。
            name: 工具名称。
            params: 执行参数。
        """
        sm = self._tasks[task_id]
        sm.transition(TaskStatus.VALIDATING)
        try:
            tool = self.get_tool(name)
            # 首次执行时调用 on_init
            if name not in self._on_init_done:
                await tool.on_init()
                self._on_init_done.add(name)

            # 参数校验
            errors = await tool.validate(params)
            if errors:
                sm.transition(TaskStatus.INVALID)
                sm._error = "; ".join(errors)
                self._fire_callback(task_id, "error", sm._error)
                return

            sm.transition(TaskStatus.VALID)

            # 检查校验阶段是否被取消
            if sm.cancelled:
                sm.transition(TaskStatus.CANCELLED)
                await tool.on_cancel()
                self._fire_callback(task_id, "cancelled", None)
                return

            sm.transition(TaskStatus.RUNNING)

            # 创建执行上下文（共享取消信号）
            ctx = TaskContext(
                task_id=task_id,
                params=params,
                temp_dir=PathUtils.get_temp_dir("data/tmp", name),
                tool_name=name,
                _progress_callback=self._make_progress_cb(task_id),
                _log_callback=self._make_log_cb(task_id),
                _cancel_event=sm._cancel_event,
            )

            # CPU/IO 密集型任务分流：
            # - 密集型任务提交 hestia 线程池执行，带超时控制
            # - IO 密集型任务直接 await，不占用线程池
            if tool.cpu_intensive:
                pool = self.get_pool()
                future = pool.submit(
                    self._run_sync_in_thread, tool, params, ctx
                )
                timeout = pool._config.task_timeout
                if timeout is None:
                    result = await asyncio.wrap_future(future)
                else:
                    try:
                        result = await asyncio.wait_for(
                            asyncio.wrap_future(future), timeout=timeout
                        )
                    except asyncio.TimeoutError:
                        raise TaskTimeoutError(
                            f"工具 '{name}' 执行超时（{timeout}s）"
                        )
            else:
                # IO 密集型任务直接 await 执行
                result = await tool.run(params, ctx)

            # 执行结束后检查取消
            if sm.cancelled:
                sm.transition(TaskStatus.CANCELLED)
                await tool.on_cancel()
                self._fire_callback(task_id, "cancelled", None)
                return

            sm.transition(TaskStatus.COMPLETED)
            sm._result = result
            await tool.on_complete(result)
            self._fire_callback(task_id, "complete", result)
        except Exception as e:
            if sm.cancelled:
                sm.transition(TaskStatus.CANCELLED)
                await tool.on_cancel()
                self._fire_callback(task_id, "cancelled", None)
            else:
                sm.transition(TaskStatus.FAILED)
                sm._error = str(e)
                self._fire_callback(task_id, "error", str(e))
        finally:
            # 无论正常/失败/取消/校验失败，任务退出时均为终态，统一落盘
            self._save_tasks()


# 全局单例 + 装饰器
tool = ToolRegistry()


__all__ = [
    "ToolBase",
    "ParamType",
    "ParamDef",
    "ParamDefSchema",
    "validate_param",
    "TaskContext",
    "TaskStatus",
    "TaskSummary",
    "TaskDetail",
    "TaskStateMachine",
    "ToolMeta",
    "ToolRegistry",
    "tool",
]
