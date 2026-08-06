"""Fabrica REST API 路由定义。

定义 7 个 REST 端点（工具列表/详情/执行、任务历史/详情/取消/删除）
与 WebSocket 实时推送端点。配套 Pydantic 请求/响应模型，
并统一错误响应格式（基于 nemesis）。
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from fabrica.tool import (
    ToolMeta,
    TaskSummary,
    TaskDetail,
    ParamDefSchema,
)
from fabrica.utils.exceptions import (
    ToolNotFoundError,
    TaskNotFoundError,
)

router = APIRouter(prefix="/api")


# ============================================================================
# 请求/响应模型
# ============================================================================

class RunRequest(BaseModel):
    """工具执行请求体。"""

    params: Dict[str, Any] = Field(
        default_factory=dict, description="执行参数"
    )


class RunResponse(BaseModel):
    """工具执行响应体。"""

    task_id: str = Field(description="任务唯一标识")
    status: str = Field(description="任务初始状态")


class CancelResponse(BaseModel):
    """任务取消响应体。"""

    task_id: str = Field(description="任务唯一标识")
    cancelled: bool = Field(description="是否已触发取消信号")


class LogEntry(BaseModel):
    """日志条目模型。"""

    level: str = Field(description="日志级别")
    message: str = Field(description="日志消息")
    timestamp: datetime = Field(description="日志时间")


class ToolDetail(ToolMeta):
    """工具详细信息（含参数定义）。"""

    params: List[ParamDefSchema] = Field(
        default_factory=list, description="参数定义列表"
    )


# ============================================================================
# 依赖
# ============================================================================

def get_registry(request: Request) -> Any:
    """获取工具注册中心实例（来自应用状态）。"""
    return request.app.state.tool_registry


# ============================================================================
# 工具端点
# ============================================================================

@router.get("/tools", response_model=List[ToolMeta])
async def list_tools(registry: Any = Depends(get_registry)) -> List[ToolMeta]:
    """获取所有工具元信息列表。"""
    return registry.list_tools()


@router.get("/tools/{name}", response_model=ToolDetail)
async def get_tool(name: str, registry: Any = Depends(get_registry)) -> ToolDetail:
    """获取单个工具详细信息（含参数定义）。"""
    try:
        meta = registry.get_tool_meta(name)
        schema = registry.get_schema(name)
    except KeyError as e:
        raise ToolNotFoundError(f"工具不存在: {name}") from e
    params = [ParamDefSchema.from_param_def(p) for p in schema]
    return ToolDetail(**meta.model_dump(), params=params)


@router.post("/tools/{name}/run", response_model=RunResponse)
async def run_tool(
    name: str,
    body: RunRequest,
    registry: Any = Depends(get_registry),
) -> RunResponse:
    """提交工具执行请求，返回任务唯一标识。"""
    try:
        task_id = registry.run_tool(name, body.params)
    except KeyError as e:
        raise ToolNotFoundError(f"工具不存在: {name}") from e
    return RunResponse(task_id=task_id, status="pending")


# ============================================================================
# 任务端点
# ============================================================================

@router.get("/tasks", response_model=List[TaskSummary])
async def list_tasks(registry: Any = Depends(get_registry)) -> List[TaskSummary]:
    """获取任务历史列表。"""
    return registry.list_tasks()


@router.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str, registry: Any = Depends(get_registry)) -> TaskDetail:
    """获取单个任务完整状态和结果。"""
    try:
        return registry.get_task(task_id)
    except KeyError as e:
        raise TaskNotFoundError(f"任务不存在: {task_id}") from e


@router.post("/tasks/{task_id}/cancel", response_model=CancelResponse)
async def cancel_task(
    task_id: str,
    registry: Any = Depends(get_registry),
) -> CancelResponse:
    """取消正在执行的任务。"""
    cancelled = registry.cancel_task(task_id)
    if not cancelled:
        raise TaskNotFoundError(f"任务不存在: {task_id}")
    return CancelResponse(task_id=task_id, cancelled=True)


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    registry: Any = Depends(get_registry),
) -> Dict[str, Any]:
    """删除任务记录。"""
    deleted = registry.delete_task(task_id)
    if not deleted:
        raise TaskNotFoundError(f"任务不存在: {task_id}")
    return {"task_id": task_id, "deleted": True}


# ============================================================================
# WebSocket 端点
# ============================================================================

@router.websocket("/ws/tasks/{task_id}")
async def ws_task(websocket: WebSocket, task_id: str) -> None:
    """为指定任务提供实时进度/日志/完成/错误事件推送。

    通过回调机制与 ToolRegistry 交互（回调解耦，不直接持有 WebSocket 对象）：
    回调将事件写入 asyncio.Queue，由后台发送任务异步推送到客户端。
    支持心跳（ping→pong），客户端断开时自动注销回调。
    """
    registry = websocket.app.state.tool_registry

    # 校验任务存在
    try:
        registry.get_task(task_id)
    except KeyError:
        await websocket.close(code=4404, reason="task not found")
        return

    await websocket.accept()

    queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()
    terminal = asyncio.Event()

    def _enqueue(event: Dict[str, Any]) -> None:
        queue.put_nowait(event)

    def on_progress(percent: int, message: str) -> None:
        _enqueue({
            "type": "progress",
            "task_id": task_id,
            "percent": percent,
            "message": message,
        })

    def on_log(level: str, message: str) -> None:
        _enqueue({
            "type": "log",
            "task_id": task_id,
            "level": level,
            "message": message,
        })

    def on_complete(result: Any) -> None:
        _enqueue({"type": "complete", "task_id": task_id, "result": result})
        terminal.set()

    def on_error(error: Any) -> None:
        _enqueue({"type": "error", "task_id": task_id, "error": str(error)})
        terminal.set()

    # 注册回调（仅持有 queue/task_id，不持有 websocket 对象）
    registry.register_progress_callback(task_id, on_progress)
    registry.register_log_callback(task_id, on_log)
    registry.register_complete_callback(task_id, on_complete)
    registry.register_error_callback(task_id, on_error)

    # 入队连接确认事件，再启动后台发送任务
    _enqueue({"type": "connected", "task_id": task_id})

    async def sender() -> None:
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                await websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass

    send_task = asyncio.create_task(sender())

    try:
        while True:
            recv_task = asyncio.create_task(websocket.receive_text())
            term_task = asyncio.create_task(terminal.wait())
            done, pending = await asyncio.wait(
                {recv_task, term_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if recv_task in done and not recv_task.cancelled():
                try:
                    message = recv_task.result()
                except WebSocketDisconnect:
                    break
                # 心跳：响应客户端 ping（统一经发送队列，避免并发发送）
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    data = {"type": message}
                if data.get("type") == "ping":
                    _enqueue({"type": "pong"})
            if terminal.is_set():
                break
    except WebSocketDisconnect:
        pass
    finally:
        # 注销回调
        registry.unregister_progress_callback(task_id)
        registry.unregister_log_callback(task_id)
        registry.unregister_complete_callback(task_id)
        registry.unregister_error_callback(task_id)
        # 停止发送任务并排空剩余事件
        queue.put_nowait(None)
        try:
            await asyncio.wait_for(send_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            send_task.cancel()


__all__ = ["router"]