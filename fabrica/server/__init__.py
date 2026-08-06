"""Fabrica Web 服务层。

包含 FastAPI 应用工厂（T3.1）、REST API 路由（T3.2）和 WebSocket 端点（T3.3）。
"""

import os
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
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

    # ---- 8. 挂接 API 路由 ----
    app.include_router(router)

    # ---- 9. 基础路由 ----
    @app.get("/")
    async def root():
        """根路由，返回平台欢迎信息。"""
        return {
            "name": "Fabrica",
            "version": "0.1.0",
            "status": "running",
        }

    @app.get("/health")
    async def health():
        """健康检查端点。"""
        return {"status": "ok"}

    # 保存工具注册中心引用，供 T3.2 路由使用
    app.state.tool_registry = tool_registry

    return app


__all__ = ["create_app"]