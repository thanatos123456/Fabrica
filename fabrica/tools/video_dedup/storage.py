"""VideoStorage 基础存储层（T4.7）。

使用 SQLite 管理视频元数据、pHash 指纹缓存与判重结果的持久化。
提供批量注册、哈希分组、pHash 存取、判重结果落库等基础接口，
以及 SCHEMA_VERSION 常量与 migrate() 数据库迁移。

表结构：
- videos      视频元信息（含文件哈希与各判重层级完成标记）
- phash_frames 每帧 pHash 指纹缓存
- matches     判重结果（视频对 + 层级 + 相似度）

用法：
    from fabrica.tools.video_dedup.storage import VideoStorage

    st = VideoStorage(db_path)
    st.register_videos([video_info, ...])
    groups = st.group_by_hash()
"""

import os
import sys
import sqlite3
import struct
import threading
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from fabrica.tools.video_dedup.models import VideoInfo
from fabrica.tools.video_dedup.sampler import SampledFrame


# ============================================================================
# 路径与常量
# ============================================================================

# 本文件位于 fabrica/tools/video_dedup/storage.py，
# 上溯 4 级到达项目根目录 nexus/Fabrica/
# PyInstaller 打包后 __file__ 指向 _MEIPASS 临时目录，改用 sys.executable 定位
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _FABRICA_DIR = os.path.dirname(sys.executable)
else:
    _CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    _TOOLS_DIR = os.path.dirname(_CURRENT_DIR)
    _FABRICA_DIR = os.path.dirname(os.path.dirname(_TOOLS_DIR))
DEFAULT_DB_PATH = os.path.join(
    _FABRICA_DIR, "data", "video_dedup", "dedup.db"
)
# 深度特征 .npy 文件目录（T5.5）
DEFAULT_FEATURE_DIR = os.path.join(
    _FABRICA_DIR, "data", "video_dedup_features"
)
# 关键帧图像目录（T6.3）
DEFAULT_KEYFRAME_DIR = os.path.join(_FABRICA_DIR, "data", "keyframes")

# 深度特征维度（与 CLIPExtractor.extract 输出一致）
DEEP_FEATURE_DIM = 512

# 数据库结构版本号
SCHEMA_VERSION = 1

# uint64 指纹的 64bit 掩码，用于有符号往返还原
_UINT64_MASK = 0xFFFFFFFFFFFFFFFF
_SIGNED_MIN = -(1 << 63)


# 建表脚本
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    duration    REAL NOT NULL DEFAULT 0.0,
    width       INTEGER NOT NULL DEFAULT 0,
    height      INTEGER NOT NULL DEFAULT 0,
    file_hash   TEXT NOT NULL DEFAULT '',
    phash_done  INTEGER NOT NULL DEFAULT 0,
    deep_done   INTEGER NOT NULL DEFAULT 0,
    frame_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS phash_frames (
    video_id   TEXT NOT NULL,
    frame_idx  INTEGER NOT NULL,
    ts         REAL NOT NULL DEFAULT 0.0,
    phash      INTEGER NOT NULL,
    PRIMARY KEY (video_id, frame_idx)
);

CREATE TABLE IF NOT EXISTS matches (
    a_id   TEXT NOT NULL,
    b_id   TEXT NOT NULL,
    level  INTEGER NOT NULL DEFAULT 0,
    score  REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (a_id, b_id)
);
"""


# ============================================================================
# 数据库迁移
# ============================================================================

def migrate(conn: sqlite3.Connection) -> None:
    """执行数据库迁移。

    通过 PRAGMA user_version 跟踪结构版本：低于 SCHEMA_VERSION
    时执行建表脚本并递增版本号。

    Args:
        conn: 已连接的 SQLite 连接。
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()


# ============================================================================
# uint64 <-> int64 转换（SQLite INTEGER 为有符号 64bit）
# ============================================================================

def _to_signed(value: int) -> int:
    """将 uint64 整数转为有符号 int64 以便 SQLite 存储。"""
    return struct.unpack(
        "q", struct.pack("Q", value & _UINT64_MASK)
    )[0]


def _to_unsigned(value: int) -> int:
    """将 SQLite 读出的有符号 int64 还原为 uint64。"""
    return value & _UINT64_MASK


# ============================================================================
# VideoStorage 类
# ============================================================================

class VideoStorage:
    """SQLite 基础存储层。

    管理视频元数据、pHash 指纹缓存与判重结果的持久化。

    Args:
        db_path: 数据库文件路径，默认 data/video_dedup/dedup.db。
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        feature_dir: Optional[str] = None,
    ) -> None:
        """初始化存储层。

        Args:
            db_path: 数据库文件路径，默认 data/video_dedup/dedup.db。
            feature_dir: 深度特征 .npy 文件目录，默认
                data/video_dedup_features。
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.feature_dir = feature_dir or DEFAULT_FEATURE_DIR
        os.makedirs(self.feature_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            migrate(self._conn)

    def close(self) -> None:
        """关闭数据库连接。"""
        with self._lock:
            self._conn.close()

    # ---- 视频元信息 ----

    def register_videos(self, video_list: Sequence[VideoInfo]) -> None:
        """批量注册视频元信息（upsert）。

        以 id 为键做 upsert：仅更新元信息字段（path/size/duration/
        width/height/frame_count），保留已计算的 file_hash / phash_done /
        deep_done。这样扫描得到的 file_hash='' 不会覆盖掉已缓存哈希，
        使 L1 哈希可跨运行复用、避免重复计算。

        Args:
            video_list: VideoInfo 列表。
        """
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO videos
                    (id, path, size, duration, width, height,
                     file_hash, phash_done, deep_done, frame_count)
                VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                    path = excluded.path,
                    size = excluded.size,
                    duration = excluded.duration,
                    width = excluded.width,
                    height = excluded.height,
                    frame_count = excluded.frame_count
                """,
                [
                    (v.id, v.path, v.size, v.duration, v.width, v.height,
                     v.frame_count)
                    for v in video_list
                ],
            )
            self._conn.commit()

    def videos_without_hash(self) -> List[VideoInfo]:
        """获取未计算文件哈希的视频。

        Returns:
            file_hash 为空的 VideoInfo 列表，按 id 排序。
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM videos WHERE file_hash = ''
                ORDER BY id
                """
            ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def get_video(self, video_id: str) -> Optional[VideoInfo]:
        """按 id 查询单个视频元信息。

        Args:
            video_id: 视频标识。

        Returns:
            VideoInfo 或 None（不存在时）。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
        return self._row_to_video(row) if row else None

    def get_match(
        self, a_id: str, b_id: str,
    ) -> Optional[Dict[str, Any]]:
        """查询两个视频间的判重结果（双向匹配）。

        matches 表以 (a_id, b_id) 为主键，候选对方向可能不一致，
        因此同时匹配 (a_id, b_id) 和 (b_id, a_id)。

        Args:
            a_id: 视频 A 标识。
            b_id: 视频 B 标识。

        Returns:
            {"level": int, "score": float} 或 None（无记录时）。
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT level, score FROM matches
                WHERE (a_id=? AND b_id=?) OR (a_id=? AND b_id=?)
                """,
                (a_id, b_id, b_id, a_id),
            ).fetchone()
        if row is None:
            return None
        return {"level": row["level"], "score": row["score"]}

    def set_hash(self, video_id: str, hash_val: str) -> None:
        """设置视频的文件哈希值。

        Args:
            video_id: 视频标识。
            hash_val: 文件 MD5 哈希。
        """
        with self._lock:
            self._conn.execute(
                "UPDATE videos SET file_hash = ? WHERE id = ?",
                (hash_val, video_id),
            )
            self._conn.commit()

    def group_by_hash(self) -> Dict[str, List[str]]:
        """按文件哈希分组（仅返回存在重复的分组）。

        Returns:
            字典 {file_hash: [video_id, ...]}，每个分组至少 2 个视频。
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT file_hash, GROUP_CONCAT(id, ',') AS ids
                FROM videos
                WHERE file_hash != ''
                GROUP BY file_hash
                HAVING COUNT(id) > 1
                """
            ).fetchall()
        return {
            r["file_hash"]: r["ids"].split(",")
            for r in rows if r["ids"]
        }

    # ---- pHash 指纹缓存 ----

    def save_phash(
        self,
        video_id: str,
        seq: np.ndarray,
        frames: Sequence[SampledFrame],
    ) -> None:
        """保存视频的 pHash 序列。

        以 (video_id, frame_idx) 为键覆盖写入，并更新 videos 表
        的 frame_count 与 phash_done 标记。

        Args:
            video_id: 视频标识。
            seq: pHash 序列（np.ndarray [n] uint64）。
            frames: SampledFrame 列表，提供 idx/ts。
        """
        values = [
            (video_id, f.idx, float(f.ts), _to_signed(int(seq[f.idx])))
            for f in frames
        ]
        with self._lock:
            self._conn.execute(
                "DELETE FROM phash_frames WHERE video_id = ?",
                (video_id,),
            )
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO phash_frames
                    (video_id, frame_idx, ts, phash)
                VALUES (?, ?, ?, ?)
                """,
                values,
            )
            self._conn.execute(
                """
                UPDATE videos SET frame_count = ?, phash_done = 1
                WHERE id = ?
                """,
                (len(seq), video_id),
            )
            self._conn.commit()

    def load_phash(self, video_id: str) -> np.ndarray:
        """加载视频的 pHash 序列。

        Args:
            video_id: 视频标识。

        Returns:
            np.ndarray shape [n] dtype uint64，按 frame_idx 升序。
            无记录时返回空数组。
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT phash FROM phash_frames
                WHERE video_id = ? ORDER BY frame_idx
                """,
                (video_id,),
            ).fetchall()
        return np.array(
            [_to_unsigned(r["phash"]) for r in rows], dtype=np.uint64
        )

    # ---- 深度特征 .npy 存储 ----

    @staticmethod
    def _safe_feature_name(video_id: str) -> str:
        """将 video_id 转为安全文件名（{hash}.npy）。

        使用 MD5 哈希生成固定长度文件名，避免路径中的非法字符
        （特别是 Windows 盘符冒号 ``:`` 导致 os.path.join 盘符切换，
        使文件创建在错误盘符位置）。

        Args:
            video_id: 视频标识（文件完整路径）。

        Returns:
            形如 {md5hex}.npy 的文件名，固定 36 字符。
        """
        import hashlib
        h = hashlib.md5(video_id.encode("utf-8")).hexdigest()
        return f"{h}.npy"

    def save_deep(self, video_id: str, feats: np.ndarray) -> None:
        """保存视频的深度特征（.npy 文件）。

        Args:
            video_id: 视频标识。
            feats: 深度特征数组（[n, FEATURE_DIM]）。
        """
        arr = np.asarray(feats).astype(np.float32)
        path = os.path.join(
            self.feature_dir, self._safe_feature_name(video_id)
        )
        np.save(path, arr)
        with self._lock:
            self._conn.execute(
                "UPDATE videos SET deep_done = 1 WHERE id = ?",
                (video_id,),
            )
            self._conn.commit()

    def load_deep(self, video_id: str) -> np.ndarray:
        """加载视频的深度特征。

        Args:
            video_id: 视频标识。

        Returns:
            np.ndarray shape [n, DEEP_FEATURE_DIM] float32。
            特征文件不存在时返回空数组 shape (0, DEEP_FEATURE_DIM)。
        """
        path = os.path.join(
            self.feature_dir, self._safe_feature_name(video_id)
        )
        if not os.path.exists(path):
            return np.zeros((0, DEEP_FEATURE_DIM), dtype=np.float32)
        return np.load(path).astype(np.float32)

    # ---- 判重结果 ----

    def save_match(
        self, a: str, b: str, level: int, score: float
    ) -> None:
        """保存判重结果。

        Args:
            a: 视频 A 标识。
            b: 视频 B 标识。
            level: 判重层级（1=文件哈希，2=pHash 序列，3=深度特征）。
            score: 相似度得分（0~1）。
        """
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO matches (a_id, b_id, level, score)
                VALUES (?, ?, ?, ?)
                """,
                (a, b, level, float(score)),
            )
            self._conn.commit()

    # ---- 内部辅助 ----

    @staticmethod
    def _row_to_video(row: sqlite3.Row) -> VideoInfo:
        """将数据库行转换为 VideoInfo。"""
        return VideoInfo(
            id=row["id"],
            path=row["path"],
            size=row["size"],
            duration=row["duration"],
            width=row["width"],
            height=row["height"],
            file_hash=row["file_hash"],
            frame_count=row["frame_count"],
        )