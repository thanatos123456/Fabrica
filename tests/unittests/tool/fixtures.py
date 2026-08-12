"""tool 模块共享测试工具类与辅助函数。

避免 test_tool_base / test_tool_registry / test_resource_pool
三处测试重复定义同名工具类与单例重置逻辑。
"""

import asyncio

from fabrica.tool import ParamDef, ToolBase, ToolRegistry


# ============================================================================
# 工具类
# ============================================================================

class DummyTool(ToolBase):
    """完整实现的工具，记录生命周期钩子调用。"""

    name = "dummy"
    title = "Dummy Tool"
    description = "用于测试的完整工具"
    icon = "🔧"
    params = []
    version = "1.0.0"
    category = "test"

    def __init__(self):
        self.init_called = False
        self.cancel_called = False
        self.complete_called = False
        self.last_result = None

    async def on_init(self):
        self.init_called = True

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        return {"ok": True}

    async def on_cancel(self):
        self.cancel_called = True

    async def on_complete(self, result):
        self.complete_called = True
        self.last_result = result


class CpuTool(ToolBase):
    """CPU 密集型工具，传入 seconds 控制睡眠时长。"""

    name = "cpu_tool"
    title = "CPU Tool"
    description = "cpu intensive tool"
    cpu_intensive = True

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        await asyncio.sleep(params.get("seconds", 0.1))
        return {"cpu": True}


class CleanupTool(ToolBase):
    """带中间产物清理钩子的工具（测试 TaskRegistry 清理编排）。"""

    name = "cleanup_tool"
    title = "Cleanup Tool"
    description = "测试产物清理钩子"
    icon = "🧹"
    params = []

    def __init__(self):
        self.cleanup_calls = []
        self.orphan_calls = []

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        return {"status": "completed", "tool": self.name, "report": {}}

    def extract_refs(self, result):
        return {"h1"}

    def cleanup_task(self, result, referenced_ids):
        self.cleanup_calls.append((result, set(referenced_ids)))
        return {"keyframes": 0, "features": 0, "output": 0}

    def cleanup_orphans(self, referenced_ids, referenced_outputs=()):
        self.orphan_calls.append((set(referenced_ids), set(referenced_outputs)))
        return {"keyframes": 1, "features": 2, "output": 0}


class IOTool(ToolBase):
    """IO 密集型工具（默认 cpu_intensive=False），传入 seconds 控制睡眠时长。"""

    name = "io_tool"
    title = "IO Tool"
    description = "io bound tool"

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        await asyncio.sleep(params.get("seconds", 0.1))
        return {"io": True}


class ParamTool(ToolBase):
    """带参数定义的完整工具。"""

    name = "param_tool"
    title = "Param Tool"
    icon = "🔢"
    params = [
        ParamDef(
            key="threshold",
            label="阈值",
            type="float",
            default=0.5,
            validation={"min": 0, "max": 1},
        ),
    ]

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        return {}


class CancellableTool(ToolBase):
    """可通过 ctx.cancelled 提前退出的工具，记录取消回调。"""

    name = "cancellable"
    title = "Cancellable Tool"

    def __init__(self):
        self.cancel_called = False

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        while not ctx.cancelled:
            await asyncio.sleep(0.05)
        return {"cancelled": True}

    async def on_cancel(self):
        self.cancel_called = True


class RejectingTool(ToolBase):
    """参数校验失败的工具。"""

    name = "rejecting"
    title = "Rejecting Tool"

    async def on_init(self):
        pass

    async def validate(self, params):
        return ["参数错误"]

    async def run(self, params, ctx):
        return {}


class FailingTool(ToolBase):
    """执行阶段抛异常的工具。"""

    name = "failing"
    title = "Failing Tool"

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        raise RuntimeError("boom")


class MissingNameTool(ToolBase):
    """缺少 name 属性的工具。"""

    title = "No Name Tool"

    async def on_init(self):
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        return {}


class UnimplementedTool(ToolBase):
    """未实现抽象方法 validate / run 的工具。"""

    name = "unimplemented"

    async def on_init(self):
        pass


# ============================================================================
# 辅助函数
# ============================================================================

def fresh_registry() -> ToolRegistry:
    """重置单例并返回一个全新的工具注册中心。

    Returns:
        全新的 ToolRegistry 实例。
    """
    ToolRegistry._instance = None
    registry = ToolRegistry()
    # 测试隔离：关闭真实文件持久化，避免污染真实 data/tasks.json
    # 与既有断言。需验证持久化时由测试另行设置 _history_path。
    registry._history_path = None
    return registry


def reset_registry(registry: ToolRegistry) -> None:
    """关闭注册中心资源池并重置单例，用于测试隔离。

    Args:
        registry: 待清理的注册中心实例。
    """
    registry.shutdown()
    ToolRegistry._instance = None