# Fabrica 平台核心模块详细设计文档

---

## 1. 模块概述

### 1.1 职责定位

平台核心模块是整个 Fabrica 系统的**工具插件管理中枢**，负责定义工具的统一接口规范、管理工具的生命周期、提供参数定义系统以及执行上下文。核心职责：

- **工具契约**：定义 `ToolBase` 抽象基类，规范所有工具的接口与生命周期
- **工具注册**：通过装饰器注册和自动目录扫描发现工具
- **参数系统**：提供 `ParamDef` 参数定义体系，自动生成前端表单
- **执行上下文**：封装任务执行环境（进度报告、取消信号、临时目录）
- **任务状态机**：管理每个工具执行实例的状态流转
- **工具元信息**：统一管理工具的名称、版本、分类等元信息

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **契约优先** | 通过 `ToolBase` 抽象基类定义严格接口契约，工具开发者只需关注业务逻辑 |
| **声明式参数** | 工具通过 `ParamDef` 声明参数，平台自动处理校验、表单渲染、序列化 |
| **无侵入注册** | 装饰器 `@tool.register` 方式注册，不要求工具继承特定元类或修改平台代码 |
| **异步执行** | 所有工具执行接口均为异步，平台不阻塞 |
| **可取消** | 支持用户取消正在执行的任务，工具需通过 `ctx.cancelled` 检查并响应 |
| **资源隔离** | 每个工具拥有独立的临时目录和数据目录，避免互相干扰 |

---

## 2. 模块代码结构

```
fabrica/
├── tool.py                     # 工具基类 + 注册中心（核心文件）
│
├── tools/                      # 工具插件目录
│   ├── __init__.py
│   ├── video_dedup/            # 视频验重工具
│   │   └── __init__.py
│   └── (更多工具...)
```

**模块内部依赖关系：**

```
tool.py（平台核心模块，对外统一入口）
    │
    ├── ToolRegistry（注册中心）
    │     ├── 管理: dict[str, type[ToolBase]]   # name → ToolClass
    │     ├── 管理: dict[str, ToolBase]         # name → ToolInstance
    │     ├── 依赖: importlib（动态导入子包）
    │     └── 依赖: pathlib（目录扫描）
    │
    ├── ToolBase（抽象基类）
    │     └── 被所有工具继承
    │
    ├── ParamDef（参数定义数据类）
    │     └── 被所有工具引用
    │
    ├── TaskContext（执行上下文）
    │     └── 由 ToolRegistry.run_tool() 创建并传递给工具
    │
    └── TaskStateMachine（任务状态机）
          └── 由 ToolRegistry 内部管理
```

---

## 3. 各组件详细设计

### 3.1 ToolRegistry — 工具注册中心

**文件：** `fabrica/tool.py`（`ToolRegistry` 类）

**职责：** 集中管理所有工具类的注册、发现和实例化。提供工具列表、参数 Schema、任务执行等统一入口。

#### 3.1.1 内部属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `_tools` | `dict[str, type[ToolBase]]` | 工具名称到工具类的映射 |
| `_instances` | `dict[str, ToolBase]` | 工具名称到工具实例的映射（懒加载） |
| `_tool_dirs` | `list[Path]` | 自动扫描的目录列表 |
| `_tasks` | `dict[str, TaskStateMachine]` | 任务 ID 到任务状态机的映射 |
| `_initialized` | `bool` | 是否已完成初始化扫描 |

#### 3.1.2 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **register(cls)** | `type[ToolBase]` | `type[ToolBase]` | 装饰器/直接调用，注册工具类 |
| **discover()** | — | `int` | 自动扫描 `_tool_dirs` 目录，发现并注册工具 |
| **get_tool(name)** | `str` | `ToolBase` | 获取工具实例（懒加载，首次调用时创建并调用 `on_init()`） |
| **list_tools()** | — | `list[ToolMeta]` | 列出所有已注册工具的元信息 |
| **get_schema(name)** | `str` | `list[ParamDef]` | 获取工具的参数定义列表 |
| **run_tool(name, params, cb)** | `str, dict, Callable` | `str` | 提交工具执行请求，返回 task_id |
| **cancel_task(task_id)** | `str` | `bool` | 取消运行中的任务 |
| **get_task(task_id)** | `str` | `TaskDetail` | 获取任务状态和结果 |
| **list_tasks()** | — | `list[TaskSummary]` | 获取所有任务摘要列表 |
| **register_progress_callback(task_id, cb)** | `str, Callable` | `None` | 注册进度回调，工具执行时推送进度事件 |
| **register_log_callback(task_id, cb)** | `str, Callable` | `None` | 注册日志回调，工具执行时推送日志事件 |
| **register_complete_callback(task_id, cb)** | `str, Callable` | `None` | 注册完成回调，任务结束时推送结果 |
| **register_error_callback(task_id, cb)** | `str, Callable` | `None` | 注册错误回调，任务失败时推送错误信息 |
| **unregister_progress_callback(task_id)** | `str` | `None` | 注销进度回调 |
| **unregister_log_callback(task_id)** | `str` | `None` | 注销日志回调 |
| **unregister_complete_callback(task_id)** | `str` | `None` | 注销完成回调 |
| **unregister_error_callback(task_id)** | `str` | `None` | 注销错误回调 |

#### 3.1.3 内部方法

| 方法名 | 说明 |
|--------|------|
| `_import_tool_module(dir_path)` | 动态导入指定目录下的工具子包 |
| `_create_instance(cls)` | 创建工具实例并调用 `on_init()` |
| `_validate_and_run(name, params, cb)` | 异步执行：校验参数 → 创建 TaskContext → 执行 run() |

#### 3.1.4 注册机制实现

```python
# tool.py 中的核心实现
class ToolRegistry:
    """工具注册中心，单例模式"""

    _instance = None

    # 线程安全说明：
    # 单例创建本身不涉及锁，因为 Python 模块导入是线程安全的，且
    # ToolRegistry 通常在应用启动阶段由主线程初始化，此时不存在并发。
    # 后续对 _tools/_instances 的读写仅在 discover() 注册阶段和
    # list_tools() 查询阶段发生，两者在时序上不重叠（注册先于查询）。
    # 若需在运行时动态注册工具，建议添加 threading.Lock 保护。
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._instances = {}
            cls._instance._tool_dirs = []
            cls._instance._tasks = {}
            cls._instance._initialized = False
        return cls._instance

    def register(self, cls: type) -> type:
        """装饰器注册方法"""
        name = getattr(cls, 'name', None)
        if name is None:
            raise ValueError(f"Tool class {cls.__name__} must have a 'name' attribute")
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = cls
        return cls

    def discover(self, tool_dirs: list[Path] | None = None) -> int:
        """自动扫描目录，发现并注册工具"""
        if tool_dirs:
            self._tool_dirs = tool_dirs
        count = 0
        for tool_dir in self._tool_dirs:
            if not tool_dir.exists():
                continue
            for entry in tool_dir.iterdir():
                if entry.is_dir() and (entry / "__init__.py").exists():
                    try:
                        importlib.import_module(
                            f"fabrica.tools.{entry.name}"
                        )
                        count += 1
                    except Exception as e:
                        logger.warning(f"加载工具 {entry.name} 失败: {e}")
        self._initialized = True
        return count


# 全局单例 + 装饰器
tool = ToolRegistry()
```

### 3.2 ToolBase — 工具抽象基类

**文件：** `fabrica/tool.py`（`ToolBase` 类）

**职责：** 定义所有工具必须遵循的生命周期接口和基础能力。工具开发者继承此类并实现核心钩子方法。

#### 3.2.1 类属性（工具元信息）

| 属性 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | `str` | 是 | — | 工具唯一标识符（snake_case），用于路由和注册 |
| `title` | `str` | 是 | — | 工具显示名称，用于前端展示 |
| `description` | `str` | 是 | — | 功能描述文本，支持 Markdown 子集 |
| `icon` | `str` | 否 | `"🔧"` | 图标（emoji 字符 或 图标文件路径） |
| `params` | `list[ParamDef]` | 否 | `[]` | 参数定义列表，自动生成前端配置表单 |
| `version` | `str` | 否 | `"1.0.0"` | 工具版本号，遵循语义化版本 |
| `category` | `str` | 否 | `"未分类"` | 工具分类标签，用于前端分组展示 |

#### 3.2.2 生命周期钩子

| 方法 | 签名 | 返回值 | 说明 |
|------|------|--------|------|
| `on_init()` | `async (self) -> None` | `None` | 初始化资源。只在首次创建实例时调用一次。适合加载模型、建立连接等重操作 |
| `validate(params)` | `async (self, params: dict) -> list[str]` | `list[str]` | 参数校验。返回空列表表示通过；返回非空列表表示校验失败，列表元素为错误描述 |
| `run(params, ctx)` | `async (self, params: dict, ctx: TaskContext) -> dict` | `dict` | 核心执行逻辑。通过 `ctx.report_progress()` 报告进度，通过 `ctx.cancelled` 检查取消信号 |
| `on_cancel()` | `async (self) -> None` | `None` | 清理资源。当用户取消任务时调用，需释放 GPU 显存、关闭文件句柄等 |
| `on_complete(result)` | `async (self, result: dict) -> None` | `None` | 收尾处理。执行正常结束时调用，可用于发送通知、清理临时文件等 |

#### 3.2.3 完整接口定义

```python
class ToolBase(ABC):
    """工具抽象基类，所有工具必须继承此类"""

    # === 类属性（工具元信息）===
    name: str = ""
    title: str = ""
    description: str = ""
    icon: str = "🔧"
    params: list[ParamDef] = []
    version: str = "1.0.0"
    category: str = "未分类"

    # === 生命周期钩子 ===

    @abstractmethod
    async def on_init(self) -> None:
        """初始化资源，只执行一次"""
        ...

    @abstractmethod
    async def validate(self, params: dict) -> list[str]:
        """参数校验，返回错误列表"""
        ...

    @abstractmethod
    async def run(self, params: dict, ctx: "TaskContext") -> dict:
        """核心执行逻辑"""
        ...

    async def on_cancel(self) -> None:
        """取消时清理资源（可选覆盖）"""
        pass

    async def on_complete(self, result: dict) -> None:
        """执行完成时的收尾处理（可选覆盖）"""
        pass
```

### 3.3 ParamDef — 参数定义系统

**文件：** `fabrica/tool.py`（`ParamDef` 数据类）

**职责：** 定义单个参数的元信息，平台据此自动生成前端表单控件、校验规则和数据序列化协议。

#### 3.3.1 完整定义

```python
@dataclass
class ParamDef:
    """参数定义"""
    key: str                                     # 参数键名，用于 params 字典
    label: str                                   # 显示标签
    type: str = "str"                            # 参数类型
    default: Any = None                          # 默认值
    required: bool = True                        # 是否必填
    description: str = ""                        # 帮助文本
    placeholder: str = ""                        # 输入框占位符
    options: list[tuple[str, str]] | None = None # 枚举选项 (value, label)
    validation: dict | None = None               # 额外校验规则
```

#### 3.3.2 类型系统

| 类型标识 | 前端控件 | 数据结构 | 说明 |
|---------|---------|---------|------|
| `str` | 文本输入框 | `str` | 普通字符串，支持 `min_length`、`max_length`、`pattern` 校验 |
| `int` | 数字输入框（整数） | `int` | 整数，支持 `min`、`max` 校验 |
| `float` | 数字输入框（浮点） | `float` | 浮点数，支持 `min`、`max` 校验 |
| `bool` | 复选框 | `bool` | 布尔开关 |
| `path` | 路径选择器 | `str` | 文件系统路径，支持 `file_extensions` 校验 |
| `file` | 文件选择器 | `str` | 单个文件路径，支持 `file_extensions` 校验 |
| `dir` | 目录选择器 | `str` | 目录路径 |
| `select` | 下拉选择框 | `str` | 单选枚举，需提供 `options` |
| `multi_select` | 多选下拉框 | `list[str]` | 多选枚举，需提供 `options` |
| `password` | 密码输入框 | `str` | 敏感信息，前端掩码显示 |

##### 类型选择指南

| 实际需求 | 推荐类型 | 理由 |
|---------|---------|------|
| 用户输入文本/数字/开关 | `str` / `int` / `float` / `bool` | 标准输入控件 |
| 选择单个文件（如视频文件） | `file` | 自动校验文件存在性，提供文件选择对话框 |
| 选择目录（如输出目录） | `dir` | 自动校验目录存在性，提供目录选择对话框 |
| 不确定是文件还是目录 | `path` | 通用路径输入，不校验存在性，仅做格式校验 |
| 从预定义列表中选择一项 | `select` | 下拉框，防止非法输入 |
| 从预定义列表中选择多项 | `multi_select` | 多选下拉框，返回列表 |
| 输入敏感信息 | `password` | 前端掩码显示，日志中自动脱敏 |

**经验法则**：能用 `select` 不用 `str`（减少用户输入错误），能用 `file` 不用 `path`（提供更好的交互体验）。

#### 3.3.3 校验规则表

| 规则键 | 适用类型 | 类型 | 说明 |
|--------|---------|------|------|
| `min` | int, float | `int | float` | 最小值 |
| `max` | int, float | `int | float` | 最大值 |
| `min_length` | str | `int` | 最小长度 |
| `max_length` | str | `int` | 最大长度 |
| `pattern` | str | `str` | 正则表达式匹配 |
| `file_extensions` | file, path | `list[str]` | 允许的文件扩展名列表，如 `[".mp4", ".avi", ".mov"]` |

### 3.4 TaskContext — 执行上下文

**文件：** `fabrica/tool.py`（`TaskContext` 数据类）

**职责：** 封装工具执行时的运行环境，提供进度报告、取消信号、临时目录等功能。

#### 3.4.1 属性与接口

| 成员 | 类型 | 说明 |
|------|------|------|
| `task_id` | `str` | 全局唯一任务 ID（UUID v4） |
| `params` | `dict` | 参数快照（用户提交时的深拷贝，防止执行过程中被修改） |
| `temp_dir` | `Path` | 工具专属临时目录，任务结束后自动清理 |
| `report_progress(percent, message)` | `async method` | 报告进度，自动推送到前端 WebSocket |
| `log(level, message)` | `async method` | 写入工具日志，同时推送到前端 WebSocket |
| `cancelled` | `property -> bool` | 检查用户是否已取消任务 |
| `get_data_dir()` | `method -> Path` | 获取工具持久化数据目录（跨任务共享） |

#### 3.4.2 实现要点

```python
@dataclass
class TaskContext:
    task_id: str
    params: dict
    temp_dir: Path
    _progress_callback: Callable | None = None
    _log_callback: Callable | None = None
    _cancel_event: Event | None = None

    async def report_progress(self, percent: float, message: str = ""):
        """报告进度，取值范围 [0, 100]"""
        percent = max(0.0, min(100.0, percent))
        if self._progress_callback:
            await self._progress_callback(self.task_id, percent, message)

    async def log(self, level: str, message: str):
        """写入日志"""
        if self._log_callback:
            await self._log_callback(self.task_id, level, message)

    @property
    def cancelled(self) -> bool:
        """检查取消信号"""
        return self._cancel_event is not None and self._cancel_event.is_set()

    def get_data_dir(self) -> Path:
        """获取工具持久化数据目录"""
        path = self.temp_dir.parent / "data" / self.params.get("_tool_name", "unknown")
        path.mkdir(parents=True, exist_ok=True)
        return path
```

### 3.5 TaskStateMachine — 任务状态机

**文件：** `fabrica/tool.py`（`TaskStateMachine` 类）

**职责：** 管理单个任务实例的状态流转，确保状态转换合法，提供状态查询和事件通知。

#### 3.5.1 状态定义

| 状态 | 枚举值 | 说明 |
|------|--------|------|
| PENDING | `"pending"` | 任务创建，等待调度 |
| VALIDATING | `"validating"` | 参数校验中 |
| VALID | `"valid"` | 参数校验通过 |
| INVALID | `"invalid"` | 参数校验失败 |
| RUNNING | `"running"` | 执行中 |
| COMPLETED | `"completed"` | 执行成功完成 |
| FAILED | `"failed"` | 执行异常终止 |
| CANCELLED | `"cancelled"` | 用户取消 |

#### 3.5.2 状态转换矩阵

| 当前状态 | 合法下一状态 | 触发条件 |
|---------|------------|---------|
| PENDING | VALIDATING | 调度器开始执行 |
| VALIDATING | VALID | 校验通过（返回空列表） |
| VALIDATING | INVALID | 校验失败（返回非空列表） |
| VALID | RUNNING | 执行开始 |
| RUNNING | COMPLETED | 执行正常结束 |
| RUNNING | FAILED | 执行抛出异常 |
| RUNNING | CANCELLED | 用户请求取消 |
| INVALID | — | 终态 |
| COMPLETED | — | 终态 |
| FAILED | — | 终态 |
| CANCELLED | — | 终态 |

#### 3.5.3 核心接口

```python
class TaskStateMachine:
    def __init__(self, task_id: str, tool_name: str, params: dict):
        self.task_id = task_id
        self.tool_name = tool_name
        self.params = params
        self._status = TaskStatus.PENDING
        self._result: dict | None = None
        self._error: str | None = None
        self._progress: float = 0.0
        self._created_at = datetime.now()
        self._completed_at: datetime | None = None

    def transition(self, new_status: TaskStatus) -> bool:
        """尝试状态转换，非法转换返回 False"""
        if new_status in self._valid_transitions(self._status):
            self._status = new_status
            if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                self._completed_at = datetime.now()
            return True
        return False

    def update_progress(self, percent: float):
        self._progress = percent

    @staticmethod
    def _valid_transitions(current: TaskStatus) -> set[TaskStatus]:
        """返回当前状态的所有合法下一状态"""
        _transitions = {
            TaskStatus.PENDING: {TaskStatus.VALIDATING},
            TaskStatus.VALIDATING: {TaskStatus.VALID, TaskStatus.INVALID},
            TaskStatus.VALID: {TaskStatus.RUNNING},
            TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
        }
        return _transitions.get(current, set())

    def to_summary(self) -> TaskSummary:
        return TaskSummary(
            task_id=self.task_id, tool_name=self.tool_name,
            status=self._status.value, progress=self._progress,
            created_at=self._created_at, completed_at=self._completed_at,
        )

    def to_detail(self) -> TaskDetail:
        return TaskDetail(
            **self.to_summary().model_dump(),
            params=self.params, result=self._result,
            error=self._error, logs=[],
        )
```

---

## 4. 配置项

通过 `fabrica.tools` 配置节控制平台核心模块的行为：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `fabrica.tools.dirs` | `list[str]` | `["fabrica/tools"]` | 工具扫描目录列表 |
| `fabrica.tools.auto_discover` | `bool` | `true` | 是否启动时自动扫描发现工具 |

---

## 5. 模块关系与数据流

### 5.1 与其他模块的关系

| 关系方向 | 模块 | 接口 | 说明 |
|----------|------|------|------|
| **平台核心 → 工具** | 各工具插件 | `ToolBase` 子类 | 平台核心调用工具的 `run()` 方法 |
| **平台核心 → 服务层** | Server 模块 | `ToolRegistry` 的公共接口 | 服务层通过 API 调用平台核心 |
| **平台核心 → 基础设施** | Utils 模块 | 日志、配置 | 平台核心使用日志和配置能力 |

### 5.2 工具执行数据流

```
用户前端              服务层(Server)          平台核心(ToolRegistry)          工具实例
    │                      │                         │                       │
    │  POST /run           │                         │                       │
    │─────────────────────▶│                         │                       │
    │                      │  ToolRegistry           │                       │
    │                      │  .run_tool()            │                       │
    │                      │────────────────────────▶│                       │
    │                      │                         │  1. 创建 TaskContext   │
    │                      │                         │  2. 创建状态机(PENDING) │
    │                      │                         │  3. 状态→VALIDATING    │
    │                      │                         │  4. validate(params)──▶│
    │                      │                         │◀── [] ────────────────│
    │                      │                         │  5. 状态→VALID         │
    │                      │                         │  6. 状态→RUNNING       │
    │                      │                         │  7. run(params, ctx)──▶│
    │                      │                         │                       │
    │  WS 实时进度          │                         │                       │
    │◀═════════════════════│═════════════════════════│◀──── progress ────────│
    │                      │                         │                       │
    │                      │                         │◀─── return result ────│
    │                      │                         │  8. 状态→COMPLETED     │
    │                      │                         │  9. on_complete()      │
    │                      │                         │  10. 清理 temp_dir     │
    │                      │                         │                       │
    │  GET /tasks/{id}     │                         │                       │
    │─────────────────────▶│────────────────────────▶│                       │
    │◀──── result ────────│◀──────── result ────────│                       │
```

### 5.3 并发限制

工具执行可能长时间占用 CPU/GPU 资源，需限制并发任务数以防止资源耗尽。

| 资源类型 | 限制策略 | 说明 |
|---------|---------|------|
| **CPU 密集型** | `ThreadPoolExecutor(max_workers=2)` | 超过 2 个任务排队等待，避免 CPU 争抢 |
| **GPU 密集型** | 隐式限制（显存独占） | 同一时间仅一个 GPU 任务可运行，其余排队 |
| **IO 密集型** | 无限制（协程内执行） | 不占用线程池，事件循环自然调度 |

并发限制通过 `asyncio.Semaphore` 实现，详见 [README 异步执行调度](../../README.md#44-异步执行调度)。

---

## 6. 监控与维护

### 6.1 日志

| 级别 | 场景 |
|------|------|
| **INFO** | 工具注册成功、任务创建、状态变更、执行完成 |
| **WARNING** | 工具扫描失败、参数校验失败、任务取消 |
| **ERROR** | 工具执行异常、注册冲突 |

### 6.2 异常处理

| 异常类型 | 处理方式 |
|---------|---------|
| 工具初始化失败 | 记录错误，跳过该工具注册，不影响其他工具 |
| 工具执行异常 | 捕获异常，任务状态标记为 FAILED，记录错误信息 |
| 参数校验失败 | 返回校验错误列表，任务状态标记为 INVALID |
| 用户取消 | 设置取消事件，等待工具响应，超时后强制终止 |

### 6.3 性能指标

| 指标 | 说明 |
|------|------|
| 任务执行时间 | 从任务创建到完成的总耗时 |
| 工具注册数 | 当前已注册的工具数量 |
| 并发任务数 | 同时运行的任务数量 |
| 任务成功率 | 任务完成率（COMPLETED / 总任务数） |

---

## 7. 扩展与迭代

### 7.1 添加新工具

1. 在 `fabrica/tools/` 下创建子目录，如 `my_tool/`
2. 在 `__init__.py` 中定义工具类，继承 `ToolBase`
3. 设置类属性（name, title, description, params 等）
4. 使用 `@tool.register` 装饰器注册
5. 实现 `validate()` 和 `run()` 方法

### 7.2 自定义参数类型

如需新的参数类型，扩展示例：

1. 在 `ParamDef` 的 `type` 字段中添加新类型标识
2. 在前端注册对应的表单控件渲染器
3. 在后端注册对应的校验器（可选）

### 7.3 自定义校验规则

在 `ParamDef.validation` 字典中添加新的规则键，平台核心在 `validate()` 方法中自动应用。

### 7.4 未来迭代计划

| 迭代项 | 描述 | 优先级 |
|-------|------|--------|
| 工具依赖注入 | 支持工具之间共享数据（如一个工具的输出作为另一个工具的输入） | P2 |
| 工具热加载 | 修改工具代码后无需重启平台 | P3 |
| 工具性能监控 | 记录每个工具的执行时间、内存使用、GPU 显存 | P3 |
| 工具沙箱 | 可选的进程隔离模式，支持不安全工具的安全执行 | P4 |

---

## 8. 设计决策记录

### 8.1 为什么 ToolBase 使用类属性而非实例属性

**问题**：工具元信息（name, title, params 等）应当定义为类属性还是实例属性？

**决策**：**类属性**。

**原因**：
1. 元信息是**静态的**，不随实例变化，定义在类上更合理
2. 前端需要在不实例化工具的情况下获取参数 Schema（`get_schema()` 方法）
3. 类属性可在子类中直接覆盖，无需重写 `__init__`

### 8.2 为什么 ToolRegistry 使用单例模式

**问题**：工具注册中心是否需要全局唯一实例？

**决策**：**是**。

**原因**：
1. 工具注册是全局状态，不应有多个实例导致注册不一致
2. 装饰器 `@tool.register` 需要访问全局唯一的注册中心实例
3. 单例模式避免了将注册中心实例作为参数层层传递

### 8.3 为什么工具采用懒加载而非启动时全部实例化

**问题**：工具实例应当在平台启动时全部创建，还是按需创建？

**决策**：**懒加载**（首次调用 `get_tool()` 时创建）。

**原因**：
1. 工具的 `on_init()` 可能包含重操作（加载模型、建立连接等），启动时全部执行会显著拖慢启动速度
2. 用户可能只使用部分工具，没有必要为所有工具预先分配资源
3. 懒加载使得工具可以按需释放资源（`on_cancel()` 后可以卸载模型）