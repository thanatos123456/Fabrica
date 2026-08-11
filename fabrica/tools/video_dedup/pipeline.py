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
import hashlib
from typing import Any, Callable, Dict, List, Optional, Sequence

from fabrica.tools.video_dedup.extractors.deepfeat import CLIPExtractor, FEATURE_DIM
from fabrica.tools.video_dedup.extractors.filehash import file_hash
from fabrica.tools.video_dedup.extractors.phash import video_phash_sequence
from fabrica.tools.video_dedup.indexing import DeepIndex, PHashIndex
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
from fabrica.tools.video_dedup.sampler import FRAME_INTERVAL, sample_frames
from fabrica.tools.video_dedup.storage import VideoStorage, DEFAULT_KEYFRAME_DIR


# ============================================================================
# 常量
# ============================================================================

# 支持的视频扩展名
VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".flv", ".wmv", ".m4v", ".ts",
}

# 阶段名称（用于进度上报）
STAGE_SCAN = "扫描视频文件"
STAGE_L1 = "L1 文件哈希去重"
STAGE_L2 = "L2 pHash 序列比对"
STAGE_L3 = "L3 深度特征比对"
STAGE_CLUSTER = "聚类合成重复组"


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

    def _report(
        self, progress_cb, percent: int, msg: str, stage: str = "",
    ) -> None:
        if progress_cb is not None:
            progress_cb(percent, msg, stage)

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
            "keyframes": {},
            "matched_frames": [],
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
        self._report(progress_cb, 0, "扫描视频文件", STAGE_SCAN)
        recursive = cfg.get("recursive", False)
        self._log(
            log_cb, "info",
            f"扫描根目录 {cfg['input_dir']}（recursive={recursive}）",
        )
        videos = scan_videos(cfg["input_dir"], recursive=recursive)
        self.storage.register_videos(videos)
        report["total_videos"] = len(videos)
        self._log(log_cb, "info", f"扫描到 {len(videos)} 个视频")

        # ---- Stage 1 L1 文件哈希 ----
        if self._cancelled(cancel_event):
            report["cancelled"] = True
            return report
        self._report(progress_cb, 0, "L1 文件哈希去重", STAGE_L1)
        hash_videos = list(self.storage.videos_without_hash())
        hash_n = len(hash_videos)
        for i, v in enumerate(hash_videos):
            self._report(
                progress_cb,
                round((i + 1) / hash_n * 100),
                f"L1 文件哈希去重 [{i + 1}/{hash_n}]",
                STAGE_L1,
            )
            self._log(log_cb, "info", f"L1 哈希 [{i + 1}/{hash_n}] {v.path}")
            try:
                self.storage.set_hash(v.id, file_hash(v.path))
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"L1 {v.id}: {exc}")
        if hash_n == 0:
            self._report(progress_cb, 100, "L1 文件哈希去重", STAGE_L1)
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
        self._report(progress_cb, 0, "L2 pHash 序列比对", STAGE_L2)
        seqs: Dict[str, Any] = {}
        rep_n = len(rep_ids)
        for i, vid in enumerate(rep_ids):
            self._report(
                progress_cb,
                round((i + 1) / rep_n * 100),
                f"L2 pHash 序列比对 [{i + 1}/{rep_n}]",
                STAGE_L2,
            )
            path = dict((v.id, v.path) for v in videos).get(vid, vid)
            try:
                frames, duration = sample_frames(
                    path,
                    min_frames=cfg.get("sample_min_frames", 16),
                    max_frames=cfg.get("sample_max_frames", 100),
                    target_fps=cfg.get("sample_target_fps", 1.0),
                    frame_interval=cfg.get("sample_frame_interval", FRAME_INTERVAL),
                    resize=cfg.get("sample_resize", (224, 224)),
                )
                if not frames:
                    report["errors"].append(f"L2 {vid}: 无法抽帧（损坏或空）")
                    continue
                self._log(
                    log_cb, "info",
                    f"L2 抽帧 [{i + 1}/{rep_n}] {path}，"
                    f"采样 {len(frames)} 帧，时长 {duration} 秒",
                )
                seq = video_phash_sequence(frames)
                self.storage.save_phash(vid, seq, frames)
                self.index.add(vid, seq)
                self._frame_cache[vid] = frames
                seqs[vid] = seq
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"L2 {vid}: {exc}")
        if rep_n == 0:
            self._report(progress_cb, 100, "L2 pHash 序列比对", STAGE_L2)

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
        self._report(progress_cb, 0, "L3 深度特征比对", STAGE_L3)
        if self.extractor is None:
            self._log(log_cb, "info", "L3 不可用（OpenCLIP 未安装），跳过深度比对")
            self._report(progress_cb, 100, "L3 深度特征比对（跳过）", STAGE_L3)
        else:
            # 收集疑似对涉及的所有视频，统一提取特征并建立深度特征索引
            suspect_vids: List[str] = sorted(
                {vid for pair in suspects for vid in pair[:2]}
            )
            deep_index = DeepIndex(
                dim=FEATURE_DIM,
                k=cfg.get("l3_search_k", 32),
            )
            suspect_n = len(suspect_vids)
            for i, vid in enumerate(suspect_vids):
                self._report(
                    progress_cb,
                    round((i + 1) / suspect_n * 100),
                    f"L3 深度特征比对 [{i + 1}/{suspect_n}]",
                    STAGE_L3,
                )
                try:
                    frames = self._frame_cache.get(vid)
                    if not frames:
                        report["errors"].append(f"L3 {vid}: 无缓存帧，跳过")
                        continue
                    feats = self.extractor.extract(
                        [f.image for f in frames]
                    )
                    self._log(
                        log_cb, "info",
                        f"L3 提取 [{i + 1}/{suspect_n}] {vid}，"
                        f"{len(feats)} 帧",
                    )
                    self.storage.save_deep(vid, feats)
                    deep_index.add(vid, feats)
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"L3 {vid}: {exc}")

            # 用深度索引检索近邻生成候选对，再逐对深度序列打分
            deep_candidates = deep_index.generate_candidates(
                suspect_vids,
                hit_threshold=cfg.get("l3_hit_threshold", 1),
                k=cfg.get("l3_search_k", 32),
                sim_thresh=l3_sim_thresh,
            )
            for a, b in deep_candidates:
                try:
                    # 复用索引缓存的特征序列，避免重复提取
                    fa = deep_index._videos.get(a)
                    fb = deep_index._videos.get(b)
                    if fa is None or fb is None:
                        continue
                    dscore = deep_sequence_score(fa, fb, sim_thresh=l3_sim_thresh)
                    if dscore >= l3_confirm:
                        report["l3_pairs"].append([a, b, float(dscore)])
                        self.storage.save_match(a, b, 3, float(dscore))
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"L3 {a}-{b}: {exc}")
            if suspect_n == 0:
                self._report(progress_cb, 100, "L3 深度特征比对", STAGE_L3)
            self._log(
                log_cb, "info",
                f"L3 判重 {len(report['l3_pairs'])} 对",
            )

        # ---- Stage 4 聚类 + 输出 ----
        if self._cancelled(cancel_event):
            report["cancelled"] = True
            return report
        # L3 可用时聚类从 L3 结束值起步，否则从 L2 结束值起步
        self._report(progress_cb, 0, "聚类合成重复组", STAGE_CLUSTER)
        all_matches: List[tuple] = [
            (a, b) for a, b, _ in report["l2_pairs"]
        ] + [(a, b) for a, b, _ in report["l3_pairs"]]
        # L3 不可用时，将 L2 疑似对（score ≥ 疑似阈值）也纳入聚类，
        # 避免跳过 L3 时因 L2 保守判定而漏判（如分辨率差异导致的疑似）
        if self.extractor is None:
            all_matches += [(a, b) for a, b, _ in suspects]
        final_groups = self._cluster(all_ids, all_matches, l1_groups)
        report["final_groups"] = self._enrich_groups(final_groups)
        # T6.3: 保存关键帧 + 计算帧级匹配
        if report["final_groups"]:
            report["keyframes"] = self._save_keyframes(
                report["final_groups"], cfg, report["errors"],
            )
            report["matched_frames"] = self._compute_matched_frames(
                report["final_groups"], frame_thresh,
            )
        self._log(
            log_cb, "info",
            f"聚类完成，最终去重组 {len(final_groups)} 组",
        )

        self._report(progress_cb, 100, "完成", STAGE_CLUSTER)
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

    def _enrich_groups(
        self, raw_groups: List[List[str]],
    ) -> List[Dict[str, Any]]:
        """将原始 ID 分组展开为含元信息的结构化分组。

        Args:
            raw_groups: 纯 video ID 列表的分组。

        Returns:
            [{"level": int, "videos": [{"id", "path", "size",
             "duration", "width", "height"}, ...]}, ...]
        """
        enriched: List[Dict[str, Any]] = []
        for group_ids in raw_groups:
            videos_info = []
            for vid in group_ids:
                v = self.storage.get_video(vid)
                if v is None:
                    continue
                videos_info.append({
                    "id": v.id,
                    "path": v.path,
                    "size": v.size,
                    "duration": v.duration,
                    "width": v.width,
                    "height": v.height,
                })
            if len(videos_info) < 2:
                continue
            # 确定组内最高判重级别
            max_level = 1
            for i in range(len(videos_info)):
                for j in range(i + 1, len(videos_info)):
                    match = self.storage.get_match(
                        videos_info[i]["id"], videos_info[j]["id"],
                    )
                    if match and match["level"] > max_level:
                        max_level = match["level"]
            enriched.append({
                "level": max_level,
                "videos": videos_info,
            })
        return enriched

    # ---- 关键帧保存（T6.3）----

    @staticmethod
    def _safe_dir_name(video_id: str) -> str:
        """将 video_id 转为安全目录名（MD5 哈希）。"""
        return hashlib.md5(video_id.encode("utf-8")).hexdigest()

    def _save_keyframes(
        self, final_groups: List[Dict[str, Any]], cfg: Dict[str, Any],
        errors: List[str],
    ) -> Dict[str, Dict[int, str]]:
        """对重复组视频重新抽帧并保存 JPEG 关键帧图像。

        使用与 L2 相同的采样参数确保帧索引一致。从所有采样帧中
        均匀选取最多 5 帧保存。非重复组视频不保存关键帧。
        单个视频保存失败时跳过并记录错误。

        Args:
            final_groups: 结构化重复组列表。
            cfg: 配置字典（读取采样参数）。
            errors: 错误收集列表（失败时追加）。

        Returns:
            {video_id: {frame_idx: "/keyframes/{hash}/frame_{idx:04d}.jpg"}}
        """
        MAX_KEYFRAMES = 5
        keyframes: Dict[str, Dict[int, str]] = {}
        for group in final_groups:
            for v in group.get("videos", []):
                vid = v["id"]
                path = v["path"]
                try:
                    frames, _ = sample_frames(
                        path,
                        min_frames=cfg.get("sample_min_frames", 16),
                        max_frames=cfg.get("sample_max_frames", 100),
                        target_fps=cfg.get("sample_target_fps", 1.0),
                        frame_interval=cfg.get(
                            "sample_frame_interval", FRAME_INTERVAL,
                        ),
                        resize=cfg.get("sample_resize", (224, 224)),
                    )
                    if not frames:
                        continue
                    # 均匀选取最多 MAX_KEYFRAMES 帧（保留原始帧索引）
                    if len(frames) > MAX_KEYFRAMES:
                        step = len(frames) / MAX_KEYFRAMES
                        selected = [
                            frames[int(i * step)]
                            for i in range(MAX_KEYFRAMES)
                        ]
                    else:
                        selected = frames
                    dir_name = self._safe_dir_name(vid)
                    out_dir = os.path.join(DEFAULT_KEYFRAME_DIR, dir_name)
                    os.makedirs(out_dir, exist_ok=True)
                    url_map: Dict[int, str] = {}
                    for f in selected:
                        fname = f"frame_{f.idx:04d}.jpg"
                        f.image.save(
                            os.path.join(out_dir, fname),
                            "JPEG",
                            quality=85,
                        )
                        url_map[f.idx] = f"/keyframes/{dir_name}/{fname}"
                    keyframes[vid] = url_map
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"keyframe {vid}: {exc}")
        return keyframes

    def _compute_matched_frames(
        self, final_groups: List[Dict[str, Any]], frame_thresh: int,
    ) -> List[Dict[str, Any]]:
        """计算重复组内视频间的帧级匹配信息。

        对每组内视频两两计算，利用 storage.load_phash() 加载已存储
        的 pHash 序列，用单调贪心匹配找出 Hamming 距离 ≤ frame_thresh
        的帧对。

        Args:
            final_groups: 结构化重复组列表。
            frame_thresh: 帧汉明距离命中阈值。

        Returns:
            [{"a_id", "a_idx", "b_id", "b_idx"}, ...]
        """
        import numpy as np

        matched: List[Dict[str, Any]] = []
        for group in final_groups:
            videos = group.get("videos", [])
            for i in range(len(videos)):
                for j in range(i + 1, len(videos)):
                    a, b = videos[i], videos[j]
                    seq_a = self.storage.load_phash(a["id"])
                    seq_b = self.storage.load_phash(b["id"])
                    arr_a = np.asarray(seq_a).astype(np.uint64)
                    arr_b = np.asarray(seq_b).astype(np.uint64)
                    if arr_a.size == 0 or arr_b.size == 0:
                        continue
                    # 以短序列为基准
                    if arr_a.size > arr_b.size:
                        short, long_ = arr_b, arr_a
                        swapped = True
                    else:
                        short, long_ = arr_a, arr_b
                        swapped = False
                    dists = np.bitwise_count(
                        short[:, None] ^ long_[None, :]
                    )
                    n_short, n_long = dists.shape
                    long_ptr = 0
                    for si in range(n_short):
                        for li in range(long_ptr, n_long):
                            if int(dists[si, li]) <= frame_thresh:
                                if swapped:
                                    a_idx, b_idx = li, si
                                else:
                                    a_idx, b_idx = si, li
                                matched.append({
                                    "a_id": a["id"], "a_idx": a_idx,
                                    "b_id": b["id"], "b_idx": b_idx,
                                })
                                long_ptr = li + 1
                                break
        return matched

    # ---- 输出 ----

    @staticmethod
    def _write_report(report: Dict[str, Any], output: Optional[str]) -> None:
        """将报告写入 JSON 文件（可选）。"""
        if not output:
            return
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)