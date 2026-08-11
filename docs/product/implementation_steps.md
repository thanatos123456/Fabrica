# Fabrica 实现步骤

## 文档信息

| 项目 | 内容 |
|------|------|
| **项目名称** | Fabrica — 工具集平台 |
| **文档版本** | v1.0 |
| **创建日期** | 2026-08-02 |
| **参考文档** | README.md + docs/core/(2) + docs/common/(3) + docs/tools/(1) + fabrica_aurora_integration_plan.md |

---

## 实现计划总览

Fabrica 第一阶段 MVP 实现周期为 10 周，分为 5 个阶段：

```
阶段一（第1-2周）           阶段二（第3-4周）           阶段三（第5-6周）
┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│ 项目骨架+公共基础设施   │   │ 平台核心模块           │   │ API服务层+Web前端     │
│                       │   │                      │   │                      │
│ · 项目目录结构+配置    │   │ · ToolBase 抽象基类   │   │ · FastAPI 应用工厂    │
│ · 日志系统 (helios)   │   │ · ParamDef 参数系统    │   │ · REST API 7端点     │
│ · 配置管理 (phoenix)  │   │ · TaskContext 执行上下文│   │ · WebSocket 实时推送  │
│ · 异常体系 (nemesis)  │   │ · TaskStateMachine     │   │ · 统一错误响应        │
│ · 设备检测(CPU/GPU)   │   │ · ToolRegistry 注册中心 │   │ · SPA前端(Hash路由)   │
│ · 路径工具+工具函数    │   │ · 装饰器+自动扫描发现   │   │ · 工具卡片/表单/进度   │
│ · main.py + 脚本系统   │   │ · 线程池(hestia)       │   │ · 单元测试            │
│ · 单元测试             │   │ · 单元测试             │   │                      │
└──────────────────────┘   └──────────────────────┘   └──────────────────────┘

阶段四（第7-8周）           阶段五（第9-10周）
┌──────────────────────┐   ┌──────────────────────┐
│ 视频验重工具L1+L2     │   │ 视频验重工具L3+全流程   │
│                      │   │                      │
│ · Sampler 抽帧模块   │   │ · CLIPExtractor 深度特征│
│ · FileHashExtractor  │   │ · DeepMatcher 比对     │
│ · PHashExtractor     │   │ · UnionFindCluster     │
│ · PHashIndex(FAISS)  │   │ · CascadePipeline      │
│ · SequenceAligner    │   │ · VideoStorage完整     │
│ · VideoStorage基础   │   │ · 工具注册(@tool.register)│
│ · 候选生成策略        │   │ · 集成测试+端到端测试   │
│ · 单元测试            │   │ · 调参报告+文档完善    │
└──────────────────────┘   └──────────────────────┘
```

---

## 阶段一：项目骨架与公共基础设施（第1-2周）

**目标**：搭建项目目录结构，实现所有公共基础设施模块——日志系统、配置管理、异常体系、设备检测、路径工具和工具函数，为上层模块提供通用能力。

### T1.1 创建项目骨架与配置

**任务描述**：初始化项目目录结构、依赖配置和基础模块入口

**交付物**：
- `pyproject.toml` — 包定义（`fabrica` 包名）与依赖声明
- `config.yaml` — 平台配置文件（4 个配置域：server / logging / storage / tools）
- `requirements.txt` — 基础依赖锁定（FastAPI / uvicorn / aurora-python / ...）
- `fabrica/__init__.py` — 主包入口
- `fabrica/app.py` — 应用启动入口（FastAPI 服务创建与启动）
- `main.py` — 主入口文件，`python main.py` 或 `./main.py` 启动
- `scripts/common.sh` — 公共函数库（路径变量、颜色输出、进程管理）
- `scripts/run.sh` — 服务管理脚本（start/stop/restart/status）
- `scripts/dev.sh` — 开发辅助脚本（环境初始化、测试运行）
- 各子目录 `__init__.py`（server/ / tools/ / utils/）
- `tests/__init__.py` — 测试包入口
- `tests/fixtures/` — 测试夹具目录

**验收标准**：
- `python main.py --help` 可正常显示帮助信息
- `bash scripts/run.sh status` 可正常显示服务状态
- 所有子模块可正常 import

---

### T1.2 实现日志系统（基于 helios）

**任务描述**：基于 Aurora/helios 框架实现统一的日志记录能力，支持控制台输出和文件日志，自动轮转。

**参考实现**：`nexus/Augur/app/utils/logger.py` 的 `_create_config()` 函数

**交付物**：
- `fabrica/utils/__init__.py` — 模块导出
- `fabrica/utils/logger.py` — `LoggerManager` 类
  - `LogConfig` 配置：控制台 handler（INFO 级别，彩色输出）+ 文件 handler（DEBUG 级别，10MB 轮转，7天保留）
  - `get_logger(name="fabrica")` — 获取指定名称的日志记录器
  - `setup_logging(config)` — 初始化日志系统（可在应用启动时调用）
  - 日志格式：`%(timestamp)s [%(level)s] %(logger)s: %(message)s`

**验收标准**：
- `get_logger("fabrica")` 可正常获取日志器
- 控制台输出彩色日志，文件日志正确轮转
- 不同模块（fabrica.server / fabrica.tools.video_dedup）日志可区分

---

### T1.3 实现配置管理（基于 phoenix）

**任务描述**：基于 Aurora/phoenix 框架实现配置的加载和管理，支持 YAML/JSON 格式。

**参考实现**：`nexus/Augur/app/utils/config.py` 的 `configure_phoenix()` 和 `get_config_manager()`

**交付物**：
- `fabrica/config.py` — `ConfigManager` 封装
  - `configure_fabrica(config_dir="config")` — 初始化 Phoenix 配置模块
  - `get_config(key, default=None)` — 获取配置项（如 `"fabrica.server.port"`）
  - `get_all_config()` — 获取完整配置字典
  - `reload_config()` — 重新加载配置

**验收标准**：
- `configure_fabrica()` 后 `get_config("fabrica.server.port")` 返回默认值 8520
- 修改 `config.yaml` 后 `reload_config()` 可读到新值
- 配置项不存在时返回默认值

---

### T1.4 实现异常体系（基于 nemesis）

**任务描述**：基于 Aurora/nemesis 框架定义 Fabrica 统一的异常体系，包括错误码和异常类。

**参考实现**：`nexus/Augur/app/utils/exceptions.py` 的 `ErrorCode` 和 `AugurError`

**交付物**：
- `fabrica/exceptions.py` — 异常定义模块
  - `ErrorCode(BaseErrorCode)` — 错误码常量（系统级 + 业务级）
    - 系统：`SYSTEM_ERROR` / `CONFIGURATION_ERROR` / `DATABASE_ERROR` / `NOT_IMPLEMENTED`
    - 工具：`TOOL_NOT_FOUND` / `TOOL_REGISTER_ERROR` / `TOOL_RUN_ERROR` / `TOOL_INIT_ERROR`
    - 任务：`TASK_NOT_FOUND` / `TASK_CANCEL_ERROR` / `TASK_TIMEOUT` / `TASK_STATE_ERROR`
    - 参数：`PARAM_INVALID` / `PARAM_MISSING` / `PARAM_TYPE_ERROR` / `PARAM_VALIDATION_ERROR`
  - `FabricaError(BusinessException)` — 基础异常
    - `__init__` 接受 `message` / `error_code` / `status_code` / `details`
    - `__str__` 只返回消息文本
  - 具体异常类（每个继承 `FabricaError`）：
    - `ToolNotFoundError` / `ToolRegisterError` / `ToolRunError` / `ToolInitError`
    - `TaskNotFoundError` / `TaskCancelError` / `TaskTimeoutError` / `TaskStateError`
    - `ParamInvalidError` / `ParamMissingError` / `ParamTypeError` / `ParamValidationError`
    - `ConfigError` / `ServerError`

**验收标准**：
- `raise ToolNotFoundError("工具不存在")` 正确抛出
- `exception_response(exc)` 返回统一格式的 JSON 响应
- `safe_call(func, fallback=None)` 在异常时返回 fallback

---

### T1.5 实现设备检测模块

**任务描述**：实现自动检测可用计算设备（CPU/GPU）的模块，提供统一的设备选择接口。

**交付物**：
- `fabrica/utils/device.py` — `DeviceDetector` 模块
  - `get_device(prefer="auto")` — 返回 `"cuda"` 或 `"cpu"`（auto 时自动检测）
  - `get_device_info()` — 返回设备详细信息字典（CUDA 版本、设备名、设备数）
  - `is_cuda_available()` — 检查 CUDA 是否可用
  - `get_batch_size_hint()` — 根据设备返回建议的 batch_size（GPU 64 / CPU 16）

**验收标准**：
- `get_device("cpu")` 始终返回 `"cpu"`
- 无 GPU 时 `get_device("auto")` 返回 `"cpu"`
- `get_device_info()` 返回格式正确的字典

---

### T1.6 实现路径工具与工具函数

**任务描述**：实现平台无关的路径操作和通用辅助函数。

**交付物**：
- `fabrica/utils/helpers.py` — 工具函数模块
  - `PathUtils` 类：
    - `get_temp_dir(base_dir, prefix)` — 创建并返回临时目录
    - `get_data_dir(base_dir, tool_name)` — 获取工具持久化数据目录
    - `ensure_dir(path)` — 确保目录存在
    - `safe_filename(filename)` — 清理文件名非法字符
  - 通用函数：
    - `format_size(bytes)` — 格式化文件大小（如 `"1.5 GB"`）
    - `format_duration(seconds)` — 格式化时间（如 `"1h 23m 45s"`）
    - `format_timestamp(dt)` — 格式化时间戳
    - `compute_file_hash(path, algo="md5")` — 计算文件哈希
    - `chunked(iterable, size)` — 将可迭代对象分块

**验收标准**：
- `format_size(1073741824)` 返回 `"1.0 GB"`
- `format_duration(3661)` 返回 `"1h 1m 1s"`
- `ensure_dir("/tmp/fabrica_test")` 创建目录成功
- `compute_file_hash` 对同一文件返回相同哈希值

---

### T1.7 实现脚本系统（main.py + shell scripts）

**任务描述**：实现主入口文件和服务管理脚本，参考 `nexus/Augur/main.py` 和 `nexus/Augur/scripts/` 的设计模式。

**参考实现**：
- `nexus/Augur/main.py` 的 `main()` 函数和 `argparse` 用法
- `nexus/Augur/scripts/common.sh` 的公共函数库设计
- `nexus/Augur/scripts/run.sh` 的服务管理设计

**交付物**：
- `main.py` — 主入口文件
  - shebang: `#!/usr/bin/env python3`
  - `sys.path` 调整：自动发现 OmniPivot 根目录，插入 `aurora/python` 路径
  - `argparse` 参数：`--port` / `--host` / `--config` / `--log-level`
  - `main()` 函数：解析参数 → 初始化配置 → 启动服务 → 优雅关闭（信号处理）
  - `if __name__ == "__main__"` 入口守卫
- `scripts/common.sh` — 公共函数库
  - 路径变量：`SCRIPT_DIR` / `PROJECT_ROOT` / `FABRICA_DIR` / `MAIN_SCRIPT`
  - 颜色输出函数：`info()` / `warn()` / `error()` / `success()`
  - 进程管理函数：`get_pid()` / `check_running()` / `wait_for_stop()`
  - 环境检测函数：`check_python()` / `check_deps()`
- `scripts/run.sh` — 服务管理脚本
  - 子命令：`start`（后台启动，PID 记录） / `stop`（优雅关闭） / `restart` / `status`
  - 日志重定向：stdout + stderr → `data/logs/fabrica.log`
  - PID 文件管理：`data/pids/fabrica.pid`
- `scripts/dev.sh` — 开发辅助脚本
  - 子命令：`setup`（创建 venv + 安装依赖） / `test`（运行测试） / `serve`（前台启动开发服务器）

**验收标准**：
- `python main.py --help` 显示所有参数
- `bash scripts/run.sh start` 后台启动服务，PID 文件正确写入
- `bash scripts/run.sh status` 正确显示服务运行状态
- `bash scripts/run.sh stop` 优雅关闭服务，PID 文件清理
- `bash scripts/dev.sh setup` 创建虚拟环境并安装依赖

---

### T1.8 单元测试（阶段一）

**任务描述**：编写阶段一所有模块的单元测试

**交付物**：
- `tests/test_utils/test_logger.py` — 日志模块测试
- `tests/test_utils/test_config.py` — 配置管理测试
- `tests/test_utils/test_exceptions.py` — 异常体系测试
- `tests/test_utils/test_device.py` — 设备检测测试
- `tests/test_utils/test_helpers.py` — 工具函数测试
- `tests/test_config.py` — 配置文件加载测试
- `tests/test_main.py` — 入口文件与脚本测试

**验收标准**：测试覆盖率 > 80%

---

## 阶段二：平台核心模块（第3-4周）

**目标**：实现 Fabrica 平台的核心——工具插件系统，包括 ToolBase 抽象基类、ParamDef 参数系统、TaskContext 执行上下文、TaskStateMachine 任务状态机和 ToolRegistry 注册中心，并集成 hestia 资源池管理线程池。

### T2.1 实现 ToolBase 抽象基类

**任务描述**：定义所有工具必须遵循的统一接口规范，包括生命周期钩子和元信息属性。

**交付物**：
- `fabrica/tool.py` — 平台核心模块（ToolBase 部分）
  - `ToolBase(ABC)` 抽象基类
    - 类属性：`name` / `title` / `description` / `icon` / `params` / `version` / `category`
    - 抽象方法：`on_init()` / `validate(params)` / `run(params, ctx)`
    - 可选方法：`on_cancel()` / `on_complete(result)`
    - 所有方法签名使用 `async def`

**验收标准**：
- 继承 `ToolBase` 的子类未实现抽象方法时，实例化抛出 `TypeError`
- 所有方法签名正确（`async` + 正确参数列表）

---

### T2.2 实现 ParamDef 参数定义系统

**任务描述**：实现参数定义数据类，支持 10 种参数类型和 6 种校验规则，前端据此自动渲染表单控件。

**交付物**：
- `fabrica/tool.py`（ParamDef 部分）
  - `ParamDef` 数据类
    - 字段：`key` / `label` / `type` / `default` / `required` / `description` / `placeholder` / `options` / `validation`
  - 参数类型枚举：`str` / `int` / `float` / `bool` / `path` / `file` / `dir` / `select` / `multi_select` / `password`
  - `ParamDefSchema` Pydantic 模型（用于 API 序列化）
  - 校验规则引擎：`validate_param(value, param_def)` 函数
    - 支持 `min` / `max` / `min_length` / `max_length` / `pattern` / `file_extensions`

**验收标准**：
- `ParamDef(key="threshold", type="float", validation={"min": 0, "max": 1})` 定义正确
- `validate_param(0.5, param_def)` 返回空列表
- `validate_param(1.5, param_def)` 返回 `["超过最大值 1"]`

---

### T2.3 实现 TaskContext 执行上下文

**任务描述**：封装工具执行时的运行环境，提供进度报告、取消信号、临时目录等功能。

**交付物**：
- `fabrica/tool.py`（TaskContext 部分）
  - `TaskContext` 数据类
    - 属性：`task_id` / `params` / `temp_dir`
    - 方法：`report_progress(percent, message)` / `log(level, message)`
    - 属性：`cancelled`（检查取消信号）
    - 方法：`get_data_dir()`（获取工具持久化数据目录）
  - 内部使用 `asyncio.Event` 实现取消信号
  - 回调机制：`_progress_callback` / `_log_callback`（与 ToolRegistry 解耦）

**验收标准**：
- `ctx.report_progress(50, "处理中")` 正确触发回调
- `ctx.cancelled` 在未取消时返回 `False`
- `ctx.get_data_dir()` 返回正确的目录路径

---

### T2.4 实现 TaskStateMachine 任务状态机

**任务描述**：管理每个工具执行实例的状态流转，确保状态转换合法，提供状态查询和事件通知。

**交付物**：
- `fabrica/tool.py`（TaskStateMachine 部分）
  - `TaskStatus` 枚举：`PENDING` / `VALIDATING` / `VALID` / `INVALID` / `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED`
  - `TaskStateMachine` 类
    - `transition(new_status)` — 尝试状态转换，非法返回 `False`
    - `update_progress(percent)` — 更新进度
    - `to_summary()` — 返回 `TaskSummary`
    - `to_detail()` — 返回 `TaskDetail`
    - `_valid_transitions(current)` — 静态方法，返回合法下一状态集合
    - 状态转换矩阵（8 状态，共 9 条合法转换规则）

**验收标准**：
- `PENDING → VALIDATING → VALID → RUNNING → COMPLETED` 合法转换
- `PENDING → COMPLETED` 非法转换返回 `False`
- 终态（INVALID / COMPLETED / FAILED / CANCELLED）不可再转换

---

### T2.5 实现 ToolRegistry 注册中心

**任务描述**：实现集中管理所有工具类的注册、发现和实例化，提供工具列表、参数 Schema、任务执行等统一入口。

**交付物**：
- `fabrica/tool.py`（ToolRegistry 部分）
  - `ToolRegistry` 单例类
    - 内部属性：`_tools` / `_instances` / `_tool_dirs` / `_tasks` / `_initialized`
    - 注册接口：`register(cls)` — 装饰器/直接调用
    - 发现接口：`discover(tool_dirs)` — 自动扫描目录，动态导入子包
    - 查询接口：`list_tools()` / `get_tool(name)` / `get_schema(name)` / `get_tool_meta(name)`
    - 执行接口：`run_tool(name, params, cb)` — 返回 `task_id`（异步执行）
    - 控制接口：`cancel_task(task_id)` / `get_task(task_id)` / `list_tasks()`
    - 回调接口：`register_progress_callback` / `register_log_callback` / `register_complete_callback` / `register_error_callback`
    - 回调注销：`unregister_progress_callback` / `unregister_log_callback` / `unregister_complete_callback` / `unregister_error_callback`
  - 全局单例 `tool = ToolRegistry()`
  - `@tool.register` 装饰器

**验收标准**：
- `@tool.register` 装饰器正确注册工具类
- `discover()` 自动扫描目录，发现并注册工具
- `run_tool()` 返回唯一 `task_id`，后台异步执行
- `cancel_task()` 正确设置取消信号
- 回调机制完整：注册 → 触发 → 注销

---

### T2.6 集成 hestia 资源池管理线程池

**任务描述**：将规划中的 `ThreadPoolExecutor` 替换为 Aurora/hestia 的 `ResourcePool`，统一管理 CPU 密集型工具的并发执行。

**交付物**：
- `fabrica/tool.py` — 修改 `run_tool()` 执行逻辑
  - 使用 `ResourcePool` 替代 `ThreadPoolExecutor`
  - `PoolConfig(pool_type="thread", max_size=2, task_timeout=3600)`
  - `pool.execute(func, *args)` 提交 CPU 密集型任务
  - IO 密集型任务直接 `await`，不占用线程池
  - 资源池在应用启动时初始化，关闭时优雅释放

**验收标准**：
- 超过 2 个并发 CPU 任务时，第 3 个任务排队等待
- 工具执行超时（3600s）后任务被标记为 FAILED
- 资源池在应用关闭时正确释放

---

### T2.7 单元测试（阶段二）

**任务描述**：编写阶段二所有模块的单元测试

**交付物**：
- `tests/test_tool_base.py` — ToolBase 基类测试
- `tests/test_param_def.py` — ParamDef 参数系统测试
- `tests/test_task_context.py` — 执行上下文测试
- `tests/test_state_machine.py` — 任务状态机测试（覆盖所有合法+非法转换）
- `tests/test_tool_registry.py` — 注册中心测试（注册/发现/执行/取消）
- `tests/test_resource_pool.py` — 资源池集成测试

**验收标准**：测试覆盖率 > 80%

---

## 阶段三：API 服务层与 Web 前端（第5-6周）

**目标**：实现 FastAPI 服务层，提供 REST API 和 WebSocket 实时推送；实现 SPA 前端，提供工具首页、详情页、执行页和任务历史页。

### T3.1 实现 AppFactory 应用工厂

**任务描述**：创建和配置 FastAPI 应用实例，注册中间件、异常处理器、路由和静态资源服务。

**交付物**：
- `fabrica/server/__init__.py` — 模块入口
  - `create_app(config, tool_registry)` — 创建并配置 FastAPI 应用
    - 注册 CORS 中间件（`allow_origins=config.server.cors_origins`）
    - 注册全局异常处理器（基于 nemesis `GlobalExceptionHandler`）
    - 注册请求日志中间件
    - 挂载静态资源（`StaticFiles(directory="static", html=True)`）
    - 注册 API 路由（`app.include_router(router)`）
    - 使用 `nemesis.register_exception_handlers(app)` 注册异常处理器

**验收标准**：
- `create_app()` 返回正确的 FastAPI 实例
- CORS 中间件配置正确
- 静态资源路径正确挂载

---

### T3.2 实现 REST API 端点

**任务描述**：定义 7 个 REST 端点，覆盖工具列表、工具详情、任务提交、任务查询和任务取消。

**交付物**：
- `fabrica/server/routes.py` — API 路由定义
  - Pydantic 请求/响应模型：`RunRequest` / `RunResponse` / `CancelResponse` / `ToolMeta` / `ToolDetail` / `TaskSummary` / `TaskDetail` / `LogEntry`
  - 7 个 REST 端点：
    - `GET /api/tools` — 获取所有工具元信息列表
    - `GET /api/tools/{name}` — 获取单个工具详细信息（含参数定义）
    - `POST /api/tools/{name}/run` — 提交工具执行请求
    - `GET /api/tasks` — 获取任务历史列表
    - `GET /api/tasks/{id}` — 获取单个任务完整状态和结果
    - `POST /api/tasks/{id}/cancel` — 取消正在执行的任务
    - `DELETE /api/tasks/{id}` — 删除任务记录
  - 统一错误响应格式（基于 nemesis）
  - 错误码映射：`TOOL_NOT_FOUND → 404` / `PARAM_INVALID → 422` / `TASK_NOT_FOUND → 404` / `INTERNAL_ERROR → 500`

**验收标准**：
- `GET /api/tools` 返回空列表（无已注册工具时）
- `GET /api/tools/{name}` 工具不存在时返回 404
- `POST /api/tools/{name}/run` 返回 `{task_id, status}`
- 所有端点返回正确的 Pydantic 模型

---

### T3.3 实现 WebSocket 实时推送

**任务描述**：实现 WebSocket 端点，为运行中的任务提供实时进度、日志、完成和错误事件推送。

**交付物**：
- `fabrica/server/routes.py`（WebSocket 部分）
  - `WS /api/ws/tasks/{task_id}` 端点
    - 接受 WebSocket 连接
    - 通过回调机制注册进度/日志/完成/错误回调（包装 WebSocket 发送）
    - 处理心跳检测（ping/pong）
    - 客户端断开时自动注销回调
  - 回调解耦：WebSocket 连接通过回调函数与 ToolRegistry 交互，不直接传入 WebSocket 对象

**验收标准**：
- WebSocket 连接建立后正确接收进度事件
- 客户端断开后回调正确注销
- 心跳检测正常（ping → pong）

---

### T3.4 实现 SPA 前端

**任务描述**：实现基于原生 HTML+CSS+JS 的单页应用，提供 5 个页面的前端路由和交互。

**交付物**：
- `fabrica/server/static/index.html` — SPA 入口（`<div id="app">` + 引入 JS/CSS）
- `fabrica/server/static/css/style.css` — 全局样式（CSS 自定义属性实现主题切换）
- `fabrica/server/static/js/app.js` — 应用入口（路由初始化）
- `fabrica/server/static/js/router.js` — SPA Hash 路由实现
  - 支持 5 个路由：`/` / `/tool/{name}` / `/tool/{name}/run` / `/tasks` / `/tasks/{id}`
  - `hashchange` 事件监听
- `fabrica/server/static/js/api.js` — HTTP API 客户端封装（`fetch()` + `async/await`）
- `fabrica/server/static/js/ws.js` — WebSocket 客户端封装
- `fabrica/server/static/js/components/tool-card.js` — 工具卡片组件
- `fabrica/server/static/js/components/tool-form.js` — 参数配置表单组件（动态渲染 10 种控件类型）
- `fabrica/server/static/js/components/task-progress.js` — 任务进度组件（进度条 + 日志流）
- `fabrica/server/static/js/components/task-history.js` — 任务历史组件

**验收标准**：
- 5 个页面路由正确跳转
- 工具卡片列表正常渲染
- 参数表单动态渲染正确（10 种控件类型）
- WebSocket 实时进度在进度条和日志流中展示

---

### T3.5 单元测试（阶段三）

**任务描述**：编写阶段三所有模块的单元测试

**交付物**：
- `tests/test_server/test_app_factory.py` — 应用工厂测试
- `tests/test_server/test_routes.py` — REST API 测试（使用 `TestClient`）
- `tests/test_server/test_websocket.py` — WebSocket 测试

**验收标准**：测试覆盖率 > 80%

---

### T3.6 桌面窗口集成（pywebview）

**任务描述**：用 pywebview 将现有 Web 前端包装为原生桌面窗口，使 exe 打开后直接弹出独立窗口（无控制台），复用现有 FastAPI 服务与前端代码。详细设计见 [docs/core/desktop_integration.md](../core/desktop_integration.md)。

**交付物**：
- `fabrica/desktop/__init__.py` — 桌面启动器模块
  - `launch_window(host, port, title, width, height, min_size, on_close)` — 创建 pywebview 窗口并阻塞主线程
  - `launch_browser(host, port)` — dev_mode 浏览器回退模式
  - `wait_for_server(host, port, timeout)` — 端口就绪探测（轮询 socket 连接）
- `main.py` — 修改启动流程
  - uvicorn 服务线程化（`threading.Thread(daemon=True)`）
  - 端口就绪探测后调用 `launch_window()` 或 `launch_browser()`
  - 窗口关闭回调触发 `server.should_exit = True`
  - dev_mode 判断逻辑（Linux 自动回退浏览器）
- `build_win.spec` — 修改打包配置
  - `console=True` → `console=False`（隐藏控制台）
  - `hiddenimports` 增加 `"pywebview"` 和 `"pywebview.platforms.winforms"`
- `config/config.yaml` — 增加 `fabrica.desktop` 配置域
  - `window_title` / `width` / `height` / `min_size` / `dev_mode`
- `requirements.txt` — 增加 `pywebview>=4.0` 依赖

**验收标准**：
- Windows exe 打开后直接弹出 pywebview 桌面窗口（无控制台终端）
- 窗口标题、尺寸符合 `fabrica.desktop` 配置
- 窗口关闭后进程优雅退出（uvicorn 服务停止 + 资源池释放）
- Linux 开发环境 `dev_mode` 自动回退浏览器模式，`python main.py` 正常启动
- 窗口内可正常访问工具首页、提交任务、查看实时进度（复用现有前端）

---

## 阶段四：视频验重工具 — L1 + L2（第7-8周）

**目标**：实现视频验重工具的前两级（L1 文件哈希 + L2 pHash 序列），包括抽帧模块、FAISS 二进制索引和序列对齐打分，并注册为 Fabrica 平台工具。

### T4.1 实现工具注册与基本结构

**任务描述**：创建视频验重工具目录结构，定义工具类并注册到 Fabrica 平台。

**交付物**：
- `fabrica/tools/video_dedup/__init__.py` — 工具入口
  - 继承 `ToolBase` 定义 `VideoDedupTool` 类
  - 设置类属性：`name="video_dedup"` / `title="视频重复检测"` / `description="..."` / `version="1.0.0"` / `category="视频处理"`
  - 定义参数：`input_dir`(dir) / `output`(str) / `recursive`(bool) / `device`(select) / `threshold`(float)
  - 使用 `@tool.register` 装饰器注册
  - 实现 `on_init()` / `validate(params)` / `run(params, ctx)` / `on_cancel()` 方法
- `fabrica/tools/video_dedup/models.py` — 数据模型
  - `VideoInfo` 数据类（id / path / size / duration / width / height / file_hash / frame_count）
  - `MatchResult` 数据类（video_a_id / video_b_id / level / score）
  - `DuplicateGroup` 数据类（video_ids / level / scores）

**验收标准**：
- `tool.list_tools()` 返回包含 `video_dedup` 的列表
- `tool.get_schema("video_dedup")` 返回正确的参数定义
- `tool.run_tool("video_dedup", params)` 返回 task_id

---

### T4.2 实现抽帧模块（Sampler）

**任务描述**：使用 PyAV 对视频文件进行自适应采样，提取关键帧图像，支持短视频密集抽帧和长视频稀疏采样。

**交付物**：
- `fabrica/tools/video_dedup/sampler.py` — 抽帧模块
  - `SampledFrame` 数据类（idx / ts / image）
  - `sample_frames(path, resize, min_frames, max_frames, target_fps)` — 核心抽帧函数
    - 使用 PyAV 精确 seek，只解码需要的帧
    - 自适应采样：短视频（< 16s）抽 min_frames 帧，长视频按 target_fps 均匀采样
    - 统一 resize 到 224x224
    - 返回 `(frames, duration)` 元组
  - `compute_sample_timestamps(duration, min_frames, max_frames, target_fps)` — 计算采样时间点
    - 均匀分布，避开首尾 0.5s

**验收标准**：
- 5 秒视频抽帧返回 min_frames 帧
- 1 小时视频抽帧不超过 max_frames 帧
- 损坏视频返回空列表，不抛出异常
- 采样时间点均匀分布，不超出视频时长

---

### T4.3 实现文件哈希提取器（L1）

**任务描述**：计算视频文件的 MD5 哈希，用于识别字节级完全相同的视频。

**交付物**：
- `fabrica/tools/video_dedup/extractors/__init__.py` — 提取器模块导出
- `fabrica/tools/video_dedup/extractors/filehash.py` — 文件哈希提取器
  - `file_hash(path, block_size=1MB)` — 计算文件 MD5 哈希
  - 1MB 分块读取，避免大文件内存溢出

**验收标准**：
- 同一文件多次调用返回相同哈希值
- 不同文件返回不同哈希值
- 大文件（> 1GB）正常计算，不 OOM

---

### T4.4 实现 pHash 序列提取器（L2）

**任务描述**：对视频的每一帧计算感知哈希，生成 64bit 指纹序列。

**交付物**：
- `fabrica/tools/video_dedup/extractors/phash.py` — pHash 提取器
  - `frame_phash(pil_img, hash_size=8)` — 计算单帧 pHash，返回 64bit 整数
    - 使用 `imagehash.phash` 计算 DCT 感知哈希
    - 转为 `np.uint64` 方便 FAISS 索引
  - `video_phash_sequence(sampled_frames)` — 计算视频所有帧的 pHash 序列
    - 返回 `np.ndarray` shape `[n_frames]`，dtype `np.uint64`

**验收标准**：
- 相同图片两次调用返回相同值
- 相似图片的汉明距离小于不同图片
- 批量处理 100 帧耗时 < 1s

---

### T4.5 实现 FAISS 二进制索引（PHashIndex）

**任务描述**：使用 FAISS 二进制索引管理所有视频的 pHash 指纹，支持汉明距离范围检索和候选对生成。

**交付物**：
- `fabrica/tools/video_dedup/indexing/__init__.py` — 索引模块导出
- `fabrica/tools/video_dedup/indexing/phash_index.py` — pHash 二进制索引
  - `PHashIndex` 类
    - `add(video_id, phash_seq)` — 将视频的 pHash 序列加入索引
    - `search(phash_seq, k)` — 检索最近邻，返回 `(distances, indices)`
    - `generate_candidates(video_ids, hit_threshold=3)` — 生成候选视频对
      - 对每个视频的每一帧，检索最近 k 个帧指纹
      - 统计命中帧数超过 `hit_threshold` 的视频对
  - 使用 `faiss.IndexBinaryFlat`，内存约 40MB（5 万视频 × 100 帧）

**验收标准**：
- `add` 后 `search` 返回正确结果
- 完全相同的 pHash 序列返回汉明距离 0
- `generate_candidates` 正确生成候选对

---

### T4.6 实现序列对齐打分器（SequenceAligner）

**任务描述**：对候选视频对的 pHash 序列进行对齐打分，计算相似度。

**交付物**：
- `fabrica/tools/video_dedup/matching/__init__.py` — 比对模块导出
- `fabrica/tools/video_dedup/matching/seq_align.py` — 序列对齐打分器
  - `hamming(a, b)` — 计算两个 64bit 指纹的汉明距离
  - `sequence_score(seq_a, seq_b, frame_thresh=8)` — 计算序列相似度（0~1）
    - 对短序列的每一帧，在长序列中找到汉明距离最小的帧
    - 命中比例 = 命中帧数 / 短序列长度
  - 判定阈值：
    - `>= 0.90` → 直接判重（Level 2）
    - `[0.50, 0.90)` → 疑似（进入 L3）
    - `< 0.50` → 不判重

**验收标准**：
- 完全相同的序列返回 1.0
- 完全不同的序列返回 < 0.5
- `hamming(0x0, 0xFFFFFFFFFFFFFFFF)` 返回 64

---

### T4.7 实现 VideoStorage 基础存储层

**任务描述**：管理视频元数据、指纹缓存和结果数据的持久化，实现 SQLite 数据库的基础操作。

**交付物**：
- `fabrica/tools/video_dedup/storage.py` — 存储层
  - SQLite 表结构：
    - `videos` 表（id / path / size / duration / width / height / file_hash / phash_done / deep_done / frame_count）
    - `phash_frames` 表（video_id / frame_idx / ts / phash）
    - `matches` 表（a_id / b_id / level / score）
  - 核心接口：
    - `register_videos(video_list)` — 批量注册视频元信息
    - `videos_without_hash()` — 获取未计算文件哈希的视频
    - `set_hash(video_id, hash_val)` — 设置文件哈希值
    - `group_by_hash()` — 按文件哈希分组
    - `save_phash(video_id, seq, frames)` — 保存 pHash 序列
    - `load_phash(video_id)` — 加载 pHash 序列
    - `save_match(a, b, level, score)` — 保存判重结果
  - 数据库迁移：`SCHEMA_VERSION` 常量 + `migrate()` 函数

**验收标准**：
- `register_videos` 正确插入记录
- `group_by_hash` 正确返回哈希分组
- 数据库迁移脚本正确执行

---

### T4.8 单元测试（阶段四）

**任务描述**：编写阶段四所有模块的单元测试

**交付物**：
- `tests/test_video_dedup/test_sampler.py` — 抽帧模块测试
- `tests/test_video_dedup/test_extractors.py` — 提取器测试（filehash + phash）
- `tests/test_video_dedup/test_phash_index.py` — FAISS 索引测试
- `tests/test_video_dedup/test_seq_align.py` — 序列对齐测试
- `tests/test_video_dedup/test_storage.py` — 存储层测试
- `tests/test_video_dedup/test_tool.py` — 工具注册测试

**验收标准**：测试覆盖率 > 80%

---

## 阶段五：视频验重工具 — L3 + 全流程（第9-10周）

**目标**：实现 CLIP 深度特征提取、深度特征比对、并查集聚类和级联调度器，完成三级级联全流程，并进行集成测试和调参。

### T5.1 实现 CLIP 深度特征提取器（L3）

**任务描述**：使用 OpenCLIP 模型提取视频帧的深度语义特征，用于最终裁决。

**交付物**：
- `fabrica/tools/video_dedup/extractors/deepfeat.py` — CLIP 深度特征提取器
  - `CLIPExtractor` 类
    - `__init__(model_name, pretrained, device, batch_size)` — 初始化模型
    - `extract(pil_images)` — 批量提取帧的深度特征
      - 使用 `open_clip.create_model_and_transforms` 加载模型
      - 模型选择：`ViT-B-32` + `laion2b_s34b_b79k` 预训练权重
      - 输出 `[n, 512]` L2 归一化特征向量（余弦相似度等价于内积）
      - 使用 `torch.no_grad()` 上下文减少显存占用
      - 按 batch_size 分批处理，避免 OOM
    - 模型下载：首次运行自动下载权重（~350MB），缓存到 `~/.cache/clip/`
    - 设备适配：自动检测 CPU/GPU，支持 `get_device()` 配置

**验收标准**：
- `extract` 返回 `[n, 512]` 的 float32 数组
- 输出向量已 L2 归一化（每行范数 ≈ 1.0）
- 相同图片两次调用返回特征向量的余弦相似度 ≈ 1.0
- CPU 环境下正常降级运行

---

### T5.2 实现深度特征比对器（DeepMatcher）

**任务描述**：对进入 L3 的疑似对，用 CLIP 深度特征序列进行余弦相似度比对。

**交付物**：
- `fabrica/tools/video_dedup/matching/deep_match.py` — 深度特征比对器
  - `deep_sequence_score(feat_a, feat_b, sim_thresh=0.92)` — 计算深度特征序列相似度
    - 对短序列的每一帧，在长序列中找到余弦相似度最高的帧
    - 命中比例 = 余弦相似度 > sim_thresh 的帧数 / 短序列长度
    - 使用矩阵内积（`short @ long_.T`）加速比对
  - 判定阈值：
    - `>= 0.85` → 判重（Level 3 最终裁决）
    - `< 0.85` → 不判重

**验收标准**：
- 完全相同特征序列返回 1.0
- 矩阵内积比对结果与逐帧比对一致
- 100 对 × 100 帧场景耗时 < 1s

---

### T5.3 实现并查集聚类器（UnionFindCluster）

**任务描述**：将所有判重关系（视频对）合并为重复组（传递性闭合）。

**交付物**：
- `fabrica/tools/video_dedup/matching/cluster.py` — 并查集聚类器
  - `UnionFind` 类（路径压缩 + 按秩合并）
    - `find(x)` — 查找根节点
    - `union(a, b)` — 合并两个集合
  - `build_groups(n_videos, matches)` — 构建重复组
    - `matches`: `[(a_id, b_id, level, score), ...]`
    - 返回 `list[list[int]]`，每组包含 video_id 列表
    - 仅返回 size > 1 的组（singleton 不输出）
  - `expand_groups(l1_groups, l2_groups)` — 展开 L1 组（将 L1 去重的代表视频替换为全组）

**验收标准**：
- `union(1,2), union(2,3)` → `find(1) == find(3)`
- `build_groups` 正确合并传递性关系
- 路径压缩后查找复杂度接近 O(1)

---

### T5.4 实现级联调度器（CascadePipeline）

**任务描述**：编排三级级联去重流程，管理各阶段的执行顺序、数据传递和结果汇总。

**交付物**：
- `fabrica/tools/video_dedup/pipeline.py` — 级联调度器
  - `CascadePipeline` 类
    - `run_pipeline(cfg, progress_cb, log_cb, cancel_event)` — 执行完整级联流程
      - Stage 0：扫描视频 → 注册到数据库
      - Stage 1：文件哈希（L1）→ 按哈希分组，每组保留代表视频
      - Stage 2：pHash 序列（L2）→ 抽帧 → 计算 pHash → FAISS 索引 → 候选对生成 → 序列对齐打分
      - Stage 3：深度特征（L3）→ 对疑似对提取 CLIP 特征 → 深度特征比对
      - Stage 4：聚类 + 输出 → 并查集合并 → 展开 L1 组 → 输出重复组报告
    - 容错机制：每个视频 try/except，失败跳过继续
    - 取消检查：每个 stage 前检查 `cancel_event`
    - 进度报告：每个 stage 内定时报告进度
  - 返回结果：
    - `total_videos` / `l1_groups` / `l2_pairs` / `l3_pairs` / `final_groups` / `errors`

**验收标准**：
- 10 个测试视频（含重复对）完整流程可运行
- 容错：损坏视频跳过，不影响整体流程
- 取消：执行中取消，任务标记为 CANCELLED
- 结果报告包含所有统计信息

---

### T5.5 完善 VideoStorage 存储层

**任务描述**：完善存储层，支持深度特征的 .npy 文件存储和加载，以及数据库迁移机制。

**交付物**：
- `fabrica/tools/video_dedup/storage.py` 修改
  - 增加 `save_deep(video_id, feats)` — 保存深度特征（存为 .npy 文件）
  - 增加 `load_deep(video_id)` — 加载深度特征
  - 增加 `feature_dir` 配置项（默认为 `data/video_dedup_features`）
  - 数据库迁移：`SCHEMA_VERSION` 检测 + 增量迁移脚本

**验收标准**：
- `save_deep` 后 `load_deep` 返回相同数据
- 特征文件使用 .npy 格式，命名规则 `{video_id}.npy`

---

### T5.6 集成测试与端到端测试

**任务描述**：编写全链路集成测试和端到端测试，验证视频验重工具的完整功能。

**交付物**：
- `tests/test_video_dedup/test_pipeline.py` — 级联调度器集成测试
  - 测试场景：同视频不同分辨率 / 加水印 / 裁剪 / 不同视频
  - 小样本测试：10 个测试视频，验证完整流程
- `tests/fixtures/video_factory.py` — 视频夹具工厂
  - `create_test_video(path, duration, resolution, content)` — 生成测试视频
  - `create_derived_video(src, watermark, crop, resize, transcode)` — 生成派生版本
- `tests/test_video_dedup/test_end_to_end.py` — 端到端测试
  - 工具注册 → 参数校验 → 执行 → 进度报告 → 结果输出 → 取消

**验收标准**：
- 集成测试全部通过，0 失败
- 端到端测试覆盖完整用户流程
- 测试夹具正确生成测试视频

---

### T5.7 调参报告与文档完善

**任务描述**：基于测试结果调整阈值参数，完善项目文档。

**交付物**：
- 调参报告（记录各阈值设置和测试结果）
- `docs/tools/video_dedup.md` 完善（补充实际测试数据）
- 确认所有文档引用与实际代码一致

**验收标准**：
- 阈值参数在测试集上达到 Precision > 0.95, Recall > 0.90
- 文档与代码完全一致

---

## 阶段六：桌面交互功能增强（第11周）

> 详细设计见 [docs/core/desktop_features.md](../core/desktop_features.md)

### T6.1 目录选择器（pywebview 原生对话框）

**任务描述**：用 pywebview 原生文件对话框替代浏览器 `<input type="file">`，使用户能通过点击选择目录并获取完整路径。

**交付物**：
- `fabrica/desktop/__init__.py` — DesktopAPI 类增加 `open_directory_dialog()` 和 `open_file_dialog()` 方法
- `fabrica/server/static/js/components/tool-form.js` — 浏览按钮逻辑改造（pywebview API 优先 + 浏览器回退手动输入）
- 移除隐藏的 `<input type="file">` 和路径截断逻辑

**验收标准**：
- Windows 桌面环境下，video_dedup 工具页"输入目录"点击"浏览"弹出原生目录选择对话框
- 选择目录后文本框填入完整路径（如 `D:\videos`），不截断
- Linux 开发环境（dev_mode）"浏览"按钮提示手动输入，不报错

### T6.2 验重结果结构化展示 + 打开文件夹

**任务描述**：将验重结果从 JSON 文本展示改为结构化重复组卡片，每个视频可点击"打开文件夹"按钮在系统文件管理器中定位。

**交付物**：
- `fabrica/tools/video_dedup/pipeline.py` — `final_groups` 结构改造（从 `List[List[str]]` 改为含视频元信息的 `List[Dict]`）
- `fabrica/tools/video_dedup/storage.py` — 新增 `get_video()` 和 `get_match()` 查询方法
- `fabrica/server/static/js/components/dedup-result.js` — 新建，专门渲染验重结果（重复组卡片+视频路径+打开文件夹按钮）
- `fabrica/server/static/js/components/task-progress.js` — `onComplete` 检测工具类型，调用 `dedup-result.js`
- `fabrica/desktop/__init__.py` — DesktopAPI 增加 `open_in_explorer(path)` 方法
- `fabrica/server/static/css/style.css` — 重复组卡片样式

**验收标准**：
- 验重完成后结果区域展示重复组卡片（非 JSON 文本）
- 每组列出视频路径、大小、时长、分辨率
- 点击"打开文件夹"按钮，系统文件管理器打开并选中对应文件
- 浏览器环境下"打开文件夹"按钮改为复制路径提示

### T6.3 关键帧保存与展示

**任务描述**：判重完成后对重复组视频保存关键帧图像，前端展示关键帧网格并高亮判定为相同的帧对。

**交付物**：
- `fabrica/tools/video_dedup/pipeline.py` — 新增 `_save_keyframes()` 方法（判重后对重复组视频重新抽帧保存 JPEG）和 `_compute_matched_frames()` 方法（利用已有 pHash 计算帧级匹配信息）
- `fabrica/server/__init__.py` — 挂载 `/keyframes` 静态文件目录
- `fabrica/server/static/js/components/dedup-result.js` — 扩展关键帧网格渲染（按视频列排列+高亮匹配帧+点击放大）
- `fabrica/server/static/css/style.css` — 关键帧网格、高亮边框样式

**验收标准**：
- 重复组卡片下方展示关键帧网格，每个视频一列
- 判定为相同的帧对有蓝色高亮边框
- 点击缩略图可放大查看
- `data/keyframes/` 目录下有对应视频的关键帧 JPEG 文件
- 非重复组视频不保存关键帧（磁盘占用合理）

---

## 关键路径

```
T1.1 → T1.2 → T1.3 → T1.4 → T1.5 → T1.6 → T1.7 → T1.8
                                                    ↓
      T2.1 → T2.2 → T2.3 → T2.4 → T2.5 → T2.6 → T2.7
                                                    ↓
            T3.1 → T3.2 → T3.3 → T3.4 → T3.5 → T3.6
                                                  ↓
            T4.1 → T4.2 → T4.3 → T4.4 → T4.5 → T4.6 → T4.7 → T4.8
                                                                  ↓
                  T5.1 → T5.2 → T5.3 → T5.4 → T5.5 → T5.6 → T5.7
                                                                ↓
                        T6.1 → T6.2 → T6.3
```

**并行可能性**：
- T1.2/T1.3/T1.4 可并行开发（均无依赖）
- T1.5/T1.6/T1.7 可并行开发（均无依赖，T1.7 脚本系统与设备检测/工具函数独立）
- T2.1/T2.2 可并行开发（ToolBase + ParamDef 独立）
- T4.2/T4.3/T4.4 可并行开发（Sampler + FileHash + PHash 独立）
- T4.5/T4.6/T4.7 可并行开发（FAISS 索引 + 序列对齐 + 存储层独立）
- T5.1/T5.2/T5.3 可并行开发（CLIP 提取 + 深度比对 + 聚类独立）

---

## 验收标准

### 功能验收

| 检查项 | 验收标准 |
|--------|---------|
| 日志系统正常工作 | 控制台彩色输出 + 文件轮转 + 模块日志区分 |
| 配置管理正常工作 | YAML 配置加载 + 配置项查询 + 重新加载 |
| 异常体系完整 | 12+ 具体异常类 + 统一错误响应格式 |
| 设备检测正确 | CPU/GPU 自动检测 + batch_size 建议 |
| 工具函数正确 | 格式化/路径操作/哈希计算全部正确 |
| ToolBase 基类可用 | 继承 + 抽象方法约束 + 生命周期钩子 |
| ParamDef 参数系统完整 | 10 种类型 + 6 种校验规则 + 前端表单渲染 |
| TaskContext 上下文完整 | 进度报告 + 日志 + 取消信号 + 临时目录 |
| TaskStateMachine 状态机正确 | 8 状态 + 9 条合法转换 + 非法转换拒绝 |
| ToolRegistry 注册中心完整 | 装饰器注册 + 自动发现 + 异步执行 + 取消 |
| hestia 资源池集成 | 最大 2 并发 + 超时控制 + 优雅关闭 |
| REST API 7 端点可用 | 所有端点返回正确 Pydantic 模型 |
| WebSocket 实时推送 | 进度/日志/完成/错误事件推送 + 心跳 |
| SPA 前端 5 页面 | Hash 路由 + 表单渲染 + 实时进度 |
| 桌面窗口集成 | exe 弹出 pywebview 窗口（无控制台）+ 窗口关闭优雅退出 + Linux dev_mode 浏览器回退 |
| Sampler 抽帧正确 | 自适应采样 + 精确 seek + 容错 |
| L1 文件哈希 | MD5 计算 + 分块读取 + 哈希分组 |
| L2 pHash 序列 | 64bit 指纹 + FAISS 二进制索引 + 序列对齐打分 |
| L3 CLIP 深度特征 | 512 维向量 + L2 归一化 + 余弦相似度比对 |
| 并查集聚类 | 传递性合并 + 路径压缩 + 展开 L1 组 |
| CascadePipeline 级联调度 | 5 级流程编排 + 容错 + 取消 + 进度报告 |
| VideoStorage 存储层 | SQLite + .npy 特征文件 + 数据库迁移 |
| 目录选择器 | pywebview 原生对话框获取完整路径 + 浏览器回退手动输入 |
| 结果结构化展示 | 重复组卡片（视频路径+元信息）+ 打开文件夹按钮 + 工具类型路由 |
| 关键帧展示 | 重复组关键帧网格 + 匹配帧高亮 + 点击放大 + 仅保存重复组帧 |

### 性能验收

| 检查项 | 验收标准 |
|--------|---------|
| 10 个测试视频完整流程 | < 5 分钟（CPU 环境） |
| Sampler 抽帧（5 分钟视频） | < 10 秒 |
| L2 FAISS 检索（100 视频 × 100 帧） | < 5 秒 |
| L3 特征比对（100 对 × 100 帧） | < 1 秒 |
| 线程池并发控制 | 超过 2 个 CPU 任务排队 |
| SPA 前端页面加载 | < 1 秒 |
| REST API 响应时间 | < 100ms（不含工具执行） |

### 质量验收

| 检查项 | 验收标准 |
|--------|---------|
| 单元测试覆盖率 | > 80% |
| 集成测试全部通过 | 0 失败 |
| 端到端测试全部通过 | 0 失败 |
| 无严重 Bug | 0 严重问题 |
| 容错机制正常 | 损坏视频跳过 + 单工具失败不影响平台 |

---

## 后续规划

### 第二阶段：平台增强

- **批量任务队列**：支持工具任务的排队、暂停、取消、历史查看
- **工具配置持久化**：每个工具的配置参数可保存为"方案"，下次复用
- **结果导出**：统一的结果导出机制（JSON/CSV/Excel）
- **更多工具**：按需添加新工具（文件整理、格式转换、数据清洗等）
- **工具依赖注入**：支持工具之间共享数据（一个工具的输出作为另一个工具的输入）

### 第三阶段：体验提升

- **暗色主题 / 多主题**：前端 CSS 自定义属性主题切换
- **任务通知**：长时间任务完成后系统通知
- **进度可视化**：实时进度条、日志流式展示
- **Electron 壳**：可选，提供更原生的桌面体验
- **OpenAPI 文档**：集成 FastAPI 自动生成的 Swagger UI

### 长线规划

- **工具热加载**：修改工具代码后无需重启平台
- **工具性能监控**：记录每个工具的执行时间、内存使用、GPU 显存
- **工具沙箱**：可选的进程隔离模式，支持不安全工具的安全执行
- **多语言支持**：前端 i18n 国际化
- **响应式布局**：适配移动端和平板

---

**文档结束**