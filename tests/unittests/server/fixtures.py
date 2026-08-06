"""server 模块共享测试工具类与辅助函数。

复用 tool 模块的公共夹具（DummyTool / ParamTool / CancellableTool 及
单例重置逻辑），并新增覆盖 10 种参数类型的 DemoTool，用于 REST/WebSocket
路由测试。
"""

# 先导入 tests.unittests 包以触发 aurora 路径注入，再导入 fabrica 模块。
from tests.unittests.tool.fixtures import (
    CancellableTool,
    DummyTool,
    ParamTool,
    fresh_registry,
    reset_registry,
)

from fabrica.tool import ParamDef, ToolBase


# ============================================================================
# 工具类
# ============================================================================

class DemoTool(ToolBase):
    """覆盖 10 种参数类型的演示工具，用于 ToolDetail 路由测试。"""

    name = "demo"
    title = "演示工具"
    description = "覆盖全部 10 种参数类型"
    icon = "🧪"
    version = "1.0.0"
    category = "demo"
    params = [
        ParamDef(key="s", label="字符串", type="str", default="hi"),
        ParamDef(key="i", label="整数", type="int", default=3),
        ParamDef(key="f", label="浮点", type="float", default=0.5),
        ParamDef(key="b", label="布尔", type="bool", default=True),
        ParamDef(key="p", label="路径", type="path", default="/tmp"),
        ParamDef(key="file", label="文件", type="file", default=""),
        ParamDef(key="d", label="目录", type="dir", default=""),
        ParamDef(key="sel", label="单选", type="select",
                 options=["a", "b", "c"], default="b"),
        ParamDef(key="ms", label="多选", type="multi_select",
                 options=["x", "y"], default=["x"]),
        ParamDef(key="pw", label="密码", type="password", default=""),
    ]

    async def on_init(self) -> None:
        pass

    async def validate(self, params):
        return []

    async def run(self, params, ctx):
        return {"ok": True}


__all__ = [
    # 工具类
    "DemoTool",
    "DummyTool",
    "ParamTool",
    "CancellableTool",
    # 辅助函数
    "fresh_registry",
    "reset_registry",
]