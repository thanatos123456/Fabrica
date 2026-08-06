# Fabrica Web 服务与 API 模块详细设计文档

---

## 1. 模块概述

### 1.1 职责定位

Web 服务与 API 模块是 Fabrica 系统的**用户交互层**，负责接收用户的前端 HTTP 请求和 WebSocket 连接，将其转化为对平台核心模块的调用，并将结果返回给前端。核心职责：

- **REST API**：提供工具列表、工具详情、任务提交、任务查询等 RESTful 接口
- **WebSocket**：为运行中的任务提供实时进度推送和日志流
- **静态资源服务**：托管前端 HTML/CSS/JS 静态资源
- **前端路由**：实现 SPA（单页应用）的前端页面路由
- **错误处理**：统一的异常捕获和错误响应格式

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **薄路由层** | API 路由只做参数解析和响应序列化，不包含业务逻辑，业务逻辑委托给平台核心模块 |
| **异步非阻塞** | 所有 API 端点使用 `async def`，避免阻塞事件循环 |
| **统一错误格式** | 所有 API 错误使用统一的 JSON 响应格式，前端统一处理 |
| **实时推送** | 耗时任务通过 WebSocket 推送进度，避免轮询 |
| **前端无关性** | 后端不依赖前端框架，前端可整体替换（原生 → React → Electron） |
| **SPA 路由兜底** | 对于非 API 路径，返回 `index.html`，由前端路由处理 |
| **并发控制** | 通过 `ThreadPoolExecutor(max_workers=2)` 限制 CPU 密集型工具的并发执行数，避免资源耗尽 |

---

## 2. 模块代码结构

```
fabrica/server/
├── __init__.py              # 模块导出，AppFactory 工厂函数
├── routes.py                # API 路由定义（REST + WebSocket）
│
└── static/                  # 前端静态资源
    ├── index.html           # 工具首页（SPA 入口）
    ├── css/
    │   └── style.css        # 全局样式
    └── js/
        ├── app.js           # 应用入口（路由初始化）
        ├── router.js        # SPA 路由实现
        ├── api.js           # HTTP API 客户端封装
        ├── ws.js            # WebSocket 客户端封装
        └── components/      # UI 组件
            ├── tool-card.js      # 工具卡片组件
            ├── tool-form.js      # 参数配置表单组件
            ├── task-progress.js  # 任务进度组件
            └── task-history.js   # 任务历史组件
```

**模块内部依赖关系：**

```
routes.py（API 路由层）
    ├── 依赖: fabrica.tool（ToolRegistry 注册中心）
    ├── 依赖: fabrica.config（配置管理）
    └── 依赖: fabrica.server.static（静态资源，通过 FastAPI.mount()）

static/（前端静态资源）
    ├── index.html → 引用 css/style.css, js/app.js
    ├── js/app.js  → 引用 js/router.js, js/api.js, js/ws.js
    └── js/router.js → 按路由加载 js/components/*.js
```

---

## 3. 各组件详细设计

### 3.1 AppFactory — 应用工厂

**文件：** `fabrica/server/__init__.py`

**职责：** 创建和配置 FastAPI 应用实例，注册中间件、异常处理器、路由。

#### 3.1.1 核心接口

```python
def create_app(config: FabricaConfig, tool_registry: ToolRegistry) -> FastAPI:
    """创建并配置 FastAPI 应用实例"""

    app = FastAPI(
        title="Fabrica",
        description="Fabrica 工具集平台 API",
        version="1.0.0",
    )

    # 注册中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册全局异常处理器
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "details": {},
                }
            },
        )

    # 挂载静态资源
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    # 注册路由
    app.include_router(router)

    return app
```

#### 3.1.2 中间件配置

| 中间件 | 配置项 | 说明 |
|--------|--------|------|
| CORS | `allow_origins: config.server.cors_origins` | 跨域支持，开发环境允许所有来源 |
| 请求日志 | 自定义 | 记录每个请求的方法、路径、状态码、耗时 |
| 访问控制 | 自定义 | 限制仅本地访问（`127.0.0.1`） |

### 3.2 API 路由层

**文件：** `fabrica/server/routes.py`

**职责：** 定义所有 REST 端点和 WebSocket 端点，将 HTTP 请求转化为平台核心模块的调用。

#### 3.2.1 REST 端点

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| `GET` | `/api/tools` | 获取所有工具的元信息列表 | — |
| `GET` | `/api/tools/{name}` | 获取单个工具详细信息和参数定义 | `name`（路径参数） |
| `POST` | `/api/tools/{name}/run` | 提交工具执行请求 | `name`（路径参数），`body: {params: dict}` |
| `GET` | `/api/tasks` | 获取任务历史列表 | — |
| `GET` | `/api/tasks/{id}` | 获取单个任务完整状态和结果 | `id`（路径参数） |
| `POST` | `/api/tasks/{id}/cancel` | 取消正在执行的任务 | `id`（路径参数） |
| `DELETE` | `/api/tasks/{id}` | 删除任务记录 | `id`（路径参数） |

#### 3.2.2 WebSocket 端点

| 端点 | 事件方向 | 事件类型 | 数据格式 |
|------|---------|---------|---------|
| `WS /api/ws/tasks/{id}` | 服务端 → 客户端 | `progress` | `{type: "progress", percent: float, message: str}` |
| | 服务端 → 客户端 | `log` | `{type: "log", level: str, message: str, timestamp: str}` |
| | 服务端 → 客户端 | `complete` | `{type: "complete", result: dict}` |
| | 服务端 → 客户端 | `error` | `{type: "error", error: str}` |
| | 服务端 → 客户端 | `cancelled` | `{type: "cancelled"}` |
| | 客户端 → 服务端 | `ping` | `{type: "ping"}` |
| | 服务端 → 客户端 | `pong` | `{type: "pong"}` |

#### 3.2.3 路由实现要点

```python
router = APIRouter(prefix="/api")

@router.get("/tools", response_model=List[ToolMeta])
async def list_tools():
    """获取所有已注册工具的元信息列表"""
    return tool_registry.list_tools()

@router.get("/tools/{name}", response_model=ToolDetail)
async def get_tool_detail(name: str):
    """获取单个工具的详细信息"""
    try:
        schema = tool_registry.get_schema(name)
    except KeyError:
        raise HTTPException(status_code=404, detail={
            "code": "TOOL_NOT_FOUND",
            "message": f"工具 '{name}' 不存在",
        })
    meta = tool_registry.get_tool_meta(name)
    return ToolDetail(**meta.model_dump(), params=schema)

@router.post("/tools/{name}/run", response_model=RunResponse)
async def run_tool(name: str, body: RunRequest):
    """提交工具执行请求"""
    try:
        task_id = tool_registry.run_tool(name, body.params)
    except KeyError:
        raise HTTPException(status_code=404, detail={
            "code": "TOOL_NOT_FOUND",
            "message": f"工具 '{name}' 不存在",
        })
    except ValueError as e:
        raise HTTPException(status_code=422, detail={
            "code": "PARAM_INVALID",
            "message": str(e),
        })
    return RunResponse(task_id=task_id, status="pending")

@router.websocket("/ws/tasks/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str):
    """WebSocket 实时推送任务进度"""
    await websocket.accept()
    try:
        # 注册进度和日志回调（包装 WebSocket 发送，而非直接传入 WebSocket 对象）
        async def progress_cb(percent: float, message: str):
            await websocket.send_json({
                "type": "progress",
                "percent": percent,
                "message": message,
            })
        async def log_cb(level: str, message: str, timestamp: str):
            await websocket.send_json({
                "type": "log",
                "level": level,
                "message": message,
                "timestamp": timestamp,
            })
        async def complete_cb(result: dict):
            await websocket.send_json({
                "type": "complete",
                "result": result,
            })
        async def error_cb(error: str):
            await websocket.send_json({
                "type": "error",
                "error": error,
            })
        tool_registry.register_progress_callback(task_id, progress_cb)
        tool_registry.register_log_callback(task_id, log_cb)
        tool_registry.register_complete_callback(task_id, complete_cb)
        tool_registry.register_error_callback(task_id, error_cb)
        # 保持连接，处理心跳
        while True:
            data = await websocket.receive_text()
            if json.loads(data).get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        tool_registry.unregister_progress_callback(task_id)
        tool_registry.unregister_log_callback(task_id)
        tool_registry.unregister_complete_callback(task_id)
        tool_registry.unregister_error_callback(task_id)
```

### 3.3 前端架构

**文件：** `fabrica/server/static/`

**职责：** 提供用户交互界面，包括工具首页、工具详情页、执行页面和任务历史页。

#### 3.3.1 页面路由

| 路由 | 页面 | 功能 |
|------|------|------|
| `/` | 工具首页 | 卡片式网格展示所有注册工具，支持分类过滤 |
| `/tool/{name}` | 工具详情页 | 展示工具描述、参数配置表单、开始按钮 |
| `/tool/{name}/run?task_id={id}` | 工具执行页 | 实时进度条、日志流、结果展示 |
| `/tasks` | 任务历史页 | 历史任务列表，可按状态过滤 |
| `/tasks/{id}` | 任务详情页 | 单任务完整状态、参数、结果、日志 |

#### 3.3.2 组件树

```
App
├── Header（导航栏：标题 + 任务历史链接）
├── Router（路由分发）
│   ├── HomePage
│   │   ├── CategoryFilter（分类筛选器）
│   │   └── ToolCardGrid（工具卡片网格）
│   │       └── ToolCard（单个工具卡片：图标 + 标题 + 简短描述）
│   ├── ToolDetailPage
│   │   ├── ToolHeader（工具图标 + 标题 + 版本 + 分类）
│   │   ├── ToolDescription（Markdown 渲染的描述文本）
│   │   ├── ParamForm（动态参数配置表单）
│   │   │   ├── StringInput / NumberInput / Checkbox
│   │   │   ├── PathSelector / FileSelector / DirSelector
│   │   │   └── SelectInput / MultiSelectInput
│   │   └── ActionButtons（开始执行 / 重置）
│   ├── TaskRunPage
│   │   ├── ProgressBar（进度条 + 百分比 + 状态文字）
│   │   ├── LogStream（实时滚动日志流）
│   │   └── ResultPanel（执行结果展示）
│   ├── TaskHistoryPage
│   │   └── TaskTable（任务列表表格）
│   └── TaskDetailPage
│       ├── TaskInfo（任务元信息：状态、时间、工具名）
│       ├── ParamSnapshot（执行参数快照）
│       ├── ResultPanel（执行结果）
│       └── LogViewer（日志查看器）
```

#### 3.3.3 前端无框架实现策略

前端使用原生 JavaScript ES6+ 实现，不依赖 React/Vue 等框架：

- **路由**：基于 `hashchange` 事件实现 SPA 路由
- **模板渲染**：使用模板字符串（`${}`）和 `innerHTML`
- **状态管理**：全局状态对象 + 自定义事件
- **HTTP 请求**：`fetch()` API + `async/await`
- **WebSocket**：原生 `WebSocket` API
- **样式**：CSS 自定义属性（变量）实现主题切换

```javascript
// router.js - SPA 路由实现示意
class Router {
    constructor(routes) {
        this.routes = routes;
        window.addEventListener('hashchange', () => this.resolve());
    }

    resolve() {
        const hash = location.hash.slice(1) || '/';
        for (const [pattern, handler] of this.routes) {
            const match = hash.match(pattern);
            if (match) {
                document.getElementById('app').innerHTML = '';
                handler(match.groups);
                return;
            }
        }
        this.navigate('/');
    }

    navigate(path) {
        location.hash = path;
    }
}
```

---

## 4. 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `fabrica.server.host` | str | `"127.0.0.1"` | 服务监听地址 |
| `fabrica.server.port` | int | `8520` | 服务监听端口 |
| `fabrica.server.cors_origins` | list | `["*"]` | CORS 允许的源 |
| `fabrica.server.static_dir` | str | `"server/static"` | 前端静态资源目录（相对于 fabrica 包） |

---

## 5. 模块关系与数据流

### 5.1 与其他模块的关系

| 关系方向 | 模块 | 接口 | 说明 |
|----------|------|------|------|
| **服务层 → 平台核心** | ToolRegistry | `list_tools()`, `get_schema()`, `run_tool()`, `cancel_task()` | API 路由层调用注册中心 |
| **服务层 → 基础设施** | Utils | 日志 | 请求日志记录 |
| **服务层 → 前端** | 静态资源 | 文件系统 | 直接返回静态 HTML/CSS/JS 文件 |

### 5.2 HTTP 请求全链路时序

```
用户浏览器                    FastAPI 服务                   ToolRegistry
    │                            │                            │
    │ 1. 输入 URL /              │                            │
    │───────────────────────────▶│                            │
    │                            │ 2. 命中静态文件 index.html  │
    │◀───────────────────────────│                            │
    │                            │                            │
    │ 3. 浏览器执行 JS            │                            │
    │    SPA 路由解析 hash        │                            │
    │                            │                            │
    │ 4. GET /api/tools          │                            │
    │───────────────────────────▶│                            │
    │                            │ 5. list_tools()            │
    │                            │───────────────────────────▶│
    │                            │◀── tool_meta_list ────────│
    │◀──────── JSON ────────────│                            │
    │                            │                            │
    │ 6. 渲染工具卡片网格         │                            │
    │                            │                            │
    │ 7. 用户点击工具卡片         │                            │
    │    hash → /tool/video_dedup│                            │
    │                            │                            │
    │ 8. GET /api/tools/         │                            │
    │    video_dedup             │                            │
    │───────────────────────────▶│                            │
    │                            │ 9. get_schema()            │
    │                            │───────────────────────────▶│
    │                            │◀── param_defs ────────────│
    │◀──────── JSON ────────────│                            │
    │                            │                            │
    │ 10. 渲染参数配置表单        │                            │
    │                            │                            │
    │ 11. 用户填写参数，点击执行   │                            │
    │                            │                            │
    │ 12. POST /api/tools/       │                            │
    │     video_dedup/run        │                            │
    │───────────────────────────▶│                            │
    │                            │ 13. run_tool() → task_id  │
    │                            │───────────────────────────▶│
    │◀──── {task_id, status} ───│                            │
    │                            │                            │
    │ 14. 跳转 /tool/            │                            │
    │     video_dedup/run        │                            │
    │     #task_id=xxx           │                            │
    │                            │                            │
    │ 15. WS /api/ws/tasks/{id}  │                            │
    │═══════════════════════════▶│                            │
    │◀══ progress/log/complete ═│═══════════════════════════│
    │                            │                            │
    │ 16. 实时更新进度条和日志     │                            │
```

---

## 6. 监控与维护

### 6.1 日志

| 级别 | 场景 |
|------|------|
| **INFO** | 请求方法、路径、状态码、耗时 |
| **WARNING** | 慢请求（> 5s）、客户端断开连接 |
| **ERROR** | 未捕获异常、WebSocket 异常 |

### 6.2 异常处理

| 异常类型 | HTTP 状态码 | 错误码 | 处理方式 |
|---------|------------|--------|---------|
| `KeyError` (工具不存在) | 404 | `TOOL_NOT_FOUND` | 返回错误信息 |
| `ValueError` (参数错误) | 422 | `PARAM_INVALID` | 返回校验错误详情 |
| `WebSocketDisconnect` | — | — | 清理回调，关闭连接 |
| 未捕获异常 | 500 | `INTERNAL_ERROR` | 记录日志，返回通用错误信息 |

### 6.3 性能指标

| 指标 | 说明 |
|------|------|
| 请求响应时间 | 每个 API 端点的平均/95 分位/99 分位响应时间 |
| WebSocket 连接数 | 当前活跃的 WebSocket 连接数 |
| 静态资源命中率 | 静态文件的缓存命中率 |
| 并发连接数 | 同时处理的 HTTP 请求数 |

---

## 7. 扩展与迭代

### 7.1 添加新路由

在 `routes.py` 中添加新的路由函数，使用 FastAPI 的 `@router` 装饰器注册：

```python
@router.get("/api/tools/{name}/stats")
async def get_tool_stats(name: str):
    """获取工具的执行统计信息"""
    stats = tool_registry.get_tool_stats(name)
    return stats
```

### 7.2 前端主题切换

通过 CSS 自定义属性实现主题切换：

```css
:root {
    --bg-primary: #ffffff;
    --text-primary: #1a1a1a;
    --accent-color: #4a90d9;
}

[data-theme="dark"] {
    --bg-primary: #1a1a1a;
    --text-primary: #e0e0e0;
    --accent-color: #66b0ff;
}
```

### 7.3 未来迭代计划

| 迭代项 | 描述 | 优先级 |
|-------|------|--------|
| OpenAPI 文档 | 集成 FastAPI 自动生成的 Swagger UI | P1 |
| 前端框架迁移 | 可选迁移到 React/Vue 或 Electron | P2 |
| 多语言支持 | 前端 i18n 国际化 | P3 |
| 响应式布局 | 适配移动端和平板 | P4 |

---

## 8. 设计决策记录

### 8.1 为什么通过回调机制解耦 WebSocket 而非直接注入

**问题**：`ToolRegistry` 核心模块应当直接持有 WebSocket 连接对象，还是通过回调函数间接推送？

**决策**：**通过回调函数**。

**原因**：
1. 解耦架构：核心模块不应依赖 Web 框架（FastAPI/Starlette），回调机制使核心模块可独立测试
2. 灵活替换：未来替换 Web 框架时，只需修改路由层的回调包装，核心模块无需改动
3. 可测试性：单元测试中注入模拟回调即可验证进度推送逻辑，无需启动 WebSocket 服务
4. 职责单一：`ToolRegistry` 负责工具调度，不负责网络传输

### 8.2 为什么选择 FastAPI 原生 WebSocket 而非独立方案

**问题**：WebSocket 实现应当使用 FastAPI 原生支持还是独立方案（如 Socket.IO）？

**决策**：**FastAPI 原生 WebSocket**。

**原因**：
1. 与 HTTP 路由共享同一端口，无需额外部署
2. 原生 `async/await` 支持，与异步路由风格一致
3. 不需要 Socket.IO 的额外依赖和传输层抽象（仅需文本帧）
4. 心跳检测简单，`ping/pong` 帧即可

### 8.3 为什么前端不使用框架

**问题**：前端应当使用 React/Vue 等框架还是原生 JS？

**决策**：**原生 JS**。

**原因**：
1. 页面复杂度低（工具卡片列表 + 表单 + 进度展示），无需框架的状态管理能力
2. 零构建依赖，开发调试简单，无需 webpack/npm 等工具链
3. 未来迁移到 Electron 时，原生 JS 代码可直接复用
4. 打包体积小，减少 PyInstaller 的负担

### 8.4 为什么 SPA 路由通过 hash 实现而非 History API

**问题**：前端路由应当使用 hash 还是 History API？

**决策**：**Hash 路由**。

**原因**：
1. 静态文件服务不需要服务器端路由配置，简单可靠
2. 无需处理 404 兜底，避免 FastAPI 静态文件挂载的兼容问题
3. 对用户透明，工具集场景下 URL 美观度不重要