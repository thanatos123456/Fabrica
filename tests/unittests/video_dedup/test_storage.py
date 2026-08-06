"""存储层测试。

测试目标：fabrica/tools/video_dedup/storage.py
覆盖：VideoStorage 各接口、SCHEMA_VERSION、migrate、uint64 往返
"""

import os
import sqlite3
import tempfile
import unittest

import numpy as np

from tests.unittests.video_dedup.fixtures import sampled_frames

from fabrica.tools.video_dedup.models import VideoInfo
from fabrica.tools.video_dedup.storage import (
    SCHEMA_VERSION,
    VideoStorage,
)


class TestVideoStorage(unittest.TestCase):
    """VideoStorage 存储层测试集。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.storage = VideoStorage(self.db_path)

    def tearDown(self):
        self.storage.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _register_three(self):
        self.storage.register_videos(
            [
                VideoInfo(id="v1", path="/a.mp4", size=100, file_hash=""),
                VideoInfo(id="v2", path="/b.mp4", size=200, file_hash=""),
                VideoInfo(id="v3", path="/c.mp4", size=300, file_hash=""),
            ]
        )

    # ---- 迁移与版本 ----

    def test_schema_version_constant(self):
        """SCHEMA_VERSION 应为 1。"""
        self.assertEqual(SCHEMA_VERSION, 1)

    def test_migrate_creates_tables(self):
        """连接后应创建三张表并设置 user_version。"""
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("videos", tables)
            self.assertIn("phash_frames", tables)
            self.assertIn("matches", tables)
            version = conn.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
        finally:
            conn.close()

    # ---- 视频元信息 ----

    def test_register_videos_inserts_records(self):
        """register_videos 应正确插入记录。"""
        self._register_three()
        self.assertEqual(len(self.storage.videos_without_hash()), 3)

    def test_set_hash_updates_record(self):
        """set_hash 应更新 file_hash。"""
        self._register_three()
        self.storage.set_hash("v1", "H1")
        videos = self.storage.videos_without_hash()
        ids = {v.id for v in videos}
        self.assertNotIn("v1", ids)
        self.assertIn("v2", ids)

    def test_group_by_hash_returns_duplicates_only(self):
        """group_by_hash 应仅返回重复分组。"""
        self._register_three()
        self.storage.set_hash("v1", "H1")
        self.storage.set_hash("v2", "H1")
        self.storage.set_hash("v3", "H2")
        groups = self.storage.group_by_hash()
        self.assertEqual(groups.get("H1"), ["v1", "v2"])
        self.assertNotIn("H2", groups)

    # ---- pHash 指纹缓存 ----

    def test_phash_roundtrip_including_max_uint64(self):
        """save_phash/load_phash 应往返一致（含最大 uint64）。"""
        self._register_three()
        seq = np.array([0, 2**64 - 1, 12345], dtype=np.uint64)
        frames = sampled_frames(3)
        # 校正 idx 与 ts 与 seq 对齐
        for i, f in enumerate(frames):
            f.idx = i
            f.ts = i * 0.1
        self.storage.save_phash("v1", seq, frames)
        loaded = self.storage.load_phash("v1")
        self.assertEqual(list(loaded), list(seq))
        self.assertEqual(loaded.dtype, np.uint64)

    def test_load_phash_for_missing_video_empty(self):
        """无记录视频应返回空数组。"""
        loaded = self.storage.load_phash("nope")
        self.assertEqual(len(loaded), 0)

    # ---- 判重结果 ----

    def test_save_match_persists(self):
        """save_match 应正确落库。"""
        self.storage.save_match("v1", "v2", 1, 1.0)
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT level, score FROM matches "
                "WHERE a_id='v1' AND b_id='v2'"
            ).fetchone()
            self.assertEqual(row, (1, 1.0))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()