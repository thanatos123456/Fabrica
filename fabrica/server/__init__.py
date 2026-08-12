"""Fabrica Web 服务层。

包含 FastAPI 应用工厂（T3.1）、REST API 路由（T3.2）和 WebSocket 端点（T3.3）。
"""

import os
import sys
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from fabrica.utils.config import get_config
from fabrica.utils.exceptions import exception_response
from fabrica.utils.logger import logger
from fabrica.server.routes import router

# __file__ 位于 nexus/Fabrica/fabrica/server/__init__.py
# 向上两级到达 fabrica 包根目录（nexus/Fabrica/fabrica/）
# 在 PyInstaller 打包环境下，__file__ 指向 _MEIPASS 内的临时目录，
# 此时需要从 sys._MEIPASS 解析静态资源路径。
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _PACKAGE_ROOT = os.path.join(sys._MEIPASS, "fabrica")
else:
    _PACKAGE_ROOT = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )


def create_app(
    config: Optional[Dict[str, Any]] = None,
    tool_registry: Any = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    注册 CORS 中间件、全局异常处理器、请求日志中间件，
    挂载静态资源并挂接 API 路由。

    Args:
        config: 配置字典（可选）。为 None 时通过 get_config() 读取。
            传入时使用 `config["server"]` 内的 cors_origins / static_dir。
        tool_registry: 工具注册中心实例（可选）。为 None 时回退到全局单例。

    Returns:
        FastAPI: 配置好的应用实例。
    """
    # ---- 1. 解析服务配置 ----
    if config is not None:
        server_cfg = config.get("server", {}) if isinstance(config, dict) else {}
        cors_origins = server_cfg.get("cors_origins", ["*"])
        static_dir = server_cfg.get("static_dir", "server/static")
    else:
        cors_origins = get_config("fabrica.server.cors_origins", ["*"])
        static_dir = get_config("fabrica.server.static_dir", "server/static")

    # ---- 2. 工具注册中心 ----
    if tool_registry is None:
        from fabrica.tool import tool as tool_registry

    # ---- 3. 创建应用 ----
    app = FastAPI(
        title="Fabrica",
        description="Fabrica - 工具集平台",
        version="0.1.0",
    )

    # ---- 4. 注册 CORS 中间件 ----
    # 不启用 allow_credentials，避免 allow_origins=["*"] 时的非法组合
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 5. 全局异常处理器（基于 nemesis 统一错误格式）----
    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception):
        response = exception_response(exc)
        status_code = response.pop("status_code", 500)
        return JSONResponse(status_code=status_code, content=response)

    # ---- 6. 请求日志中间件 ----
    @app.middleware("http")
    async def _request_logging(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            f"{request.method} {request.url.path} -> "
            f"{response.status_code} ({duration:.3f}s)"
        )
        return response

    # ---- 7. 挂载静态资源 ----
    # static_dir 为相对 fabrica 包根目录的路径（如 "server/static"）
    static_path = os.path.join(
        _PACKAGE_ROOT, *static_dir.replace("\\", "/").split("/")
    )
    if os.path.isdir(static_path):
        app.mount(
            "/static",
            StaticFiles(directory=static_path, html=True),
            name="static",
        )
    else:
        logger.warning("静态资源目录不存在，跳过挂载: %s", static_path)

    # ---- 7b. 挂载关键帧图像目录（T6.3）----
    from fabrica.tools.video_dedup.storage import DEFAULT_KEYFRAME_DIR
    # 兼容 PyInstaller：开发环境用默认路径，打包后使用 exe 同级 data 目录
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        _exe_dir = os.path.dirname(sys.executable)
        _keyframe_dir = os.path.join(_exe_dir, "data", "keyframes")
    else:
        _keyframe_dir = DEFAULT_KEYFRAME_DIR
    # 关键帧目录在任务运行时才被写入，启动时可能尚不存在；
    # 先确保目录存在再无条件挂载，避免 /keyframes 404、图片无法展示。
    os.makedirs(_keyframe_dir, exist_ok=True)
    app.mount(
        "/keyframes",
        StaticFiles(directory=_keyframe_dir),
        name="keyframes",
    )

    # ---- 8. 挂接 API 路由 ----
    app.include_router(router)

    # ---- 9. 基础路由 ----
    @app.get("/")
    async def root():
        """根路由：返回 Web 前端入口 index.html。"""
        from fastapi.responses import FileResponse
        index_path = os.path.join(static_path, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path, media_type="text/html")
        return {
            "name": "Fabrica",
            "version": "0.1.0",
            "status": "running",
            "message": "index.html not found",
        }

    @app.get("/health")
    async def health():
        """健康检查端点。"""
        return {"status": "ok"}

    # 保存工具注册中心引用，供 T3.2 路由使用
    app.state.tool_registry = tool_registry

    return app


__all__ = ["create_app"]