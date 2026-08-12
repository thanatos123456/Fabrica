"""视频验重工具（T4.1）。

定义 VideoDedupTool 工具类，通过 @tool.register 注册到 Fabrica 平台。
本阶段仅实现工具外壳（元信息、参数定义、校验与占位执行），
L1 文件哈希 + L2 pHash 序列的算法逻辑在 T4.2-T4.7 实现。
"""

import hashlib
import os
import shutil
from typing import Any, Dict, List, Sequence, Set

from fabrica.tool import ParamDef, ToolBase, tool, validate_param
from fabrica.utils.config import get_config
from fabrica.utils.logger import get_logger
# 注意：pipeline（及其背后 torch/open_clip/faiss/av 等重库）在 run() 内懒加载，
# 避免 discover()/启动时拖慢窗口显示。
from fabrica.tools.video_dedup.storage import (
    DEFAULT_FEATURE_DIR,
    DEFAULT_KEYFRAME_DIR,
    DEFAULT_REPORT_DIR,
)


# ============================================================================
# 中间产物清理辅助
# ============================================================================

def _vid_hash(video_id: str) -> str:
    """将 video_id 转为统一的产物键（md5 十六进制）。

    关键帧目录名与深度特征文件名共用该键，便于引用计数。

    Args:
        video_id: 视频标识（文件完整路径）。

    Returns:
        md5 十六进制字符串。
    """
    return hashlib.md5(video_id.encode("utf-8")).hexdigest()


def _remove_keyframes_dir(name: str) -> bool:
    """删除关键帧目录（容错）。

    Args:
        name: 目录名（即 video_id 的 md5 键）。

    Returns:
        True 表示删除成功，False 表示不存在或删除失败。
    """
    path = os.path.join(DEFAULT_KEYFRAME_DIR, name)
    if not os.path.isdir(path):
        return False
    try:
        shutil.rmtree(path, ignore_errors=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _remove_feature_file(hash_key: str) -> bool:
    """删除深度特征文件（容错）。

    Args:
        hash_key: video_id 的 md5 键。

    Returns:
        True 表示删除成功，False 表示不存在或删除失败。
    """
    path = os.path.join(DEFAULT_FEATURE_DIR, f"{hash_key}.npy")
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except Exception:  # noqa: BLE001
        return False


logger = get_logger("fabrica.tools.video_dedup")


def _merge_config(params: Dict[str, Any]) -> Dict[str, Any]:
    """合并 config.yaml 默认值与前端参数，前端参数优先。

    从 config.yaml 的 tools.video_dedup 配置节读取默认值，
    再以用户传入的 params 覆盖，组装成级联验重配置 cfg。

    Args:
        params: 用户传入的参数字典。

    Returns:
        合并后的级联验重配置字典。
    """
    sample = get_config("tools.video_dedup.sample", {}) or {}
    l2_cfg = get_config("tools.video_dedup.l2", {}) or {}
    l3_cfg = get_config("tools.video_dedup.l3", {}) or {}
    storage_cfg = get_config("tools.video_dedup.storage", {}) or {}

    cfg = {
        "input_dir": params.get("input_dir"),
        "output": params.get("output"),
        "recursive": params.get("recursive", False),
        # 计算设备：前端参数优先，回退到配置默认
        "device": params.get("device", get_config("tools.video_dedup.device", "auto")),
        # L2 阈值
        "l2_threshold": params.get("threshold", l2_cfg.get("confirm", 0.90)),
        "frame_thresh": l2_cfg.get("frame_thresh", 16),
        "suspect_threshold": l2_cfg.get("suspect", 0.50),
        "hit_threshold": l2_cfg.get("hit_threshold", 3),
        "k": l2_cfg.get("search_k", 32),
        # L2 并行抽帧线程数（None 时使用默认值 min(4, cpu_count)）
        "l2_workers": params.get("l2_workers")
        or l2_cfg.get("workers"),
        # L3 阈值
        "l3_sim_thresh": l3_cfg.get("sim_thresh", 0.92),
        "l3_confirm": l3_cfg.get("confirm", 0.85),
        "l3_search_k": l3_cfg.get("search_k", 32),
        "l3_hit_threshold": l3_cfg.get("hit_threshold", 1),
        # 抽帧采样参数
        "sample_min_frames": sample.get("min_frames", 16),
        "sample_max_frames": sample.get("max_frames", 100),
        "sample_target_fps": sample.get("target_fps", 1.0),
        "sample_frame_interval": sample.get("frame_interval", 5.0),
        "sample_resize": tuple(sample.get("resize", [224, 224])),
        # 存储路径：内部测试钩子 db_path 优先，其次配置默认
        "db_path": params.get("db_path")
        or storage_cfg.get("db_path")
        or get_config("fabrica.storage.db_path"),
    }
    return cfg


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
        "对视频目录执行三级验重（L1 文件哈希 + L2 pHash 序列 + L3 CLIP 深度特征），"
        "识别完全重复、内容相似与语义级重复（含水印/裁剪/字幕变体）的视频。"
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
            default="",
            description=(
                "输出报告（可选）。留空时自动保存到 "
                "data/video_dedup/reports/{任务ID}.json；"
                "填写绝对路径则保存到指定位置。"
            ),
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
    ) -> List[str]:
        """参数校验。

        校验 input_dir 必填，并对各参数套用 validate_param 规则。

        Args:
            params: 用户传入的参数字典。

        Returns:
            List[str]: 错误消息列表，为空表示校验通过。
        """
        # 必填参数检查
        input_dir = params.get("input_dir")
        if input_dir is None or str(input_dir).strip() == "":
            return ["缺少必填参数 input_dir"]

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

        return errors

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
        ctx.report_progress(0, "开始视频验重", "初始化")
        # 重库（torch/faiss/av 等）仅在实际执行任务时懒加载，避免拖慢启动
        from fabrica.tools.video_dedup.pipeline import CascadePipeline
        # 合并 config.yaml 默认值与前端参数（前端参数优先）
        cfg = _merge_config(params)
        # 输出报告按任务隔离：默认写入受管 reports 目录、以 task_id 命名
        cfg["output"] = self._resolve_output(
            cfg.get("output"), getattr(ctx, "task_id", None)
        )
        pipeline = CascadePipeline()
        report = pipeline.run_pipeline(
            cfg,
            progress_cb=ctx.report_progress,
            log_cb=ctx.log,
            cancel_event=getattr(ctx, "_cancel_event", None),
        )
        if report["cancelled"]:
            ctx.report_progress(100, "已取消", "")
            return {"status": "cancelled", "tool": self.name, "report": report}
        ctx.report_progress(100, "完成", "")
        return {"status": "completed", "tool": self.name, "report": report}

    @staticmethod
    def _resolve_output(user_output, task_id) -> str:
        """确定本任务的报告输出绝对路径。

        用户提供绝对路径则原样使用；否则使用受管 reports 目录 +
        任务 ID 生成唯一文件，避免多任务互相覆盖。

        Args:
            user_output: 用户传入的输出路径（可能为空/相对）。
            task_id: 任务唯一标识。

        Returns:
            输出报告绝对路径。
        """
        if user_output and os.path.isabs(user_output):
            return user_output
        os.makedirs(DEFAULT_REPORT_DIR, exist_ok=True)
        return os.path.join(DEFAULT_REPORT_DIR, f"{task_id or 'report'}.json")

    # ---- 中间产物清理钩子（供 TaskRegistry 编排）----

    def extract_refs(self, result: Any) -> Set[str]:
        """提取任务结果引用的产物键（video_id 的 md5 散列）集合。

        供注册中心做跨任务引用计数，避免误删仍被其他任务引用的产物。

        Args:
            result: 任务执行结果（含 report）。

        Returns:
            产物键集合（md5 十六进制）。
        """
        if not isinstance(result, dict):
            return set()
        report = result.get("report", {})
        if not isinstance(report, dict):
            return set()
        hashes: Set[str] = set()

        # keyframes 的键即 video_id
        for vid in (report.get("keyframes") or {}):
            hashes.add(_vid_hash(vid))
        # final_groups 内 videos[].id
        for group in (report.get("final_groups") or []):
            for v in (group.get("videos") or []):
                hashes.add(_vid_hash(v["id"]))
        # l1_groups（id 列表）
        for group in (report.get("l1_groups") or []):
            for vid in group:
                hashes.add(_vid_hash(vid))
        # l2_pairs / l3_pairs（[a, b, score]）
        for pair in ((report.get("l2_pairs") or [])
                     + (report.get("l3_pairs") or [])):
            for vid in pair[:2]:
                hashes.add(_vid_hash(vid))
        return hashes

    def extract_outputs(self, result: Any) -> Set[str]:
        """提取任务结果引用的输出报告绝对路径集合。

        供注册中心做跨任务引用计数，避免全局清理误删仍被引用的报告。

        Args:
            result: 任务执行结果（含 report）。

        Returns:
            输出报告绝对路径集合。
        """
        if not isinstance(result, dict):
            return set()
        report = result.get("report", {})
        if not isinstance(report, dict):
            return set()
        out = report.get("_output")
        return {out} if out else set()

    def cleanup_task(
        self, result: Any, referenced_ids: Set[str],
    ) -> Dict[str, int]:
        """删除本任务引用、且不再被任何任务引用的中间产物。

        Args:
            result: 被删除任务的执行结果。
            referenced_ids: 其余任务仍引用的产物键集合。

        Returns:
            {"keyframes", "features", "output"} 删除计数。
        """
        counts: Dict[str, int] = {
            "keyframes": 0, "features": 0, "output": 0,
        }
        if not isinstance(result, dict):
            return counts
        orphan = self.extract_refs(result) - set(referenced_ids)
        for key in orphan:
            if _remove_keyframes_dir(key):
                counts["keyframes"] += 1
            if _remove_feature_file(key):
                counts["features"] += 1
        report = result.get("report") or {}
        output = report.get("_output")
        if output:
            try:
                if os.path.isfile(output):
                    os.remove(output)
                    counts["output"] += 1
            except Exception:  # noqa: BLE001
                pass
        return counts

    def cleanup_orphans(
        self,
        referenced_ids: Set[str],
        referenced_outputs: Sequence[str] = (),
    ) -> Dict[str, int]:
        """清理所有未被任何任务引用的关键帧目录、特征文件与报告。

        Args:
            referenced_ids: 所有任务仍引用的产物键集合。
            referenced_outputs: 所有任务仍引用的输出报告绝对路径集合。

        Returns:
            {"keyframes", "features", "output"} 删除计数。
        """
        counts: Dict[str, int] = {
            "keyframes": 0, "features": 0, "output": 0,
        }
        referenced = set(referenced_ids)
        if os.path.isdir(DEFAULT_KEYFRAME_DIR):
            for name in os.listdir(DEFAULT_KEYFRAME_DIR):
                if name not in referenced:
                    if _remove_keyframes_dir(name):
                        counts["keyframes"] += 1
        if os.path.isdir(DEFAULT_FEATURE_DIR):
            for name in os.listdir(DEFAULT_FEATURE_DIR):
                if name.endswith(".npy") and name[:-4] not in referenced:
                    try:
                        os.remove(
                            os.path.join(DEFAULT_FEATURE_DIR, name)
                        )
                        counts["features"] += 1
                    except Exception:  # noqa: BLE001
                        pass
        # 清理未被任何任务引用的判重报告
        ref_outputs = set(referenced_outputs or ())
        if os.path.isdir(DEFAULT_REPORT_DIR):
            for name in os.listdir(DEFAULT_REPORT_DIR):
                path = os.path.join(DEFAULT_REPORT_DIR, name)
                if (
                    name.endswith(".json")
                    and os.path.isfile(path)
                    and path not in ref_outputs
                ):
                    try:
                        os.remove(path)
                        counts["output"] += 1
                    except Exception:  # noqa: BLE001
                        pass
        return counts

    async def on_cancel(self) -> None:
        """取消回调。

        取消信号经 TaskContext.cancel() 传播，pipeline 在各 stage
        边界检测并中止；此处记录日志即可。
        """
        logger.info("video_dedup 任务已取消")