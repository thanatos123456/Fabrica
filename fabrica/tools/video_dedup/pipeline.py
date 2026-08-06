"""级联调度 Pipeline（T5.4）。

将 L1/L2/L3 各模块编排为端到端验重流程：

    Stage 0 扫描视频 → 注册到数据库
    Stage 1 文件哈希（L1）→ 按哈希分组，每组保留代表视频
    Stage 2 pHash 序列（L2）→ 抽帧 → pHash → FAISS 索引 → 候选对 → 序列对齐打分
    Stage 3 深度特征（L3）→ 对疑似对提取 CLIP 特征 → 深度特征比对
    Stage 4 聚类 + 输出 → 并查集合并 → 展开 L1 组 → 返回报告

支持容错（单视频失败跳过）、取消（cancel_event）与进度上报。

用法：
    from fabrica.tools.video_dedup.pipeline import CascadePipeline

    report = CascadePipeline().run_pipeline(cfg, progress_cb, log_cb, cancel_event)
"""

import json
import os
from typing import Any, Callable, Dict, List, Optional, Sequence

from fabrica.tools.video_dedup.extractors.deepfeat import CLIPExtractor
from fabrica.tools.video_dedup.extractors.filehash import file_hash
from fabrica.tools.video_dedup.extractors.phash import video_phash_sequence
from fabrica.tools.video_dedup.indexing import PHashIndex
from fabrica.tools.video_dedup.matching import (
    DEFAULT_SIM_THRESH,
    LEVEL2_THRESHOLD,
    LEVEL3_THRESHOLD,
    SUSPECT_THRESHOLD,
    build_groups,
    deep_sequence_score,
    expand_groups,
    sequence_score,
)
from fabrica.tools.video_dedup.models import VideoInfo
from fabrica.tools.video_dedup.sampler import sample_frames
from fabrica.tools.video_dedup.storage import VideoStorage


# ============================================================================
# 常量
# ============================================================================

# 支持的视频扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".flv", ".wmv", ".m4v", ".ts",
}


# ============================================================================
# 扫描
# ============================================================================

def scan_videos(root: str, recursive: bool = False) -> List[VideoInfo]:
    """扫描目录下的视频文件。

    Args:
        root: 扫描根目录。
        recursive: 是否递归扫描子目录。

    Returns:
        VideoInfo 列表，id 为文件绝对路径。
    """
    videos: List[VideoInfo] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            if os.path.splitext(fname)[1].lower() in VIDEO_EXTENSIONS:
                path = os.path.join(dirpath, fname)
                size = os.path.getsize(path)
                videos.append(
                    VideoInfo(
                        id=path,
                        path=path,
                        size=size,
                        duration=0.0,
                        width=0,
                        height=0,
                        file_hash="",
                        frame_count=0,
                    )
                )
        if not recursive:
            break
    return videos


# ============================================================================
# CascadePipeline
# ============================================================================

class CascadePipeline:
    """级联验重编排器。

    Args:
        storage: 注入的 VideoStorage；为 None 时在 run_pipeline 内创建。
        index: 注入的 PHashIndex；为 None 时创建。
        extractor: 注入的 CLIP 特征提取器；为 None 时按 is_available 决定。
    """

    def __init__(
        self,
        storage: Optional[VideoStorage] = None,
        index: Optional[PHashIndex] = None,
        extractor: Any = None,
    ) -> None:
        self.storage = storage
        self.index = index
        self.extractor = extractor
        # 帧缓存：video_id -> SampledFrame 列表，供 L3 复用（避免重复解码）
        self._frame_cache: Dict[str, Sequence] = {}

    # ---- 内部辅助 ----

    def _cancelled(self, cancel_event) -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    def _report(self, progress_cb, percent: int, msg: str) -> None:
        if progress_cb is not None:
            progress_cb(percent, msg)

    def _log(self, log_cb, level: str, msg: str) -> None:
        if log_cb is not None:
            log_cb(level, msg)

    # ---- 主流程 ----

    def run_pipeline(
        self,
        cfg: Dict[str, Any],
        progress_cb: Optional[Callable] = None,
        log_cb: Optional[Callable] = None,
        cancel_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """执行五阶段级联验重。

        Args:
            cfg: 配置字典（见方案文档 §配置文件）。
            progress_cb: 进度回调 (percent, message)。
            log_cb: 日志回调 (level, message)。
            cancel_event: 可取消事件（含 is_set 方法）。

        Returns:
            验重报告 dict。
        """
        report: Dict[str, Any] = {
            "cancelled": False,
            "total_videos": 0,
            "l1_groups": [],
            "l2_pairs": [],
            "l3_pairs": [],
            "final_groups": [],
            "errors": [],
        }

        # 资源初始化
        if self.storage is None:
            self.storage = VideoStorage(cfg.get("db_path"))
        if self.index is None:
            # k 为 FAISS 最近邻检索数；T5.7 调参默认 32，避免采样帧数
            # 占满 top-k 导致跨视频真匹配被挤出（原默认 8 会漏检）。
            self.index = PHashIndex(k=cfg.get("k", 32))
        if self.extractor is None:
            self.extractor = (
                CLIPExtractor(device=cfg.get("device", "auto"))
                if CLIPExtractor.is_available() else None
            )

        # 阈值
        l2_threshold = cfg.get("l2_threshold", LEVEL2_THRESHOLD)
        suspect_threshold = cfg.get("suspect_threshold", SUSPECT_THRESHOLD)
        l3_sim_thresh = cfg.get("l3_sim_thresh", DEFAULT_SIM_THRESH)
        l3_confirm = cfg.get("l3_confirm", LEVEL3_THRESHOLD)
        hit_threshold = cfg.get("hit_threshold", 3)
        # T5.7 调参：默认帧汉明命中阈值 8 -> 16
        frame_thresh = cfg.get("frame_thresh", 16)

        # ---- Stage 0 扫描 ----
        if self._cancelled(cancel_event):
            report["cancelled"] = True
            return report
        self._report(progress_cb, 0, "扫描视频文件")
        videos = scan_videos(
            cfg["input_dir"], recursive=cfg.get("recursive", False)
        )
        self.storage.register_videos(videos)
        report["total_videos"] = len(videos)
        self._log(log_cb, "info", f"扫描到 {len(videos)} 个视频")

        # ---- Stage 1 L1 文件哈希 ----
        if self._cancelled(cancel_event):
            report["cancelled"] = True
            return report
        self._report(progress_cb, 15, "L1 文件哈希去重")
        for v in self.storage.videos_without_hash():
            try:
                self.storage.set_hash(v.id, file_hash(v.path))
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"L1 {v.id}: {exc}")
        l1_groups = list(self.storage.group_by_hash().values())
        # 代表 = 非重复成员；每组的代表取首个
        dup_ids: set = set()
        for group in l1_groups:
            dup_ids.update(group[1:])
        all_ids = [v.id for v in videos]
        rep_ids = [vid for vid in all_ids if vid not in dup_ids]
        report["l1_groups"] = [sorted(g) for g in l1_groups]
        self._log(log_cb, "info", f"L1 重建 {len(l1_groups)} 组，代表 {len(rep_ids)} 个")

        # ---- Stage 2 L2 pHash 序列 ----
        if self._cancelled(cancel_event):
            report["cancelled"] = True
            return report
        self._report(progress_cb, 40, "L2 pHash 序列比对")
        seqs: Dict[str, Any] = {}
        for vid in rep_ids:
            path = dict((v.id, v.path) for v in videos).get(vid, vid)
            try:
                frames, _duration = sample_frames(path)
                if not frames:
                    report["errors"].append(f"L2 {vid}: 无法抽帧（损坏或空）")
                    continue
                seq = video_phash_sequence(frames)
                self.storage.save_phash(vid, seq, frames)
                self.index.add(vid, seq)
                self._frame_cache[vid] = frames
                seqs[vid] = seq
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"L2 {vid}: {exc}")

        candidates = self.index.generate_candidates(
            rep_ids,
            hit_threshold=hit_threshold,
            frame_thresh=frame_thresh,
        )
        suspects: List[tuple] = []
        for a, b in candidates:
            if a not in seqs or b not in seqs:
                continue
            score = sequence_score(seqs[a], seqs[b], frame_thresh=frame_thresh)
            if score >= l2_threshold:
                report["l2_pairs"].append([a, b, float(score)])
                self.storage.save_match(a, b, 2, float(score))
            elif score >= suspect_threshold:
                suspects.append((a, b, float(score)))
        self._log(log_cb, "info", f"L2 判重 {len(report['l2_pairs'])} 对，L3 候选 {len(suspects)} 对")

        # ---- Stage 3 L3 深度特征 ----
        if self._cancelled(cancel_event):
            report["cancelled"] = True
            return report
        self._report(progress_cb, 75, "L3 深度特征比对")
        if self.extractor is None:
            self._log(log_cb, "info", "L3 不可用（OpenCLIP 未安装），跳过深度比对")
        else:
            for a, b, _score in suspects:
                try:
                    fa = self.extractor.extract(
                        [f.image for f in self._frame_cache[a]]
                    )
                    fb = self.extractor.extract(
                        [f.image for f in self._frame_cache[b]]
                    )
                    dscore = deep_sequence_score(fa, fb, sim_thresh=l3_sim_thresh)
                    if dscore >= l3_confirm:
                        report["l3_pairs"].append([a, b, float(dscore)])
                        self.storage.save_match(a, b, 3, float(dscore))
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"L3 {a}-{b}: {exc}")
            self._log(
                log_cb, "info",
                f"L3 判重 {len(report['l3_pairs'])} 对",
            )

        # ---- Stage 4 聚类 + 输出 ----
        if self._cancelled(cancel_event):
            report["cancelled"] = True
            return report
        self._report(progress_cb, 90, "聚类合成重复组")
        all_matches: List[tuple] = [
            (a, b) for a, b, _ in report["l2_pairs"]
        ] + [(a, b) for a, b, _ in report["l3_pairs"]]
        final_groups = self._cluster(all_ids, all_matches, l1_groups)
        report["final_groups"] = final_groups

        self._report(progress_cb, 100, "完成")
        self._write_report(report, cfg.get("output"))
        return report

    # ---- 聚类 ----

    def _cluster(
        self,
        all_ids: List[str],
        matches: List[tuple],
        l1_groups: Sequence[Sequence],
    ) -> List[List[str]]:
        """将判重关系合并为重复组并展开 L1 组。

        Args:
            all_ids: 全部视频 id（用于 id<->idx 映射）。
            matches: 判重关系 [(id_a, id_b), ...]。
            l1_groups: L1 重复组（id 列表）。

        Returns:
            展开后的重复组列表（组内 id 升序）。
        """
        id_to_idx = {vid: i for i, vid in enumerate(all_ids)}
        idx_arr = [v for v in all_ids]
        int_matches = []
        for a, b in matches:
            if a in id_to_idx and b in id_to_idx:
                int_matches.append((id_to_idx[a], id_to_idx[b]))
        int_groups = build_groups(len(all_ids), int_matches)
        id_groups = [[idx_arr[i] for i in group] for group in int_groups]
        return expand_groups(l1_groups, id_groups)

    # ---- 输出 ----

    @staticmethod
    def _write_report(report: Dict[str, Any], output: Optional[str]) -> None:
        """将报告写入 JSON 文件（可选）。"""
        if not output:
            return
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)