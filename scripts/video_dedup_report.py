#!/usr/bin/env python3
"""CLI 视频验重报告脚本。

调用 video_dedup 工具的 CascadePipeline 对输入视频执行去重，
但不做删除，而是生成 Markdown 验重报告输出到 data/dedup_reports/。

支持的输入方式：
- 单个母目录（默认递归扫描其下所有子目录中的视频）
- 多个目录 / 视频文件混合输入（全局聚合去重）

用法：
    python3 scripts/video_dedup_report.py --input <DIR_OR_FILE> [<DIR_OR_FILE> ...]
    python3 scripts/video_dedup_report.py --input /data/videos --skip-l3

注：本脚本为独立 CLI 工具，不纳入 pytest 收集。
"""

import argparse
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime

# ============================================================================
# 路径注入：构造 aurora 虚拟包 + 注入 Fabrica 项目根目录
# （复用 tests/conftest.py 与 video_dedup_eval.py 的注入逻辑，使脚本可独立运行）
# ============================================================================
_FABRICA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NEXUS_ROOT = os.path.dirname(_FABRICA_ROOT)
_OMNIPIVOT_ROOT = os.path.dirname(_NEXUS_ROOT)
_AURORA_PATH = os.path.join(_OMNIPIVOT_ROOT, "aurora", "python")
_AURORA_ROOT = os.path.join(_OMNIPIVOT_ROOT, "aurora")

for _p in (_AURORA_PATH, _FABRICA_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if "aurora" not in sys.modules:
    _aurora_pkg = types.ModuleType("aurora")
    _aurora_pkg.__path__ = [_AURORA_ROOT]
    sys.modules["aurora"] = _aurora_pkg
if "aurora.python" not in sys.modules:
    _aurora_python_pkg = types.ModuleType("aurora.python")
    _aurora_python_pkg.__path__ = [_AURORA_PATH]
    sys.modules["aurora.python"] = _aurora_python_pkg

from fabrica.tools.video_dedup import _merge_config  # noqa: E402
from fabrica.tools.video_dedup.storage import DEFAULT_DB_PATH  # noqa: E402
from fabrica.tools.video_dedup.extractors.deepfeat import (  # noqa: E402
    CLIPExtractor,
)
from fabrica.tools.video_dedup.pipeline import (  # noqa: E402
    VIDEO_EXTENSIONS,
    CascadePipeline,
)
from fabrica.utils.logger import get_logger  # noqa: E402


logger = get_logger("fabrica.scripts.video_dedup_report")


# ============================================================================
# 文件大小格式化
# ============================================================================

def _human_size(num: float) -> str:
    """将字节数格式化为可读字符串（B/KB/MB/GB）。"""
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{num} B"


# ============================================================================
# 输入聚合
# ============================================================================

def _collect_videos(path: str, recursive: bool) -> list:
    """从单个输入路径收集视频文件路径列表。

    Args:
        path: 输入路径（目录或单个视频文件）。
        recursive: 目录是否递归扫描子目录。

    Returns:
        str 列表：视频文件绝对路径。
    """
    if os.path.isfile(path):
        return [path]
    videos = []
    for dirpath, _dirnames, filenames in os.walk(path):
        for fname in sorted(filenames):
            if os.path.splitext(fname)[1].lower() in VIDEO_EXTENSIONS:
                videos.append(os.path.join(dirpath, fname))
        if not recursive:
            break
    return videos


def _link_file(src: str, dst: str) -> None:
    """创建源视频的聚合副本。

    链接策略：硬链接优先（瞬时、不复制数据），失败时回退符号链接，
    再失败则复制文件。跨分区或无链接权限时走复制路径。

    Args:
        src: 源视频路径。
        dst: 聚合目录中的目标路径。
    """
    try:
        os.link(src, dst)
    except OSError:
        try:
            os.symlink(src, dst)
        except OSError:
            shutil.copy2(src, dst)


def _aggregate(input_paths, recursive: bool, root: str) -> tuple:
    """将多个输入路径聚合到临时目录，返回 (聚合目录, 路径映射)。

    Args:
        input_paths: 输入路径列表（目录或视频文件）。
        recursive: 目录是否递归扫描。
        root: 临时根目录，聚合子目录创建于其下。

    Returns:
        (aggr_dir, name_map)：
        - aggr_dir: 聚合后的目录（其中每个视频为聚合内路径）。
        - name_map: 聚合内路径 -> 真实源路径 的映射。
    """
    aggr_dir = os.path.join(root, "aggregated")
    os.makedirs(aggr_dir, exist_ok=True)
    name_map = {}

    # 收集所有输入的视频
    all_videos = []
    for path in input_paths:
        found = _collect_videos(path, recursive)
        logger.info("输入 %s 收集到 %d 个视频", path, len(found))
        all_videos.extend(found)

    # 以硬链接为主、符号链接/复制回退，聚合到统一目录（避免同名冲突）
    for index, src in enumerate(sorted(all_videos)):
        basename = os.path.basename(src)
        link_name = f"{index:04d}_{basename}"
        link_path = os.path.join(aggr_dir, link_name)
        _link_file(src, link_path)
        name_map[link_path] = src

    logger.info("聚合完成，共 %d 个视频", len(all_videos))
    return aggr_dir, name_map


# ============================================================================
# 去重执行
# ============================================================================

def _resolve(name_map: dict, vid: str) -> str:
    """将报告中的视频 id 映射为真实源路径。

    Args:
        name_map: 聚合路径 -> 真实路径 映射。
        vid: 视频 id（扫描得到的路径）。

    Returns:
        真实源路径；无映射时原样返回。
    """
    return name_map.get(vid, vid)


def _run(input_dir: str, recursive: bool, cfg: dict, skip_l3: bool) -> tuple:
    """执行级联验重，返回 (report, pipeline)。

    Args:
        input_dir: 扫描根目录。
        recursive: 是否递归扫描。
        cfg: 级联配置（含 input_dir/db_path/阈值）。
        skip_l3: 是否跳过 L3 深度特征。

    Returns:
        (report, pipeline)：report 为验重报告 dict；pipeline 用于关闭 db。
    """
    def _log_cb(level: str, msg: str) -> None:
        getattr(logger, level.lower(), logger.info)(msg)

    def _progress_cb(percent: int, msg: str) -> None:
        # 仅在百分比变化时打印 [N%] 前缀，避免同一百分比重复刷屏；
        # 其余仅打印消息，保留 [i/总数] 精确计数。
        if percent != _progress_cb._last:
            _progress_cb._last = percent
            logger.info("[%d%%] %s", percent, msg)
        else:
            logger.info("%s", msg)

    _progress_cb._last = None  # 记录上一次百分比

    pipeline = CascadePipeline()
    if skip_l3:
        # 临时将 CLIP 置为不可用，走 L1+L2 降级路径
        from unittest import mock
        with mock.patch.object(
            CLIPExtractor, "is_available", return_value=False
        ):
            report = pipeline.run_pipeline(
                cfg, progress_cb=_progress_cb, log_cb=_log_cb,
            )
    else:
        report = pipeline.run_pipeline(
            cfg, progress_cb=_progress_cb, log_cb=_log_cb,
        )
    # 关闭数据库连接，避免临时文件被占用
    if pipeline.storage is not None:
        pipeline.storage.close()
    return report, pipeline


# ============================================================================
# Markdown 报告生成
# ============================================================================

def _build_markdown(
    report: dict,
    input_desc: str,
    cfg: dict,
    name_map: dict,
) -> str:
    """将验重报告渲染为 Markdown 字符串。

    Args:
        report: run_pipeline 返回的报告。
        input_desc: 输入描述文本。
        cfg: 使用的级联配置。
        name_map: 聚合路径 -> 真实路径 映射。

    Returns:
        Markdown 文本。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("# 视频验重报告")
    lines.append("")
    lines.append(f"- 生成时间：{now}")
    lines.append(f"- 输入：{input_desc}")
    lines.append(f"- 计算设备：{cfg.get('device', 'auto')}")
    lines.append("")

    # ---- 执行摘要 ----
    lines.append("## 执行摘要")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 扫描视频总数 | {report.get('total_videos', 0)} |")
    lines.append(f"| L1 完全重复组 | {len(report.get('l1_groups', []))} |")
    lines.append(f"| L2 疑似对 | {len(report.get('l2_pairs', []))} |")
    lines.append(f"| L3 判重对 | {len(report.get('l3_pairs', []))} |")
    lines.append(f"| 最终去重组 | {len(report.get('final_groups', []))} |")
    lines.append(f"| 错误 | {len(report.get('errors', []))} |")
    lines.append("")

    # ---- 关键阈值 ----
    lines.append("## 关键阈值")
    lines.append("")
    lines.append("| 参数 | 值 |")
    lines.append("|---|---|")
    for key, label in (
        ("l2_threshold", "L2 判定阈值"),
        ("suspect_threshold", "L2 疑似阈值"),
        ("l3_sim_thresh", "L3 帧相似阈值"),
        ("l3_confirm", "L3 判定阈值"),
        ("hit_threshold", "命中帧数阈值"),
        ("frame_thresh", "帧汉明阈值"),
    ):
        lines.append(f"| {label} | {cfg.get(key, '-')} |")
    lines.append("")

    # ---- 去重分组明细 ----
    lines.append("## 去重分组")
    lines.append("")
    final_groups = report.get("final_groups", [])
    if not final_groups:
        lines.append("未发现重复视频。")
        lines.append("")
    else:
        for idx, group in enumerate(final_groups, start=1):
            lines.append(f"### 组 {idx}（含 {len(group)} 个视频）")
            lines.append("")
            # 按文件大小排序，推荐保留最大的、其余为候选删除
            scaled = []
            for vid in group:
                real = _resolve(name_map, vid)
                try:
                    size = os.path.getsize(vid)
                except OSError:
                    size = 0
                scaled.append((real, size))
            scaled.sort(key=lambda item: item[1], reverse=True)
            keep_real, keep_size = scaled[0]
            lines.append(f"- **建议保留**：`{keep_real}`（{_human_size(keep_size)}）")
            lines.append("")
            if len(scaled) > 1:
                lines.append("- **候选删除**（仅建议，不执行删除）：")
                for real, size in scaled[1:]:
                    lines.append(f"  - `{real}`（{_human_size(size)}）")
                lines.append("")

    # ---- L2 判重对 ----
    lines.append("## L2 判重对")
    lines.append("")
    l2_pairs = report.get("l2_pairs", [])
    if not l2_pairs:
        lines.append("无。")
    else:
        for a, b, score in l2_pairs:
            ra = _resolve(name_map, a)
            rb = _resolve(name_map, b)
            lines.append(f"- `{ra}` ↔ `{rb}`（相似度 {float(score):.4f}）")
    lines.append("")

    # ---- L3 判重对 ----
    lines.append("## L3 判重对")
    lines.append("")
    l3_pairs = report.get("l3_pairs", [])
    if not l3_pairs:
        lines.append("无。")
    else:
        for a, b, score in l3_pairs:
            ra = _resolve(name_map, a)
            rb = _resolve(name_map, b)
            lines.append(f"- `{ra}` ↔ `{rb}`（相似度 {float(score):.4f}）")
    lines.append("")

    # ---- 错误与警告 ----
    lines.append("## 错误与警告")
    lines.append("")
    errors = report.get("errors", [])
    if not errors:
        lines.append("无。")
    else:
        for err in errors:
            lines.append(f"- {err}")
    lines.append("")

    return "\n".join(lines)


def _write_report(markdown: str, out_dir: str, filename: str) -> str:
    """将 Markdown 报告写入输出目录。

    Args:
        markdown: 报告文本。
        out_dir: 输出目录（不存在则创建）。
        filename: 报告文件名。

    Returns:
        写入的报告完整路径。
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    logger.info("报告已写入 %s", path)
    return path


# ============================================================================
# 主流程
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="视频验重报告：对输入视频去重并生成 Markdown 报告"
    )
    parser.add_argument(
        "--input", nargs="+", required=True,
        help="一个或多个输入路径（目录或视频文件）",
    )
    parser.add_argument(
        "--output", default=None,
        help="报告文件名（默认按时间戳生成）",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="报告输出目录（默认 data/dedup_reports）",
    )
    parser.add_argument(
        "--no-recursive", dest="recursive",
        action="store_false", default=True,
        help="不递归扫描子目录（默认递归）",
    )
    parser.add_argument(
        "--device", default="auto",
        help="计算设备（auto/cpu/cuda，默认 auto）",
    )
    parser.add_argument(
        "--skip-l3", action="store_true",
        help="跳过 L3 深度特征（仅跑 L1+L2）",
    )
    parser.add_argument(
        "--db", default=None,
        help="结果数据库路径（默认 data/video_dedup/dedup.db）",
    )
    parser.add_argument(
        "--keep-db", action="store_true",
        help="保留结果数据库（默认已持久保存，此参数保留兼容）",
    )
    parser.add_argument(
        "--l2-threshold", type=float, default=None)
    parser.add_argument(
        "--suspect-threshold", type=float, default=None)
    parser.add_argument(
        "--l3-sim-thresh", type=float, default=None)
    parser.add_argument(
        "--l3-confirm", type=float, default=None)
    parser.add_argument(
        "--hit-threshold", type=int, default=None)
    parser.add_argument(
        "--frame-thresh", type=int, default=None)
    parser.add_argument(
        "--log-level", default="INFO",
        help="日志级别（默认 INFO）",
    )
    args = parser.parse_args()

    # 校验输入路径存在
    for path in args.input:
        if not os.path.exists(path):
            logger.error("输入路径不存在：%s", path)
            return 2

    # 默认输出目录：nexus/Fabrica/data/dedup_reports
    out_dir = args.out_dir or os.path.join(
        _FABRICA_ROOT, "data", "dedup_reports"
    )
    filename = args.output or (
        "video_dedup_report_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    )

    temp_root = tempfile.mkdtemp(prefix="video_dedup_")
    try:
        # 单目录直接扫描；多输入/含文件则聚合
        if len(args.input) == 1 and os.path.isdir(args.input[0]):
            input_dir = os.path.abspath(args.input[0])
            recursive = args.recursive
            name_map = {}
            input_desc = input_dir
        else:
            input_dir, name_map = _aggregate(
                args.input, args.recursive, temp_root
            )
            recursive = False  # 聚合目录已平铺
            input_desc = ", ".join(args.input)

        # 组装 cfg：复用 config.yaml 默认值，命令行参数覆盖。
        # 默认使用持久库 DEFAULT_DB_PATH，使 L1 文件哈希缓存跨运行生效
        # （同一文件无需重复计算 MD5）；--db 可指定自定义路径。
        db = args.db or DEFAULT_DB_PATH
        cfg = _merge_config({
            "input_dir": input_dir,
            "recursive": recursive,
            "db_path": db,
        })
        cfg["device"] = args.device
        for key, val in (
            ("l2_threshold", args.l2_threshold),
            ("suspect_threshold", args.suspect_threshold),
            ("l3_sim_thresh", args.l3_sim_thresh),
            ("l3_confirm", args.l3_confirm),
            ("hit_threshold", args.hit_threshold),
            ("frame_thresh", args.frame_thresh),
        ):
            if val is not None:
                cfg[key] = val

        logger.info("开始验重：%s", input_desc)
        report, _pipeline = _run(
            input_dir, recursive, cfg, args.skip_l3
        )
        if report.get("cancelled"):
            logger.warning("验重被取消")
            return 1

        markdown = _build_markdown(report, input_desc, cfg, name_map)
        report_path = _write_report(markdown, out_dir, filename)
        logger.info(
            "验重完成：视频 %d 个，去重组 %d 组，报告 %s",
            report.get("total_videos", 0),
            len(report.get("final_groups", [])),
            report_path,
        )
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())