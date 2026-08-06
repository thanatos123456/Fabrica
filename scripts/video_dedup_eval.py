#!/usr/bin/env python3
"""视频验重阈值评估脚本（T5.7）。

基于 video_factory 构建带标注的测试集，运行完整 L1+L2+L3 级联验重，
计算并输出 Precision / Recall / F1，用于阈值调参。

测试集结构：
- --n-groups 组真重复组，每组 1 个原始视频 + 若干派生视频
  （派生轮流施加 resize / watermark / crop / transcode 变换）
- --n-distinct 个真不同视频（content 各异）

gold standard 由真重复组展开为「视频对」集合；预测结果由
report.final_groups 展开为「预测对」集合，按文档 §7.3 的 evaluate 逻辑打分。

用法：
    python3 scripts/video_dedup_eval.py --device cpu \
        --l2-threshold 0.90 --l3-confirm 0.85 --json

注：本脚本为独立调参工具，不纳入 pytest 收集。
"""

import argparse
import json
import os
import sys
import tempfile
import types

# ============================================================================
# 路径注入：构造 aurora 虚拟包 + 注入 Fabrica 项目根目录
# （复用 tests/conftest.py 的注入逻辑，使脚本可独立运行）
# ============================================================================
_FABRICA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NEXUS_ROOT = os.path.dirname(_FABRICA_ROOT)
_OMNIPIVOT_ROOT = os.path.dirname(_NEXUS_ROOT)
_AURORA_PATH = os.path.join(_OMNIPIVOT_ROOT, "aurora", "python")
_AURORA_ROOT = os.path.join(_OMNIPIVOT_ROOT, "aurora")

if _AURORA_PATH not in sys.path:
    sys.path.insert(0, _AURORA_PATH)
if _FABRICA_ROOT not in sys.path:
    sys.path.insert(0, _FABRICA_ROOT)

if "aurora" not in sys.modules:
    _aurora_pkg = types.ModuleType("aurora")
    _aurora_pkg.__path__ = [_AURORA_ROOT]
    sys.modules["aurora"] = _aurora_pkg
if "aurora.python" not in sys.modules:
    _aurora_python_pkg = types.ModuleType("aurora.python")
    _aurora_python_pkg.__path__ = [_AURORA_PATH]
    sys.modules["aurora.python"] = _aurora_python_pkg

from tests.fixtures.video_factory import (  # noqa: E402
    create_derived_video,
    create_test_video,
)
from fabrica.tools.video_dedup.extractors.deepfeat import (
    CLIPExtractor,  # noqa: E402
)
from fabrica.tools.video_dedup.pipeline import CascadePipeline  # noqa: E402


# ============================================================================
# 派生变换轮转
# ============================================================================

def _derived_kwargs(index: int) -> dict:
    """按顺序轮转派生变换，返回 create_derived_video 的 kwargs。"""
    transforms = [
        {"resize": True},
        {"watermark": True},
        {"crop": True},
        {"transcode": True},
    ]
    return transforms[index % len(transforms)]


# ============================================================================
# 测试集构建
# ============================================================================

def build_dataset(
    video_dir: str,
    n_groups: int,
    n_derived: int,
    n_distinct: int,
    resolution: tuple = (448, 336),
) -> tuple:
    """构建带标注测试集。

    Args:
        video_dir: 视频输出目录。
        n_groups: 真重复组数量。
        n_derived: 每组派生视频数量。
        n_distinct: 真不同视频数量。
        resolution: 视频分辨率 (width, height)。

    Returns:
        (video_paths, gold_groups)：
        - video_paths: 全部视频绝对路径列表。
        - gold_groups: 真重复组（组内为绝对路径的 basename），
          仅含 n_groups 个重复组，不含真不同视频。
    """
    gold_groups = []
    video_paths = []

    for g in range(n_groups):
        base = create_test_video(
            os.path.join(video_dir, f"g{g}_base.mp4"),
            content=f"group_{g}",
            resolution=resolution,
        )
        group = [os.path.basename(base)]
        for d in range(n_derived):
            derived = create_derived_video(
                base,
                os.path.join(video_dir, f"g{g}_d{d}.mp4"),
                **_derived_kwargs(d),
            )
            group.append(os.path.basename(derived))
        video_paths.append(base)
        video_paths.extend(group[1:])
        gold_groups.append(sorted(group))

    for i in range(n_distinct):
        video_paths.append(
            create_test_video(
                os.path.join(video_dir, f"dist{i}.mp4"),
                content=f"distinct_{i}",
                resolution=resolution,
            )
        )
    return video_paths, gold_groups


# ============================================================================
# 评估
# ============================================================================

def _pairs_from_groups(groups) -> set:
    """将分组展开为「有序视频对」集合。"""
    pairs = set()
    for group in groups:
        ids = sorted(group)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.add((ids[i], ids[j]))
    return pairs


def evaluate(gold_groups, pred_groups) -> dict:
    """按文档 §7.3 逻辑计算 Precision / Recall / F1。"""
    gold_pairs = _pairs_from_groups(gold_groups)
    pred_pairs = _pairs_from_groups(pred_groups)

    tp = len(pred_pairs & gold_pairs)
    fp = len(pred_pairs - gold_pairs)
    fn = len(gold_pairs - pred_pairs)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0 else 0.0
    )
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _pred_groups_from_report(report) -> list:
    """从 pipeline 报告提取预测分组（转 basename）。"""
    return [
        sorted(os.path.basename(vid) for vid in group)
        for group in report["final_groups"]
    ]


# ============================================================================
# 主流程
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="视频验重阈值评估")
    parser.add_argument("--n-groups", type=int, default=8,
                        help="真重复组数量（默认 8）")
    parser.add_argument("--n-derived", type=int, default=3,
                        help="每组派生视频数量（默认 3）")
    parser.add_argument("--n-distinct", type=int, default=16,
                        help="真不同视频数量（默认 16）")
    parser.add_argument("--resolution", type=str, default="448x336",
                        help="视频分辨率 WxH（默认 448x336）")
    parser.add_argument("--device", default="auto",
                        help="计算设备（auto/cpu/cuda，默认 auto）")
    parser.add_argument("--skip-l3", action="store_true",
                        help="跳过 L3 深度特征（仅跑 L1+L2）")
    parser.add_argument("--l2-threshold", type=float, default=None)
    parser.add_argument("--suspect-threshold", type=float, default=None)
    parser.add_argument("--l3-sim-thresh", type=float, default=None)
    parser.add_argument("--l3-confirm", type=float, default=None)
    parser.add_argument("--hit-threshold", type=int, default=None)
    parser.add_argument("--frame-thresh", type=int, default=None)
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 输出评估结果")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        video_dir = os.path.join(tmp, "videos")
        os.makedirs(video_dir)
        db_path = os.path.join(tmp, "dedup.db")
        w, h = args.resolution.lower().split("x")
        resolution = (int(w), int(h))

        video_paths, gold_groups = build_dataset(
            video_dir, args.n_groups, args.n_derived, args.n_distinct,
            resolution=resolution,
        )

        cfg = {
            "input_dir": video_dir,
            "output": None,
            "recursive": False,
            "device": args.device,
            "db_path": db_path,
        }
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

        if args.skip_l3:
            # pipeline 内部会按 CLIPExtractor.is_available() 决定是否启用 L3，
            # 用 mock 将其临时置为不可用以走 L1+L2 降级路径。
            from unittest import mock
            with mock.patch.object(
                CLIPExtractor, "is_available", return_value=False
            ):
                report = CascadePipeline().run_pipeline(cfg)
        else:
            report = CascadePipeline().run_pipeline(cfg)
        pred_groups = _pred_groups_from_report(report)
        metrics = evaluate(gold_groups, pred_groups)

        # 定位 FP 对
        gold_pairs = _pairs_from_groups(gold_groups)
        pred_pairs = _pairs_from_groups(pred_groups)
        fp_pairs = pred_pairs - gold_pairs
        if fp_pairs:
            print("FP 对:")
            for a, b in sorted(fp_pairs):
                print(f"  {a} vs {b}")

        result = {
            "dataset": {
                "n_groups": args.n_groups,
                "n_derived": args.n_derived,
                "n_distinct": args.n_distinct,
                "n_videos": len(video_paths),
            },
            "thresholds": {
                "l2_threshold": cfg.get("l2_threshold"),
                "suspect_threshold": cfg.get("suspect_threshold"),
                "l3_sim_thresh": cfg.get("l3_sim_thresh"),
                "l3_confirm": cfg.get("l3_confirm"),
                "hit_threshold": cfg.get("hit_threshold"),
                "frame_thresh": cfg.get("frame_thresh"),
            },
            "metrics": metrics,
            "l3_used": CLIPExtractor.is_available() and not args.skip_l3,
        }

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"视频总数: {result['dataset']['n_videos']}")
            print(f"L2 判重 {len(report['l2_pairs'])} 对, "
                  f"L3 判重 {len(report['l3_pairs'])} 对")
            print(f"预测重复组: {len(pred_groups)}, "
                  f"真实重复组: {len(gold_groups)}")
            print(f"Precision = {metrics['precision']:.4f} | "
                  f"Recall = {metrics['recall']:.4f} | "
                  f"F1 = {metrics['f1']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())