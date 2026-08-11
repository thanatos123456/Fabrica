# Fabrica

> *"Fabrica"*——拉丁语，意为「工坊」。如同工匠的工坊中陈列着各式趁手工具，此处汇聚各类实用功能，从视频验重到更多未知可能。

---

## 1. 项目概述

### 1.1 背景

日常开发与工作中，经常遇到零散的实用需求——批量视频验重、文件整理、格式转换、数据清洗……每类需求单独建一个项目太重，散落在脚本里又难复用。需要一个统一的工具集平台，将各类实用功能以"工具"的形式组织起来，每个工具独立开发、独立维护，共享统一的运行环境与用户界面。

### 1.2 核心目标

**构建一个可扩展的桌面工具集平台** — 以 Windows EXE 为主要分发形态，提供图形化功能界面，让用户通过点选即可进入各工具完成具体任务；同时保证在 Linux 开发环境中可以完整测试所有功能。

### 1.3 核心价值

| 价值点 | 说明 |
|--------|------|
| **统一入口** | 一个应用汇集所有工具，避免功能散落在不同项目与脚本中 |
| **即开即用** | 图形界面，无需命令行操作，降低使用门槛 |
| **插件化扩展** | 新工具只需继承基类注册即可接入，与平台解耦 |
| **跨平台可测** | 同一套代码在 Linux 下可完整开发测试，Windows 下打包分发 |
| **共享基建** | 日志、配置、存储、UI 组件等公共能力由平台统一提供 |
| **渐进增强** | 单机版先行，后续可扩展网络协同、批量任务调度等能力 |

### 1.4 边界

**做：**
- 桌面级图形化工具集平台，以 Web 前端作为 GUI 方案
- 插件化工具注册机制，工具与平台解耦
- 首个工具：批量视频验重（详见 [docs/tools/video_dedup.md](./docs/tools/video_dedup.md)）
- 工具之间数据隔离，运行环境共享
- Linux 开发环境完整测试 → Windows PyInstaller 打包分发

**不做（初期）：**
- 多用户/权限管理
- 分布式任务调度
- 云端部署与在线服务
- 移动端适配

---

## 2. 架构设计

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                       用户界面层                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │               Web 前端（本地浏览器渲染）                  │  │
│  │  工具首页（卡片式入口） → 工具详情页 → 参数配置 → 执行  │  │
│  │  HTML + CSS + JS（无前端框架依赖，轻量可替换）           │  │
│  └──────────────────────┬─────────────────────────────────┘  │
│                         │ HTTP / WebSocket (localhost)        │
│  ┌──────────────────────▼─────────────────────────────────┐  │
│  │                API 服务层（FastAPI）                     │  │
│  │  REST 端点 + WebSocket 端点 + 静态资源服务               │  │
│  └──────────────────────┬─────────────────────────────────┘  │
└─────────────────────────┼────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│                      工具插件层                               │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              ToolRegistry（工具注册中心）                │  │
│  │  自动扫描 fabrica/tools/ → 装饰器注册 → 依赖注入       │  │
│  └──────┬──────────────┬──────────────┬───────────────────┘  │
│         │              │              │                      │
│  ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐            │
│  │  VideoDedup │ │  (待开发)   │ │  (待开发)   │   ...      │
│  │  视频验重    │ │  工具B      │ │  工具C      │            │
│  └─────────────┘ └─────────────┘ └─────────────┘            │
│                                                              │
└─────────────────────────┬────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│                      公共基础设施层                            │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ 配置管理  │  │ 日志系统  │  │ 数据存储 │  │ 设备检测 │     │
│  │ (YAML)   │  │ (loguru) │  │ (SQLite) │  │ (CPU/GPU)│     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 请求生命周期时序图

```
用户浏览器              API 服务层              工具注册中心            工具实例            存储层
    │                      │                      │                  │                  │
    │ 1. GET /api/tools     │                      │                  │                  │
    │─────────────────────▶│── list_tools()──────▶│                  │                  │
    │◀─────────────────────│◀──── tool_list ──────│                  │                  │
    │                      │                      │                  │                  │
    │ 2. 展示工具卡片列表   │                      │                  │                  │
    │                      │                      │                  │                  │
    │ 3. GET /api/tools/    │                      │                  │                  │
    │    video_dedup        │                      │                  │                  │
    │─────────────────────▶│── get_schema()──────▶│                  │                  │
    │◀─────────────────────│◀── param_defs ──────│                  │                  │
    │                      │                      │                  │                  │
    │ 4. 用户填写参数并提交  │                      │                  │                  │
    │                      │                      │                  │                  │
    │ 5. POST /api/tools/   │                      │                  │                  │
    │    video_dedup/run    │                      │                  │                  │
    │─────────────────────▶│── validate(params)──▶│                  │                  │
    │                      │◀─ validation_ok ────│                  │                  │
    │                      │                      │                  │                  │
    │ 6. 返回 task_id       │                      │                  │                  │
    │◀─────────────────────│                      │                  │                  │
    │                      │                      │                  │                  │
    │ 7. 前端连接 WebSocket │                      │                  │                  │
    │═════════════════════▶│                      │                  │                  │
    │                      │ 注册进度/日志回调     │                  │                  │
    │                      │────────────────────▶│                  │                  │
    │                      │                      │                  │                  │
    │ 8. asyncio.create_task│                      │                  │                  │
    │    (后台异步执行)      │                      │                  │                  │
    │                      │── run(params, ctx)──▶│ 9. 执行工具逻辑   │                  │
    │                      │                      │  (asyncio.       │                  │
    │                      │                      │   to_thread)     │                  │
    │                      │                      │─────────────────▶│                  │
    │10. progress(30%,     │                      │                  │                  │
    │    "抽帧中...")       │                      │◀─────────────────│                  │
    │◀═════════════════════│══════════════════════│                  │                  │
    │                      │                      │                  │                  │
    │11. progress(80%,     │                      │                  │                  │
    │    "比对中...")       │                      │─────────────────▶│                  │
    │◀═════════════════════│══════════════════════│                  │                  │
    │                      │                      │                  │─ save_results ──▶│
    │                      │                      │◀─────────────────│                  │
    │12. 任务完成           │                      │                  │                  │
    │◀═════════════════════│══════════════════════│                  │                  │
    │                      │                      │                  │                  │
    │13. 展示结果           │                      │                  │                  │
```

### 2.3 工具注册中心内部类图

```
┌─────────────────────────────────────────────────────────────────┐
│                    ToolRegistry（注册中心）                       │
│                                                                 │
│  - _tools: dict[str, type[ToolBase]]     # 名称 → 工具类        │
│  - _instances: dict[str, ToolBase]       # 名称 → 工具实例      │
│  - _tool_dirs: list[Path]                # 扫描目录列表          │
│                                                                 │
│  + register(cls) -> type[ToolBase]       # 装饰器注册方法        │
│  + discover() -> int                     # 自动扫描目录发现工具  │
│  + get_tool(name) -> ToolBase            # 获取工具实例          │
│  + list_tools() -> list[ToolMeta]        # 列出所有工具元信息    │
│  + get_schema(name) -> list[ParamDef]    # 获取工具参数定义      │
│  + run_tool(name, params, cb) -> Task    # 运行工具（异步）      │
│  + cancel_task(task_id) -> bool          # 取消运行中的任务      │
│                                                                 │
└──────────────────────┬──────────────────────────────────────────┘
                       │ 注册
          ┌────────────┼────────────┐
          ▼            ▼            ▼
┌─────────────────┐ ┌───────────┐ ┌───────────┐
│   @tool.register│ │  @tool.   │ │  @tool.   │
│   class ToolA   │ │  register │ │  register │
│                 │ │  ToolB    │ │  ToolC    │
│  name = "a"     │ │           │ │           │
│  title = "工具A" │ │           │ │           │
└─────────────────┘ └───────────┘ └───────────┘
                       │
                       ▼
          ┌─────────────────────────┐
          │      ToolBase           │
          │  （抽象基类）            │
          │                         │
          │  类属性:                │
          │  ├── name: str          │
          │  ├── title: str         │
          │  ├── description: str   │
          │  ├── icon: str          │
          │  └── params: list       │
          │                         │
          │  实例方法:              │
          │  ├── on_init()          │
          │  ├── validate(params)   │
          │  ├── run(params, ctx)   │
          │  ├── on_cancel()        │
          │  └── on_complete()      │
          └─────────────────────────┘
```

### 2.4 GUI 方案选型

| 方案 | 说明 |
|------|------|
| **pywebview 桌面窗口（选用）** | 本地 FastAPI 服务 + pywebview 原生窗口壳。Windows 打包后双击 exe 直接弹出独立桌面窗口（隐藏控制台），内嵌 WebView 渲染现有 Web 前端；Linux 开发环境回退为浏览器自动打开。复用 Python 技术栈，体积增量小。 |
| Web 前端 + 系统浏览器 | 本地 FastAPI 服务 + 浏览器渲染。实现简单，但浏览器标签页缺乏"软件"感，关闭标签不退出进程，不符合桌面应用心智。 |
| PyQt/PySide | 原生桌面体验好，但打包体积大，依赖较复杂，开发调试不如 Web 灵活。 |
| Tkinter | 标准库无需额外依赖，但 UI 表现力有限，难以构建现代化的工具界面。 |
| Electron/Tauri | 最原生的桌面体验，但需引入 Node.js/Rust 生态，工程量大。作为未来可选升级方向。 |

选择 pywebview 桌面窗口方案的核心原因：**Linux 开发与 Windows 部署使用完全相同的代码**，无需为不同平台维护两套 GUI 实现；exe 打开后直接弹出原生窗口，符合"像样的软件界面"的用户期望；前端轻量可替换，未来可平滑过渡到 Electron 或 Tauri 等原生壳。

> 详细的桌面集成设计见 [docs/core/desktop_integration.md](./docs/core/desktop_integration.md)。

### 2.5 前端路由设计

```
/                          → 工具首页（卡片式网格展示所有注册工具）
/tool/:id                  → 工具详情页（展示描述 + 参数配置表单）
/tool/:id/run              → 工具执行页（实时进度 + 日志流 + 结果展示）
/tasks                     → 任务历史页（历史任务列表）
/tasks/:id                 → 任务详情页（单任务完整状态与结果）
```

前端为单页应用（SPA），通过 Hash 路由或 History API 实现，无前端框架依赖。

---

## 3. 首个工具：批量视频验重

详见独立的 [视频重复检测系统详细设计文档](./docs/tools/video_dedup.md)，此处仅概述。

### 3.1 功能概要

| 项 | 内容 |
|----|------|
| 核心功能 | 在最多 5 万个视频中，找出画面内容相同（含转码/水印/裁剪/缩放差异）的视频组 |
| 检测策略 | 三级级联：文件哈希(L1) → pHash 序列(L2) → CLIP 深度特征(L3) |
| 优先级 | **准确率 > 速度** |
| 开发环境 | Linux，无 GPU |
| 运行环境 | Windows，有 GPU（代码同一套，设备自动适配） |

### 3.2 级联流程

```
Stage 0: 扫描所有视频 → 建立 video_id
Stage 1: 算 filehash → 完全相同的直接分组，剔除
Stage 2: 对剩余视频抽帧算 pHash 序列 → FAISS 汉明检索 → 序列对齐打分
Stage 3: 疑似对 → CLIP 深度特征作为最终裁决
Stage 4: 并查集合并 → 输出重复组
```

---

## 4. 工具插件系统详细设计

### 4.1 ToolBase 抽象基类

所有工具必须继承 `ToolBase` 并实现以下接口。平台通过 `ToolBase` 的类型系统自动生成前端参数表单、校验规则、执行调度。

#### 4.1.1 类属性（工具元信息）

| 属性 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `name` | `str` | 是 | 工具唯一标识符（snake_case），用于路由和注册 |
| `title` | `str` | 是 | 工具显示名称，用于前端展示 |
| `description` | `str` | 是 | 功能描述文本，支持 Markdown 子集 |
| `icon` | `str` | 否 | 图标（emoji 字符 或 图标文件路径），默认 `🔧` |
| `params` | `list[ParamDef]` | 否 | 参数定义列表，自动生成前端配置表单 |
| `version` | `str` | 否 | 工具版本号，默认 `"1.0.0"` |
| `category` | `str` | 否 | 工具分类标签，用于前端分组展示 |

#### 4.1.2 生命周期钩子

| 方法 | 触发时机 | 返回值 | 说明 |
|------|---------|--------|------|
| `on_init()` | 工具实例首次创建时 | `None` | 初始化资源（加载模型、建立连接等），只执行一次 |
| `validate(params)` | 用户提交参数后、执行前 | `list[str]` | 参数校验，返回错误列表（空列表表示通过） |
| `run(params, ctx)` | 校验通过后 | `dict` | 核心执行逻辑，通过 `ctx` 报告进度并接收取消信号 |
| `on_cancel()` | 用户取消任务时 | `None` | 清理资源（释放 GPU 显存、关闭文件句柄等） |
| `on_complete(result)` | 执行正常结束时 | `None` | 收尾处理（发送通知、清理临时文件等） |

#### 4.1.3 执行上下文（TaskContext）

`run()` 方法接收的 `ctx` 参数提供以下能力：

```python
@dataclass
class TaskContext:
    task_id: str                    # 全局唯一任务 ID（UUID）
    params: dict                    # 参数快照（用户提交时的深拷贝）
    temp_dir: Path                  # 工具专属临时目录，任务结束后自动清理

    async def report_progress(self, percent: float, message: str = ""):
        """报告进度（0-100），自动推送到前端 WebSocket"""

    async def log(self, level: str, message: str):
        """写入工具日志，同时推送到前端 WebSocket"""

    @property
    def cancelled(self) -> bool:
        """检查用户是否已取消任务"""

    def get_data_dir(self) -> Path:
        """获取工具持久化数据目录（跨任务共享）"""
```

### 4.2 ParamDef 参数定义系统

`ParamDef` 定义了一个参数的元信息，前端据此自动渲染表单控件。

#### 4.2.1 支持的类型

| 类型标识 | 前端控件 | 说明 |
|---------|---------|------|
| `str` | 文本输入框 | 普通字符串 |
| `int` | 数字输入框（整数） | 整数类型 |
| `float` | 数字输入框（浮点） | 浮点数类型 |
| `bool` | 复选框 | 布尔开关 |
| `path` | 路径选择器（文件/目录） | 文件系统路径 |
| `file` | 文件选择器 | 单个文件路径 |
| `dir` | 目录选择器 | 目录路径 |
| `select` | 下拉选择框 | 单选枚举 |
| `multi_select` | 多选下拉框 | 多选枚举 |
| `password` | 密码输入框 | 敏感信息，前端掩码显示 |

#### 4.2.2 ParamDef 定义规范

```python
@dataclass
class ParamDef:
    key: str                          # 参数键名，用于 params 字典
    label: str                        # 显示标签
    type: str                         # 参数类型（见上表）
    default: Any = None               # 默认值
    required: bool = True             # 是否必填
    description: str = ""             # 帮助文本
    placeholder: str = ""             # 输入框占位符
    options: list[tuple[str, str]] | None = None  # select/multi_select 的选项列表 (value, label)
    validation: dict | None = None    # 额外校验规则（见 4.2.3）
```

#### 4.2.3 校验规则（validation 字典）

| 规则键 | 适用类型 | 说明 |
|--------|---------|------|
| `min` | int, float | 最小值 |
| `max` | int, float | 最大值 |
| `min_length` | str | 最小长度 |
| `max_length` | str | 最大长度 |
| `pattern` | str | 正则表达式匹配 |
| `file_extensions` | file, path | 允许的文件扩展名列表，如 `[".mp4", ".avi"]` |

### 4.3 任务状态机

每个工具执行实例是一个"任务"，经历以下状态流转：

```
                ┌──────────┐
                │  PENDING  │  ← 任务创建，等待调度
                └────┬─────┘
                     │ 调度执行
                     ▼
                ┌───────────┐
                │ VALIDATING │  ← 参数校验（调用 validate()）
                └─────┬─────┘
             ┌────────┴────────┐
             ▼                 ▼
        ┌─────────┐     ┌──────────┐
        │ VALID   │     │ INVALID  │  ← 参数校验失败，返回错误信息
        └────┬────┘     └──────────┘
             │ 开始执行
             ▼
        ┌─────────┐
        │ RUNNING  │  ← 执行中（可取消）
        └────┬────┘
     ┌───────┼───────┐
     ▼       ▼       ▼
 ┌───────┐ ┌───────┐ ┌──────────┐
 │COMPLTD│ │CANCELL│ │  FAILED  │
 │(成功)  │ │(用户取消)│ │(异常终止)│
 └───────┘ └───────┘ └──────────┘
```

**状态转换矩阵**：

| 当前状态 | 合法下一状态 | 触发条件 |
|---------|------------|---------|
| PENDING | VALIDATING | 调度器开始执行 |
| VALIDATING | VALID / INVALID | 校验完成 |
| VALID | RUNNING | 执行开始 |
| RUNNING | COMPLETED / CANCELLED / FAILED | 执行结束 / 用户取消 / 异常 |
| INVALID | — | 终态 |
| COMPLETED | — | 终态 |
| CANCELLED | — | 终态 |
| FAILED | — | 终态 |

### 4.4 异步执行调度

状态机定义了"做什么"，调度机制决定了"怎么做"。工具执行调度遵循以下原则：

#### 4.4.1 调度策略

```
用户提交请求 → run_tool() 返回 task_id（立即返回，不阻塞）
                       │
            ┌──────────┴──────────┐
            │  asyncio.create_task() │  ← 后台异步执行
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │  状态机流转          │
            │  PENDING → VALIDATING │
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │  validate() 校验参数  │
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │  VALID → RUNNING    │
            │  asyncio.to_thread() │  ← CPU 密集型任务放入线程池
            │  或直接 await        │  ← IO 密集型任务直接执行
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │  run() 执行工具逻辑   │
            │  report_progress()   │  ← 通过回调推送进度到 WebSocket
            │  cancelled 检查取消   │  ← 响应取消信号
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │  COMPLETED / FAILED  │
            │  / CANCELLED         │
            └─────────────────────┘
```

#### 4.4.2 执行模式选择

| 工具类型 | 调度方式 | 说明 |
|---------|---------|------|
| **IO 密集型**（如网络请求） | 直接 `await` | 在事件循环中执行，不阻塞其他请求 |
| **CPU 密集型**（如视频验重） | `asyncio.to_thread()` | 放入线程池执行，释放事件循环 |
| **GPU 密集型**（如深度学习推理） | `asyncio.to_thread()` | PyTorch/FAISS 在执行时会释放 GIL，线程池安全 |

#### 4.4.3 线程池配置

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 全局线程池，限制并发工具数
_tool_executor = ThreadPoolExecutor(max_workers=2)

async def _execute_tool(tool, params, ctx):
    # CPU 密集型工具在后台线程执行
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _tool_executor,
        tool.run_sync,  # 工具的实际同步执行入口
        params, ctx,
    )
    return result
```

#### 4.4.4 取消机制

当用户取消任务时，`ToolRegistry.cancel_task()` 设置取消事件。工具在执行中通过 `ctx.cancelled` 检查该信号，主动退出。`asyncio.to_thread` 不会自动响应取消信号，因此工具需在耗时循环中定期检查 `ctx.cancelled`。

### 4.5 工具注册与发现

#### 装饰器注册

```python
# fabrica/tools/my_tool/__init__.py
from fabrica.tool import tool, ToolBase, ParamDef

@tool.register
class MyTool(ToolBase):
    name = "my_tool"
    title = "我的工具"
    description = "示例工具，展示如何注册新工具"
    icon = "🧰"
    version = "1.0.0"
    category = "工具示例"

    params = [
        ParamDef(key="input_path", label="输入路径", type="path",
                 required=True, description="请选择要处理的文件或目录"),
        ParamDef(key="threshold", label="相似度阈值", type="float",
                 default=0.8, validation={"min": 0.0, "max": 1.0}),
    ]

    async def on_init(self):
        self._model = None  # 延迟初始化

    async def validate(self, params):
        errors = []
        if not params.get("input_path"):
            errors.append("输入路径不能为空")
        return errors

    async def run(self, params, ctx):
        await ctx.report_progress(0, "开始处理...")
        # 核心逻辑
        for i in range(10):
            if ctx.cancelled:
                return {"status": "cancelled"}
            await ctx.report_progress((i + 1) * 10, f"处理第 {i+1}/10 步")
            await asyncio.sleep(0.5)
        return {"status": "success", "result": "处理完成"}
```

#### 自动扫描发现

平台启动时扫描 `fabrica/tools/` 目录下的所有子包，自动导入并注册带有 `@tool.register` 装饰器的类：

```python
# 扫描逻辑示意
def discover_tools(tool_dirs: list[Path]) -> int:
    count = 0
    for tool_dir in tool_dirs:
        for entry in tool_dir.iterdir():
            if entry.is_dir() and (entry / "__init__.py").exists():
                module = importlib.import_module(
                    f"fabrica.tools.{entry.name}"
                )
                # @tool.register 装饰器会自动调用 ToolRegistry.register()
                count += 1
    return count
```

---

## 5. API 规范

### 5.1 REST 端点

| 方法 | 路径 | 请求体 | 响应体 | 说明 |
|------|------|--------|--------|------|
| `GET` | `/api/tools` | — | `List[ToolMeta]` | 获取所有已注册工具的元信息列表 |
| `GET` | `/api/tools/{name}` | — | `ToolDetail` | 获取单个工具的详细信息（含参数定义） |
| `POST` | `/api/tools/{name}/run` | `RunRequest` | `RunResponse` | 提交工具执行请求，返回任务 ID |
| `GET` | `/api/tasks` | — | `List[TaskSummary]` | 获取任务历史列表 |
| `GET` | `/api/tasks/{id}` | — | `TaskDetail` | 获取单个任务的完整状态和结果 |
| `POST` | `/api/tasks/{id}/cancel` | — | `CancelResponse` | 取消正在执行的任务 |
| `DELETE` | `/api/tasks/{id}` | — | — | 删除任务记录 |

### 5.2 请求/响应 Schema

```python
# 请求模型
class RunRequest(BaseModel):
    params: dict  # 参数键值对

class CancelResponse(BaseModel):
    success: bool
    task_id: str

# 响应模型
class ToolMeta(BaseModel):
    name: str
    title: str
    description: str
    icon: str
    version: str
    category: str

class ToolDetail(ToolMeta):
    params: list[ParamDefSchema]

class RunResponse(BaseModel):
    task_id: str
    status: str  # "pending"

class TaskSummary(BaseModel):
    task_id: str
    tool_name: str
    status: str          # pending / validating / running / completed / failed / cancelled
    progress: float      # 0-100
    created_at: datetime
    completed_at: datetime | None

class TaskDetail(TaskSummary):
    params: dict         # 执行参数快照
    result: dict | None  # 执行结果
    error: str | None    # 错误信息
    logs: list[LogEntry] # 执行日志
```

### 5.3 WebSocket 端点

| 端点 | 事件 | 说明 |
|------|------|------|
| `WS /api/ws/tasks/{id}` | `progress` | 实时进度推送 `{percent: float, message: str}` |
| | `log` | 实时日志推送 `{level: str, message: str, timestamp: str}` |
| | `complete` | 任务完成通知 `{result: dict}` |
| | `error` | 任务异常通知 `{error: str}` |

### 5.4 统一错误响应

所有 API 错误使用统一格式：

```json
{
    "error": {
        "code": "PARAM_INVALID",
        "message": "参数校验失败",
        "details": {
            "input_path": ["输入路径不能为空"]
        }
    }
}
```

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| `TOOL_NOT_FOUND` | 404 | 工具不存在 |
| `PARAM_INVALID` | 422 | 参数校验失败 |
| `TASK_NOT_FOUND` | 404 | 任务不存在 |
| `TASK_CANCELLED` | 409 | 任务已被取消 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |

---

## 6. 配置规范

### 6.1 平台配置

`config.yaml` 顶层配置（📝 待创建）：

```yaml
fabrica:
  server:
    host: "127.0.0.1"          # 监听地址
    port: 8520                  # 监听端口
    cors_origins: ["*"]         # CORS 允许的源
    static_dir: "server/static" # 前端静态资源目录

  logging:
    level: "INFO"               # DEBUG / INFO / WARNING / ERROR
    dir: "logs"                 # 日志目录
    rotation: "1 day"           # 日志轮转周期
    retention: "30 days"        # 日志保留时间

  storage:
    db_path: "data/fabrica.db"  # SQLite 数据库路径
    temp_dir: "data/tmp"        # 临时文件目录
    data_dir: "data/tools"      # 工具持久化数据目录

  tools:
    dirs: ["fabrica/tools"]     # 工具扫描目录
    auto_discover: true         # 是否自动扫描发现工具
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `fabrica.server.host` | str | `"127.0.0.1"` | 服务监听地址 |
| `fabrica.server.port` | int | `8520` | 服务监听端口 |
| `fabrica.server.cors_origins` | list | `["*"]` | CORS 允许的源 |
| `fabrica.server.static_dir` | str | `"server/static"` | 前端静态资源目录 |
| `fabrica.logging.level` | str | `"INFO"` | 日志级别 |
| `fabrica.logging.dir` | str | `"logs"` | 日志目录 |
| `fabrica.logging.rotation` | str | `"1 day"` | 日志轮转周期 |
| `fabrica.logging.retention` | str | `"30 days"` | 日志保留时间 |
| `fabrica.storage.db_path` | str | `"data/fabrica.db"` | SQLite 数据库路径 |
| `fabrica.storage.temp_dir` | str | `"data/tmp"` | 临时文件目录 |
| `fabrica.storage.data_dir` | str | `"data/tools"` | 工具持久化数据目录 |
| `fabrica.tools.dirs` | list | `["fabrica/tools"]` | 工具扫描目录列表 |
| `fabrica.tools.auto_discover` | bool | `true` | 是否自动扫描发现工具 |

### 6.2 工具配置

每个工具可以在 `config.yaml` 中拥有独立的配置节，平台在加载工具时注入：

```yaml
tools:
  video_dedup:
    default_params:
      min_frames: 16
      max_frames: 200
      target_fps: 1.0
    device: "auto"              # auto / cpu / cuda
    deep:
      model_name: "ViT-B-32"
      batch_size: 64
    l2:
      frame_thresh: 8
      confirm: 0.90
      suspect: 0.50
    l3:
      sim_thresh: 0.92
      confirm: 0.85
```

---

## 7. 开发指南

### 7.1 环境准备

```bash
# 克隆项目后进入目录
cd nexus/Fabrica

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装基础依赖
pip install -r requirements.txt  # 📝 待创建
```

### 7.2 启动开发服务器

```bash
# 启动 Fabrica 服务（默认 http://localhost:8520）
python main.py

# 指定端口
python main.py --port 8520
```

### 7.3 运行测试

```bash
# 运行所有测试
pytest tests/

# 仅测试视频验重工具
pytest tests/tools/test_video_dedup/

# 用小样本测试级联流程
pytest tests/tools/test_video_dedup/ -k "test_pipeline_small"
```

### 7.4 添加新工具

详见 §4.4 工具注册与发现章节的代码示例。

---

## 8. 构建与分发

### 8.1 Windows EXE 构建

打包在 **Windows 环境** 中执行（PyInstaller 不支持交叉编译）：

```bash
# 安装打包依赖
pip install pyinstaller pywebview

# 执行打包（onedir 单目录模式）
pyinstaller build_win.spec --clean

# 产物在 dist/fabrica/ 目录，整个目录分发给用户
```

`build_win.spec` 关键配置（完整文件见仓库根目录）：

```python
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

_FABRICA_ROOT = os.path.abspath(SPECPATH)
# aurora 本地包（helios/nemesis/phoenix/hestia）位于 <OmniPivot>/aurora/python
_OMNIPIVOT_ROOT = os.path.abspath(os.path.join(_FABRICA_ROOT, "..", "..", ".."))
_AURORA_PYTHON = os.path.join(_OMNIPIVOT_ROOT, "aurora", "python")

a = Analysis(
    [os.path.join(_FABRICA_ROOT, "main.py")],
    pathex=[_FABRICA_ROOT, _AURORA_PYTHON],
    binaries=[],
    datas=(
        collect_data_files("fabrica.server", includes=["static/**"])  # 静态资源
        + [(os.path.join(_FABRICA_ROOT, "config", "config.yaml"), ".")]  # 配置
    ),
    hiddenimports=(
        ["aurora.python.helios", "aurora.python.nemesis",
         "aurora.python.phoenix", "aurora.python.hestia"]  # 本地 aurora 包
        + collect_submodules("fabrica.tools.video_dedup")   # 工具子模块
        + ["open_clip", "faiss", "av"]                      # 第三方重依赖
        + ["pywebview", "pywebview.platforms.winforms"]     # 桌面窗口壳
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='fabrica', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,  # 桌面应用隐藏控制台，由 pywebview 窗口展示界面
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[], name="fabrica",
)
```

### 8.2 分发方式

| 方式 | 适用场景 | 说明 |
|------|---------|------|
| **PyInstaller 单目录** | 最终用户 | 推荐，onedir 模式避免 onefile 对大型依赖的兼容问题 |
| 便携式 Python 环境 | 技术用户 | conda-pack 打包，zip 分发 + 启动脚本 |
| 源码运行 | 开发者 | `pip install -r requirements.txt` + `python main.py` |

---

## 9. 项目结构

```
nexus/Fabrica/
│
├── README.md                       # 本文件
├── requirements.txt                # 依赖清单 📝 待创建
├── config.yaml                     # 平台配置文件 📝 待创建
├── build_win.spec                  # PyInstaller 打包配置（Windows onedir）
├── main.py                         # 主入口文件 📝 待创建
│
├── scripts/                        # 管理脚本 📝 待创建
│   ├── common.sh                   # 公共函数库
│   ├── run.sh                      # 服务管理（start/stop/restart/status）
│   └── dev.sh                      # 开发辅助（setup/test/serve）
│
├── fabrica/                        # 主包 📝 待创建
│   ├── __init__.py
│   ├── app.py                      # 应用启动（FastAPI 服务）
│   ├── config.py                   # 配置管理（pydantic + yaml）
│   ├── tool.py                     # 工具基类 + 注册中心
│   │
│   ├── server/                     # Web 服务层 📝 待创建
│   │   ├── __init__.py
│   │   ├── routes.py               # API 路由定义
│   │   └── static/                 # 前端静态资源
│   │       ├── index.html          # 工具首页
│   │       ├── css/
│   │       └── js/
│   │
│   ├── desktop/                    # 桌面集成层（pywebview 窗口壳）
│   │   └── __init__.py             # 桌面启动器（launch_window / launch_browser）
│   │
│   ├── tools/                      # 工具插件目录 📝 待创建
│   │   ├── __init__.py
│   │   ├── video_dedup/            # 视频验重工具 📝 待创建
│   │   │   ├── __init__.py
│   │   │   ├── config.py           # 工具配置
│   │   │   ├── pipeline.py         # 级联调度器
│   │   │   ├── sampler.py          # 抽帧模块
│   │   │   ├── device.py           # 设备自动检测
│   │   │   ├── extractors/         # 指纹提取
│   │   │   │   ├── filehash.py     # L1 文件哈希
│   │   │   │   ├── phash.py        # L2 pHash
│   │   │   │   └── deepfeat.py     # L3 CLIP 特征
│   │   │   ├── indexing/           # 索引与检索
│   │   │   │   ├── phash_index.py  # FAISS 二进制索引
│   │   │   │   └── deep_index.py   # FAISS 向量索引
│   │   │   ├── matching/           # 比对与聚类
│   │   │   │   ├── seq_align.py    # 序列对齐打分
│   │   │   │   ├── deep_match.py   # 深度特征比对
│   │   │   │   └── cluster.py      # 并查集聚类
│   │   │   └── storage.py          # SQLite + 向量存储
│   │   │
│   │   └── (更多工具...)           # 后续工具在此添加
│   │
│   └── utils/                      # 公共工具
│       ├── __init__.py
│       ├── logger.py               # 日志
│       ├── device.py               # 设备检测
│       └── helpers.py              # 工具函数
│
├── tests/                          # 测试
│   ├── test_tool_base.py
│   ├── test_server.py
│   ├── test_video_dedup/
│   │   ├── test_sampler.py
│   │   ├── test_extractors.py
│   │   ├── test_indexing.py
│   │   ├── test_matching.py
│   │   └── test_pipeline.py
│   └── fixtures/                   # 测试用视频文件
│       └── (10 个左右小视频)
│
├── docs/                           # 文档
│   ├── core/                       # 核心模块设计文档
│   │   ├── platform_module.md      # 平台核心模块设计
│   │   └── server_module.md        # Web 服务与 API 模块设计
│   ├── common/                     # 公共基础设施设计文档
│   │   └── utils_module.md         # 公共基础设施模块设计
│   └── tools/                      # 工具专用文档
│       └── video_dedup.md          # 视频验重工具详细设计
```

---

## 10. 技术选型

| 领域 | 选型 | 理由 |
|------|------|------|
| **语言** | Python ≥ 3.10 | 团队技术栈，生态丰富 |
| **Web 框架** | FastAPI | 异步支持好，自动生成 OpenAPI 文档，轻量 |
| **桌面窗口** | pywebview | 轻量原生窗口壳，复用 Web 前端，Windows 弹出独立窗口，Linux 回退浏览器 |
| **前端** | 原生 HTML + CSS + JS | 零构建依赖，开发调试简单，未来可替换 |
| **配置** | pydantic + yaml | 类型安全，配置校验 |
| **存储** | SQLite | 单文件，零部署，桌面工具首选 |
| **日志** | loguru | 开箱即用，格式美观 |
| **打包** | PyInstaller | 社区成熟，支持 onedir/onefile |

### 视频验重工具选型

| 用途 | 选型 |
|------|------|
| 视频解码/抽帧 | PyAV（libav 绑定） |
| 文件哈希 | hashlib（标准库） |
| 感知哈希 | imagehash（pHash） |
| 深度特征 | OpenCLIP ViT-B/32 |
| 相似检索 | FAISS |
| 设备适配 | torch（CPU/GPU 自动切换） |

---

## 11. 设计决策记录（DDR）

### 11.1 为什么选择 Web 前端而非 PyQt

**问题**：GUI 方案应当选择 Web 前端还是 PyQt/PySide？

**决策**：**Web 前端**。

**原因**：
1. 跨平台代码完全一致，"同一套代码在 Linux 开发、Windows 部署"，与 Fabrica 的跨平台测试需求高度吻合
2. 开发调试工具丰富（浏览器 DevTools）
3. 前端可替换为 Electron/Tauri，未来扩展灵活
4. 打包体积小，无需像 PyQt 那样额外增加 ~100MB，且无需维护两套测试流程
5. 对工具集场景，用户关注功能而非界面，PyQt 的"原生体验"优势不敏感

### 11.2 为什么选择 FastAPI 而非 Flask

**问题**：Web 框架应当选择 FastAPI 还是 Flask？

**决策**：**FastAPI**。

**原因**：
1. 原生 `async/await` 支持，天然适配 WebSocket 实时推送进度
2. Uvicorn 异步 ASGI 服务，长连接场景不阻塞
3. 自动生成 OpenAPI + Swagger UI，开发调试方便
4. Pydantic 原生集成，参数校验零成本
5. 原生 WebSocket 支持，无需额外安装 flask-socketio

### 11.3 为什么选择异步接口而非同步

**问题**：接口应当采用同步方式还是异步方式？

**决策**：**异步接口**。

**原因**：
1. 工具执行可能耗时长（视频验重可能数小时），同步接口会阻塞整个服务进程
2. 异步接口配合 WebSocket 推送，提交任务后立即返回 task_id
3. 前端通过 WebSocket 实时接收进度
4. 用户可取消任务
5. 服务不阻塞，可同时处理多个任务

### 11.4 工具执行采用线程隔离而非进程隔离

**问题**：工具执行应当采用线程隔离还是进程隔离？

**决策**：**线程隔离**。

**原因**：
1. 共享内存，数据传递零拷贝
2. Python GIL 不影响 CPU 密集型任务（工具使用 C 扩展如 PyTorch/FAISS 时会释放 GIL）
3. 工具是用户主动触发的，同时运行多个工具的概率低，线程隔离的开销远小于进程隔离
4. 进程隔离虽能完全隔离崩溃影响，但进程间通信开销大，无法共享 GPU 显存，序列化/反序列化成本高

**线程池配置**：建议 `max_workers=2`（详见第 4.4.3 节），在并发能力和资源消耗之间取得平衡。视频验重等 GPU 密集型任务独占 GPU 显存，过高的并发数会导致显存不足。

### 11.5 为什么选择 pydantic + yaml 而非 toml/json

**问题**：配置格式应当选择 pydantic + yaml 还是 toml/json？

**决策**：**pydantic + yaml**。

**原因**：
1. YAML 支持注释，适合人工编辑的配置文件
2. pydantic 提供类型校验和 IDE 自动补全
3. 工具集场景下配置项数量有限，YAML 的简洁性优于 TOML 的严格格式

---

## 12. 测试策略

### 12.1 测试金字塔

```
         ┌──────────┐
         │   E2E    │  ← 浏览器打开 → 选工具 → 填参数 → 执行 → 验证结果
         │   (少量)  │
        ┌┴──────────┴┐
        │  集成测试   │  ← 工具完整流程（小样本数据）
        │  (中等量)   │
       ┌┴────────────┴┐
       │  单元测试     │  ← 单个函数/类/模块
       │  (大量)       │
       └──────────────┘
```

| 层级 | 运行环境 | 速度 | 覆盖范围 |
|------|---------|------|---------|
| 单元测试 | Linux CI | 秒级 | 每个函数/类的所有分支 |
| 集成测试 | Linux CI | 分钟级 | 工具完整流程（10 个测试视频） |
| E2E 测试 | Linux 手动 / Windows CI | 分钟级 | 浏览器交互 → 工具执行 → 结果展示 |

### 12.2 测试夹具设计

```python
# tests/fixtures/video_factory.py
class VideoFixtureFactory:
    """生成测试用视频夹具"""

    @staticmethod
    def create_test_video(path: Path, duration: int = 5,
                          resolution: tuple = (1920, 1080),
                          content: str = "solid_color") -> Path:
        """使用 PyAV 生成测试视频，避免依赖外部视频文件"""

    @staticmethod
    def create_derived_video(src: Path, watermark: bool = False,
                             crop: bool = False, resize: tuple = None,
                             transcode: str = None) -> Path:
        """从源视频生成派生版本（加水印/裁剪/缩放/转码）"""
```

### 12.3 Linux 开发环境 vs Windows 生产环境差异矩阵

| 维度 | Linux 开发环境 | Windows 生产环境 |
|------|---------------|-----------------|
| 操作系统 | Ubuntu 24.04 | Windows 10/11 |
| Python | 3.10+ | 3.10+（打包后自带） |
| PyTorch | CPU 版 | CUDA 版 |
| FAISS | faiss-cpu | faiss-cpu（足够） |
| 视频数量 | 10 个测试视频 | 数千至数万 |
| 深度模型 | CPU 推理（慢） | GPU 推理（快） |
| 测试目标 | 逻辑正确性 + 输出准确性 | 性能 + 大规模稳定性 |
| 调试手段 | 日志 + 断点 + 浏览器 DevTools | 日志 + 远程调试 |

### 12.4 关键测试用例（视频验重）

| 测试场景 | 预期结果 | 验证级别 |
|---------|---------|---------|
| 同视频不同分辨率 | 判重 | 集成测试 |
| 加静态水印 | 判重 | 集成测试 |
| 黑边裁剪 | 判重 | 集成测试 |
| 不同视频某几帧相似 | 不判重 | 集成测试 |
| 损坏/无法解码视频 | 跳过，不中断流程 | 集成测试 |
| 空目录/无视频文件 | 正常返回空结果 | 单元测试 |
| 用户取消正在执行的任务 | 任务标记为 CANCELLED | 集成测试 |

---

## 13. 路线图

### 第一阶段：平台骨架 + 视频验重（当前）

| 里程碑 | 内容 |
|--------|------|
| M1 | 平台骨架搭建：FastAPI 服务 + 前端首页 + 工具注册机制 + pywebview 桌面窗口 |
| M2 | 视频验重工具核心逻辑：L1+L2 级联，FAISS 索引，小样本可跑通 |
| M3 | 视频验重工具完整实现：L3 CLIP 深度特征，前端配置与结果展示 |
| M4 | 测试与验证：Linux 开发环境全套测试，Windows 打包验证 |

### 第二阶段：平台完善

| 功能 | 说明 |
|------|------|
| 批量任务队列 | 支持工具任务的排队、暂停、取消、历史查看 |
| 工具配置持久化 | 每个工具的配置参数可保存为"方案"，下次复用 |
| 结果导出 | 统一的结果导出机制（JSON/CSV/Excel） |
| 更多工具 | 按需添加新工具（文件整理、格式转换、数据清洗等） |

### 第三阶段：体验提升

| 功能 | 说明 |
|------|------|
| 暗色主题 / 多主题 | 前端主题切换 |
| 任务通知 | 长时间任务完成后系统通知 |
| 进度可视化 | 实时进度条、日志流式展示 |
| Electron/Tauri 壳升级 | 可选，pywebview 桌面窗口已在第一阶段交付，未来可升级到 Electron/Tauri 获得更原生体验 |

---

## 14. 与 OmniPivot 生态的关系

```
┌──────────────────────────────────────────────────────────────┐
│                       OmniPivot 生态                           │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │  Tela    │  │Concilium │  │  Augur   │  │  Numen   │     │
│  │ 新闻采集  │  │ 投研分析  │  │ 交易执行  │  │ 因子发掘  │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                    Fabrica                               │ │
│  │              工具集平台（独立于量化链路）                  │ │
│  │  共享 aurora 公共库，但业务上不依赖其他 nexus 项目        │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                    aurora 公共库                          │ │
│  │  heimdall · athena · chronos · gaia · hermes · ...      │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

Fabrica 是 OmniPivot 生态中的**工具集平台**，与其他 nexus 项目（量化交易链路）业务上无直接依赖关系。可根据需要按需复用 aurora 公共库的能力（如 heimdall 数据采集、gaia 持久化等）。

---

## 15. 开发环境说明

### Linux 开发环境（已验证）

- **操作系统**：Ubuntu 24.04
- **Python**：≥ 3.10
- **硬件**：无 GPU（CPU 推理）
- **测试方式**：`python main.py` 启动后浏览器访问，全功能可测

### Windows 部署环境

- **打包方式**：PyInstaller 在 Windows 上构建
- **GPU 支持**：自动检测 CUDA，深度模型在 GPU 上推理
- **分发形态**：单目录 exe（含模型权重与依赖）