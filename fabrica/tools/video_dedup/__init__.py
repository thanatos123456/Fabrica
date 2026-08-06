"""视频验重工具（T4.1）。

定义 VideoDedupTool 工具类，通过 @tool.register 注册到 Fabrica 平台。
本阶段仅实现工具外壳（元信息、参数定义、校验与占位执行），
L1 文件哈希 + L2 pHash 序列的算法逻辑在 T4.2-T4.7 实现。
"""

from typing import Any, Dict, List

from fabrica.tool import ParamDef, ToolBase, tool, validate_param
from fabrica.utils.exceptions import (
    ParamInvalidError,
    ParamMissingError,
)
from fabrica.utils.logger import get_logger
from fabrica.tools.video_dedup.pipeline import CascadePipeline


logger = get_logger("fabrica.tools.video_dedup")


@tool.register
class VideoDedupTool(ToolBase):
    """视频重复检测工具。

    对输入目录中的视频执行两级验重：
    - L1：文件 MD5 哈希，识别字节级完全相同的视频
    - L2：pHash 感知哈希序列，识别内容相似但编码不同的视频

    算法逻辑在 T4.2-T4.7 逐模块实现，本类提供注册与调度外壳。
    """

    name = "video_dedup"
    title = "视频重复检测"
    description = (
        "对视频目录执行两级验重（L1 文件哈希 + L2 pHash 序列），"
        "识别完全重复与内容相似的视频。"
    )
    icon = "🎞️"
    version = "1.0.0"
    category = "视频处理"
    cpu_intensive = True  # 视频抽帧/哈希为 CPU 密集型，提交线程池执行

    params: List[ParamDef] = [
        ParamDef(
            key="input_dir",
            label="输入目录",
            type="dir",
            required=True,
            description="待检测视频所在目录",
        ),
        ParamDef(
            key="output",
            label="输出文件",
            type="str",
            default="dedup_result.json",
            description="判重结果输出文件名",
        ),
        ParamDef(
            key="recursive",
            label="递归扫描子目录",
            type="bool",
            default=False,
            description="是否递归扫描子目录中的视频",
        ),
        ParamDef(
            key="device",
            label="计算设备",
            type="select",
            default="auto",
            options=["auto", "cpu", "cuda"],
            description="计算设备，auto 表示自动检测",
        ),
        ParamDef(
            key="threshold",
            label="判定阈值",
            type="float",
            default=0.9,
            validation={"min": 0, "max": 1},
            description="L2 序列相似度判定阈值（0~1）",
        ),
    ]

    async def on_init(self) -> None:
        """初始化钩子。

        占位实现。后续阶段在此完成依赖检查（如 PyAV/FAISS）与
        模型加载（如 CLIP）等耗时初始化。
        """
        logger.info("video_dedup 工具初始化完成")

    async def validate(
        self, params: Dict[str, Any],
    ) -> None:
        """参数校验。

        校验 input_dir 必填，并对各参数套用 validate_param 规则。

        Args:
            params: 用户传入的参数字典。

        Raises:
            ParamMissingError: input_dir 缺失时。
            ParamInvalidError: 参数值不合法时。
        """
        # 必填参数检查
        input_dir = params.get("input_dir")
        if input_dir is None or str(input_dir).strip() == "":
            raise ParamMissingError("缺少必填参数 input_dir")

        # 逐参数套用通用校验规则
        errors: List[str] = []
        for param_def in self.params:
            if param_def.key not in params:
                continue
            errors.extend(
                validate_param(params[param_def.key], param_def)
            )

        # 枚举型参数：device 必须在可选列表内
        device = params.get("device")
        if device is not None:
            device_opt = next(
                (p.options for p in self.params if p.key == "device"), []
            )
            if device not in device_opt:
                errors.append(
                    f"device 取值 {device} 不在允许范围 {device_opt}"
                )

        if errors:
            raise ParamInvalidError("; ".join(errors))

    async def run(
        self, params: Dict[str, Any], ctx: Any,
    ) -> Dict[str, Any]:
        """主执行逻辑。

        将参数组装为级联验重配置，调用 CascadePipeline 执行
        L1 哈希 + L2 pHash + L3 深度特征（可用时）的完整流程，
        并把进度/日志/取消信号接入 TaskContext。

        Args:
            params: 用户传入的参数字典。
            ctx: 任务执行上下文（TaskContext）。

        Returns:
            Dict[str, Any]: 执行结果（status + 验重报告）。
        """
        ctx.report_progress(0, "开始视频验重")
        cfg = {
            "input_dir": params.get("input_dir"),
            "output": params.get("output"),
            "recursive": params.get("recursive", False),
            "device": params.get("device", "auto"),
            "l2_threshold": params.get("threshold", 0.9),
            # 内部测试钩子：允许注入数据库路径以隔离测试数据；生产调用不传
            "db_path": params.get("db_path"),
        }
        pipeline = CascadePipeline()
        report = pipeline.run_pipeline(
            cfg,
            progress_cb=ctx.report_progress,
            log_cb=ctx.log,
            cancel_event=getattr(ctx, "_cancel_event", None),
        )
        if report["cancelled"]:
            ctx.report_progress(100, "已取消")
            return {"status": "cancelled", "tool": self.name, "report": report}
        ctx.report_progress(100, "完成")
        return {"status": "completed", "tool": self.name, "report": report}

    async def on_cancel(self) -> None:
        """取消回调。

        取消信号经 TaskContext.cancel() 传播，pipeline 在各 stage
        边界检测并中止；此处记录日志即可。
        """
        logger.info("video_dedup 任务已取消")