# Fabrica 桌面集成模块详细设计文档

---

## 1. 模块概述

### 1.1 职责定位

桌面集成模块是 Fabrica 系统的**窗口展示层**，负责将现有 Web 前端包装为原生桌面窗口，使用户在 Windows 上双击 exe 后直接看到图形化软件界面，而非控制台终端。核心职责：

- **窗口展示**：用 pywebview 创建原生桌面窗口，内嵌 WebView 渲染现有 Web 前端
- **服务协调**：管理 uvicorn 后台服务与 pywebview 窗口的生命周期，确保窗口启动前服务已就绪
- **优雅退出**：窗口关闭时触发 uvicorn 服务停止，避免残留进程
- **窗口元信息**：提供窗口标题、尺寸、最小尺寸等配置
- **跨平台回退**：Linux 开发环境无 GUI 库时，回退为自动打开浏览器模式

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **零改动复用** | 现有 Web 前端（HTML/CSS/JS）与 FastAPI 服务代码不修改，桌面层只做包装 |
| **线程隔离** | uvicorn 服务运行在后台线程，pywebview 窗口运行在主线程（GUI 线程约束） |
| **端口就绪探测** | 窗口启动前轮询服务端口，确保前端可加载后再弹出窗口 |
| **优雅退出** | 窗口关闭 → 触发 `server.should_exit` → 等待服务线程结束 → 进程退出 |
| **跨平台一致** | Windows 生产用桌面窗口，Linux 开发用浏览器回退，同一套主入口代码 |
| **日志不丢** | 控制台隐藏后，日志仍写入文件（复用 helios 文件日志） |

---

## 2. 架构设计

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                       桌面展示层                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │           pywebview 窗口（主线程）                       │  │
│  │  原生窗口壳 → 内嵌 WebView → 加载 http://127.0.0.1:8520 │  │
│  │  窗口关闭 → 触发服务停止                                 │  │
│  └──────────────────────┬─────────────────────────────────┘  │
│                         │ HTTP / WebSocket (localhost)        │
└─────────────────────────┼────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│                    API 服务层（后台线程）                       │
│  ┌────────────────────────────────────────────────────────┐  │
│  │           uvicorn Server（独立线程）                     │  │
│  │  FastAPI 应用 + REST 端点 + WebSocket 端点              │  │
│  └──────────────────────┬─────────────────────────────────┘  │
└─────────────────────────┼────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│              工具插件层 + 公共基础设施层（现有代码不变）         │
│  ToolRegistry / video_dedup / 配置 / 日志 / 存储 / 设备检测    │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 启动时序

```
main() 入口
    │
    ├── 1. 解析参数 / 初始化配置 / 初始化日志
    ├── 2. create_app() 创建 FastAPI 应用
    ├── 3. 加载工具插件 / 初始化资源池
    ├── 4. 创建 uvicorn.Server 实例
    │
    ├── 5. 启动 uvicorn 服务线程（daemon=True）
    │       └── server.run() 在后台线程阻塞运行
    │
    ├── 6. 等待端口就绪（轮询 socket 连接，超时 10s）
    │       └── 探测 127.0.0.1:8520 可连接
    │
    ├── 7. 判断 dev_mode
    │   ├── dev_mode=true（Linux 开发）→ 自动打开浏览器访问 localhost
    │   └── dev_mode=false（Windows 生产）→ 启动 pywebview 窗口（主线程阻塞）
    │
    ├── 8. 窗口关闭 / 浏览器关闭信号
    │       └── server.should_exit = True
    │
    ├── 9. 等待 uvicorn 服务线程结束（join 超时 5s）
    │
    └── 10. tool.shutdown() 释放资源池 → 进程退出
```

### 2.3 与现有模块的关系

| 关系方向 | 模块 | 接口 | 说明 |
|----------|------|------|------|
| **桌面层 → 服务层** | fabrica.server | HTTP/WS (localhost) | pywebview 窗口通过 `http://127.0.0.1:{port}` 访问 FastAPI 服务 |
| **桌面层 → 配置** | fabrica.utils.config | `get_config()` | 读取窗口标题、尺寸、dev_mode 等配置 |
| **桌面层 → 主入口** | main.py | 函数调用 | main.py 在服务就绪后调用 `launch_window()` |
| **桌面层 → 日志** | fabrica.utils.logger | `get_logger()` | 记录窗口启动/关闭事件 |

**不修改的模块**：
- `fabrica/server/`（FastAPI 应用、路由、静态资源）— 完全复用
- `fabrica/tools/`（工具插件）— 完全复用
- `fabrica/utils/`（日志、配置、异常）— 完全复用

**修改的模块**：
- `main.py` — 增加窗口启动逻辑（服务线程化 + 端口探测 + 调用 `launch_window()`）
- `build_win.spec` — `console=False` + pywebview hiddenimports
- `config/config.yaml` — 增加 `fabrica.desktop` 配置域

---

## 3. 各组件详细设计

### 3.1 桌面启动器（Desktop Launcher）

**文件：** `fabrica/desktop/__init__.py`

**职责：** 创建并运行 pywebview 窗口，阻塞主线程直到窗口关闭。

#### 3.1.1 核心接口

```python
def launch_window(
    host: str,
    port: int,
    title: str = "Fabrica 工具集平台",
    width: int = 1280,
    height: int = 800,
    min_size: tuple[int, int] = (1024, 600),
    on_close: Callable[[], None] | None = None,
) -> None:
    """启动 pywebview 桌面窗口，阻塞主线程直到窗口关闭。

    Args:
        host: 服务监听地址（通常 127.0.0.1）
        port: 服务监听端口
        title: 窗口标题
        width: 窗口初始宽度
        height: 窗口初始高度
        min_size: 窗口最小尺寸 (width, height)
        on_close: 窗口关闭时的回调（用于触发服务停止）
    """
```

#### 3.1.2 端口就绪探测

```python
def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """轮询探测服务端口是否可连接。

    Args:
        host: 服务地址
        port: 服务端口
        timeout: 最大等待时间（秒）

    Returns:
        True 表示服务已就绪，False 表示超时
    """
    import socket
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False
```

#### 3.1.3 浏览器回退模式

```python
def launch_browser(host: str, port: int) -> None:
    """dev_mode 模式下自动打开系统浏览器（Linux 开发环境回退）。

    Args:
        host: 服务地址
        port: 服务端口
    """
    import webbrowser
    url = f"http://{host}:{port}"
    webbrowser.open(url)
    # 浏览器模式下，主线程需阻塞等待服务退出信号
    # （由 main.py 的信号处理器管理）
```

### 3.2 服务线程管理

**文件：** `main.py`（修改）

**职责：** 将 uvicorn 服务运行在后台线程，主线程用于 pywebview 窗口。

#### 3.2.1 服务线程启动

```python
import threading

# 在 main() 中，替换原有的 server.run() 阻塞调用
server_thread = threading.Thread(
    target=server.run,
    daemon=True,  # 守护线程，主线程退出时自动结束
    name="uvicorn-server",
)
server_thread.start()
```

#### 3.2.2 窗口关闭触发服务停止

```python
def on_window_close():
    """窗口关闭回调：触发 uvicorn 优雅停止。"""
    server.should_exit = True

# 启动窗口（阻塞主线程）
launch_window(
    host=host,
    port=port,
    title=get_config("fabrica.desktop.window_title", "Fabrica 工具集平台"),
    width=get_config("fabrica.desktop.width", 1280),
    height=get_config("fabrica.desktop.height", 800),
    min_size=tuple(get_config("fabrica.desktop.min_size", [1024, 600])),
    on_close=on_window_close,
)

# 窗口关闭后，等待服务线程退出
server_thread.join(timeout=5.0)
```

#### 3.2.3 dev_mode 判断逻辑

```python
dev_mode = get_config("fabrica.desktop.dev_mode", False)

# Linux 开发环境默认 dev_mode（可通过配置覆盖）
import platform
if platform.system() == "Linux" and not dev_mode:
    # Linux 下 pywebview 依赖 GUI 库（如 GTK），开发环境可能缺失
    # 默认回退浏览器模式，可通过配置 fabrica.desktop.dev_mode=true 强制窗口
    dev_mode = True

if dev_mode:
    launch_browser(host, port)
    # 浏览器模式下，主线程阻塞在 server.run() 或信号等待
    # 由信号处理器管理退出
else:
    # pywebview 窗口模式（Windows 生产）
    if not wait_for_server(host, port, timeout=10.0):
        logger.error("服务启动超时，无法打开窗口")
        sys.exit(1)
    launch_window(host, port, ..., on_close=on_window_close)
```

### 3.3 DesktopAPI — JS 桥接层

**文件：** `fabrica/desktop/__init__.py`（在桌面启动器同模块中定义）

**职责：** 通过 pywebview `js_api` 机制，将 Python 桌面能力暴露给前端 JavaScript 调用，突破浏览器安全沙箱限制。

#### 3.3.1 桥接机制

pywebview 提供 `js_api` 参数，将 Python 对象的方法暴露给前端。前端通过 `window.pywebview.api.<method>()` 异步调用，返回 Promise。

```python
# main.py 中创建窗口时传入 js_api
from fabrica.desktop import DesktopAPI

webview.create_window(
    title, url, width=width, height=height,
    min_size=min_size,
    js_api=DesktopAPI(),  # ← 暴露桌面 API 给前端
)
```

```javascript
// 前端 JS 调用（异步，返回 Promise）
const path = await window.pywebview.api.open_directory_dialog();
```

#### 3.3.2 DesktopAPI 接口清单

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `open_directory_dialog()` | — | `str \| None` | 打开原生目录选择对话框，返回完整路径 |
| `open_file_dialog()` | — | `str \| None` | 打开原生文件选择对话框，返回完整路径 |
| `open_in_explorer(path)` | `str` | `bool` | 在系统文件管理器中打开并选中文件/目录 |

#### 3.3.3 浏览器环境回退

`window.pywebview` 对象仅在 pywebview 桌面环境存在，浏览器环境为 `undefined`。前端调用前需检测环境：

```javascript
const isDesktop = typeof window.pywebview !== 'undefined' && window.pywebview.api;
```

> DesktopAPI 的详细方法实现、前端调用示例和浏览器回退策略，见 [desktop_features.md](./desktop_features.md) §2 技术基础。

---

## 4. 配置项

### 4.1 配置域

`config.yaml` 新增 `fabrica.desktop` 配置域：

```yaml
fabrica:
  # ... 现有 server / logging / storage / tools 配置 ...

  # 桌面窗口配置
  desktop:
    window_title: "Fabrica 工具集平台"   # 窗口标题
    width: 1280                          # 窗口初始宽度（像素）
    height: 800                          # 窗口初始高度（像素）
    min_size: [1024, 600]                # 窗口最小尺寸 [width, height]
    dev_mode: false                      # true=浏览器回退模式，false=桌面窗口模式
```

### 4.2 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `fabrica.desktop.window_title` | str | `"Fabrica 工具集平台"` | 窗口标题栏显示文本 |
| `fabrica.desktop.width` | int | `1280` | 窗口初始宽度（像素） |
| `fabrica.desktop.height` | int | `800` | 窗口初始高度（像素） |
| `fabrica.desktop.min_size` | list[int] | `[1024, 600]` | 窗口最小尺寸 `[width, height]`，防止用户拖拽过小 |
| `fabrica.desktop.dev_mode` | bool | `false` | `true` 时跳过窗口，自动打开浏览器；Linux 下自动回退为 `true` |

### 4.3 Linux 自动回退规则

| 环境 | `dev_mode` 配置值 | 实际行为 |
|------|------------------|---------|
| Windows（任意） | `false`（默认） | pywebview 桌面窗口 |
| Windows（任意） | `true` | 浏览器回退（调试用） |
| Linux | `false` | 自动回退为浏览器模式（pywebview 依赖 GUI 库） |
| Linux | `true` | 浏览器回退 |

---

## 5. 跨平台策略

### 5.1 环境矩阵

| 维度 | Windows 生产（exe） | Windows 开发 | Linux 开发 |
|------|---------------------|-------------|-----------|
| 操作系统 | Windows 10/11 | Windows 10/11 | Ubuntu 24.04 |
| 启动方式 | pywebview 桌面窗口 | pywebview 窗口 或 浏览器 | 浏览器自动打开 |
| 控制台 | 隐藏（`console=False`） | 可见（`console=True`） | 可见（终端） |
| dev_mode | `false`（默认） | 可配置 | 自动 `true` |
| GUI 库依赖 | 系统自带（EdgeWebView2） | 系统自带 | 无需（浏览器回退） |
| 调试方式 | 日志文件 | 日志 + DevTools | 日志 + 浏览器 DevTools |

### 5.2 Linux 开发环境说明

- pywebview 在 Linux 上依赖 GUI 库（GTK/Qt），服务器或 SSH 远程开发环境通常无 GUI
- 因此 Linux 下默认 `dev_mode=true`，自动回退为浏览器模式
- 开发时通过浏览器 DevTools 调试前端，与 pywebview 窗口行为一致（同一套前端代码）

### 5.3 Windows 生产环境说明

- Windows 10/11 自带 EdgeWebView2 运行时（pywebview 默认后端）
- 若用户系统未安装 WebView2 运行时，pywebview 会回退到 MSHTML 或提示安装
- 打包时需将 pywebview 及其后端加入 `hiddenimports`

---

## 6. 打包变更

### 6.1 build_win.spec 修改

| 配置项 | 修改前 | 修改后 | 说明 |
|--------|--------|--------|------|
| `console` | `True` | `False` | 隐藏控制台窗口，用户只看到桌面窗口 |
| `hiddenimports` | 无 pywebview | 增加 pywebview 相关 | 确保 pywebview 及其后端被打包 |

修改后的 `hiddenimports` 示例：

```python
_hiddenimports = (
    _aurora_hidden
    + _video_dedup_hidden
    + _third_party_hidden
    + [
        "pywebview",
        "pywebview.platforms.winforms",  # Windows EdgeWebView2 后端
    ]
)
```

### 6.2 依赖变更

`requirements.txt` 增加：

```
pywebview>=4.0
```

### 6.3 日志处理

控制台隐藏（`console=False`）后的日志策略：

| 日志通道 | 现状 | 隐藏控制台后 | 说明 |
|---------|------|-------------|------|
| 控制台输出 | helios ConsoleHandler 彩色输出 | 不再可见 | 用户无需关注内部日志 |
| 文件日志 | helios FileHandler 轮转写入 | **正常写入** | 日志文件路径不变（`logs/` 目录） |
| 窗口内日志 | 无 | 未来迭代可加 | 可在 Web 前端增加"日志查看"页面 |

**注意**：`console=False` 后，helios 的 ConsoleHandler 仍可保留（输出到空控制台不影响功能），或通过配置关闭 ConsoleHandler 以减少无意义输出。建议保留文件日志为主，控制台输出在开发环境（`console=True`）时启用。

---

## 7. 模块代码结构

```
fabrica/
├── desktop/                     # 桌面集成模块（新增）
│   └── __init__.py              # 桌面启动器 + DesktopAPI（launch_window / launch_browser / wait_for_server / DesktopAPI）
│
├── server/                      # Web 服务层（现有，不修改）
│   ├── __init__.py
│   ├── routes.py
│   └── static/
│
└── ...                          # 其他现有模块
```

**模块内部依赖关系：**

```
fabrica/desktop/__init__.py（桌面启动器 + DesktopAPI）
    ├── 依赖: pywebview（第三方库，窗口创建 + js_api 桥接）
    ├── 依赖: webbrowser（标准库，浏览器回退）
    ├── 依赖: socket（标准库，端口探测）
    ├── 依赖: subprocess（标准库，打开文件管理器）
    └── 依赖: fabrica.utils.config（读取窗口配置）

main.py（主入口，修改）
    ├── 依赖: fabrica.desktop（launch_window / launch_browser / wait_for_server / DesktopAPI）
    ├── 依赖: fabrica.server（create_app）
    ├── 依赖: uvicorn（服务运行）
    └── 依赖: threading（服务线程化）
```

---

## 8. 设计决策记录（DDR）

### 8.1 为什么选 pywebview 而非 Electron/Tauri

**问题**：桌面窗口壳层应当选择 pywebview、Electron 还是 Tauri？

**决策**：**pywebview**。

**原因**：
1. 复用 Python 技术栈，无需引入 Node.js（Electron）或 Rust（Tauri）生态，学习与维护成本最低
2. 打包体积增量小（pywebview ~10MB，Electron ~100MB+），与现有 PyInstaller onedir 模式兼容
3. 与现有 Web 前端代码零改动集成（pywebview 内嵌 WebView 加载 localhost）
4. README §13 路线图中 Electron 壳为"可选"项，pywebview 作为轻量替代先行交付，未来仍可升级到 Electron/Tauri

### 8.2 为什么选 pywebview 而非自动打开系统浏览器

**问题**：GUI 方案应当选择 pywebview 桌面窗口还是自动打开系统浏览器？

**决策**：**pywebview 桌面窗口**（生产环境），保留浏览器作为开发回退。

**原因**：
1. 浏览器标签页缺乏"软件"感，用户期望"打开 exe 出现像样的软件界面"
2. pywebview 提供独立原生窗口，关闭窗口即退出应用，符合桌面应用心智模型
3. 隐藏控制台（`console=False`）后，用户只看到窗口，体验更纯粹
4. 浏览器模式下，关闭浏览器标签不会触发应用退出，进程残留需手动管理
5. 保留 `dev_mode` 浏览器回退，兼顾 Linux 开发环境与调试便利性

### 8.3 为什么 uvicorn 在后台线程而非主线程

**问题**：uvicorn 服务与 pywebview 窗口应当分别在哪个线程运行？

**决策**：**uvicorn 在后台守护线程，pywebview 在主线程**。

**原因**：
1. pywebview（以及大多数 GUI 框架）要求在主线程运行，否则窗口无法创建（macOS/Windows GUI 线程约束）
2. uvicorn 的 asyncio 事件循环可在子线程中独立运行，与服务逻辑不冲突
3. uvicorn 线程设为 `daemon=True`，主线程（窗口）退出时自动结束，避免进程残留
4. 窗口关闭回调触发 `server.should_exit = True`，uvicorn 优雅停止，再由主线程 `join` 等待清理

### 8.4 为什么保留 dev_mode 浏览器回退

**问题**：是否应当在所有平台统一使用 pywebview 窗口？

**决策**：**保留 dev_mode 浏览器回退，Linux 默认回退**。

**原因**：
1. Linux 开发环境可能无 GUI 库（如 SSH 远程开发、Docker 容器），pywebview 无法创建窗口
2. 浏览器 DevTools 调试能力优于 pywebview 内嵌 WebView，开发调试更高效
3. 符合 README §12.3 "Linux 开发环境 vs Windows 生产环境"的跨平台测试策略
4. 同一套前端代码在浏览器和 pywebview 中行为一致，回退不影响功能验证

### 8.5 为什么隐藏控制台（console=False）

**问题**：打包时是否应当隐藏控制台窗口？

**决策**：**生产打包 `console=False`**。

**原因**：
1. 桌面应用不应显示终端窗口，影响用户体验
2. 日志已通过 helios FileHandler 写入文件，控制台输出非必要
3. 隐藏控制台后，用户只看到 pywebview 桌面窗口，符合"像样的软件界面"期望
4. 开发环境仍可使用 `console=True`（或不打包直接 `python main.py`）查看实时日志

---

## 9. 与实现步骤的对应关系

本设计文档对应的实现任务为 `docs/product/implementation_steps.md` 中的 **T3.6 桌面窗口集成（pywebview）**。

| 设计文档章节 | 对应实现交付物 |
|-------------|---------------|
| §3.1 桌面启动器 | `fabrica/desktop/__init__.py`（launch_window / launch_browser / wait_for_server） |
| §3.2 服务线程管理 | `main.py` 修改 |
| §3.3 DesktopAPI JS 桥接层 | `fabrica/desktop/__init__.py`（DesktopAPI 类，详见 [desktop_features.md](./desktop_features.md)） |
| §4 配置项 | `config/config.yaml` 增加 `fabrica.desktop` 域 |
| §6.1 打包变更 | `build_win.spec` 修改 |
| §6.2 依赖变更 | `requirements.txt` 增加 pywebview |

---

**文档结束**
