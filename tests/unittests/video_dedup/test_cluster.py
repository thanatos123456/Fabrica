"""并查集聚类器测试（T5.3）。

测试目标：fabrica/tools/video_dedup/matching/cluster.py
覆盖：UnionFind 的查找/合并/路径压缩/按秩合并；
build_groups 的传递性合并与 singleton 过滤；expand_groups 的 L1 展开。
"""

import unittest

from fabrica.tools.video_dedup.matching.cluster import (
    UnionFind,
    build_groups,
    expand_groups,
)


# ============================================================================
# UnionFind 测试
# ============================================================================

class TestUnionFind(unittest.TestCase):
    """UnionFind 类测试集。"""

    def test_find_singleton_returns_self(self):
        """未合并时 find(x) 应返回自身。"""
        uf = UnionFind(5)
        for x in range(5):
            self.assertEqual(uf.find(x), x)

    def test_union_chain(self):
        """union(1,2), union(2,3) 后 find(1) == find(3)。"""
        uf = UnionFind(5)
        uf.union(1, 2)
        uf.union(2, 3)
        self.assertEqual(uf.find(1), uf.find(3))
        self.assertNotEqual(uf.find(0), uf.find(1))

    def test_transitive_disjoint(self):
        """union(1,2), union(3,4), union(2,3) 后 find(1) == find(4)。"""
        uf = UnionFind(5)
        uf.union(1, 2)
        uf.union(3, 4)
        uf.union(2, 3)
        self.assertEqual(uf.find(1), uf.find(4))
        self.assertNotEqual(uf.find(0), uf.find(1))

    def test_union_already_connected_noop(self):
        """合并已连接集合应是 no-op，根不变。"""
        uf = UnionFind(3)
        uf.union(0, 1)
        root = uf.find(0)
        uf.union(0, 1)
        self.assertEqual(uf.find(0), root)
        self.assertEqual(uf.find(1), root)

    def test_path_compression_idempotent(self):
        """路径压缩后多次 find 幂等，parent 指向根。"""
        uf = UnionFind(6)
        # 构造链 0->1->2->3
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(2, 3)
        root = uf.find(3)
        self.assertEqual(uf.find(0), root)
        self.assertEqual(uf.find(0), root)
        # 压缩后 0 的 parent 直接指向根
        self.assertEqual(uf.find(uf.parent[0]), uf.parent[0])

    def test_rank_non_negative(self):
        """按秩合并后 rank 应非负且根节点递增。"""
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(0, 2)
        self.assertTrue(all(r >= 0 for r in uf.rank))
        self.assertEqual(uf.find(0), uf.find(3))


# ============================================================================
# build_groups 测试
# ============================================================================

class TestBuildGroups(unittest.TestCase):
    """build_groups 函数测试集。"""

    def test_transitive_merge(self):
        """matches=[(1,2),(2,3)] 应合并为 [1,2,3]。"""
        groups = build_groups(4, [(1, 2), (2, 3)])
        self.assertIn([1, 2, 3], groups)

    def test_skips_singletons(self):
        """仅返回 size>1 的组。"""
        groups = build_groups(3, [(1, 2)])
        self.assertEqual(groups, [[1, 2]])

    def test_empty_matches(self):
        """空 matches 应返回空列表。"""
        self.assertEqual(build_groups(4, []), [])

    def test_ignores_extra_fields(self):
        """matches 元素含 level/score 额外字段应正常合并。"""
        groups = build_groups(4, [(1, 2, 3, 0.9)])
        self.assertEqual(groups, [[1, 2]])

    def test_ids_sorted_ascending(self):
        """组内 id 应升序。"""
        groups = build_groups(4, [(3, 1)])
        self.assertEqual(groups, [[1, 3]])


# ============================================================================
# expand_groups 测试
# ============================================================================

class TestExpandGroups(unittest.TestCase):
    """expand_groups 函数测试集。"""

    def test_expand_representatives(self):
        """将 L2 组中的代表展开为 L1 全组。"""
        l1 = [[1, 10, 11], [2, 20]]
        l2 = [[1, 2]]
        out = expand_groups(l1, l2)
        self.assertEqual(out, [[1, 2, 10, 11, 20]])

    def test_rep_not_in_l1_falls_back(self):
        """未命中 L1 映射的 id 应保持自身。"""
        l1 = [[1, 10]]
        l2 = [[5, 1]]
        out = expand_groups(l1, l2)
        self.assertEqual(out, [[1, 5, 10]])

    def test_empty_l2(self):
        """空 L2 应返回空列表。"""
        self.assertEqual(expand_groups([[1, 10]], []), [])


if __name__ == "__main__":
    unittest.main()