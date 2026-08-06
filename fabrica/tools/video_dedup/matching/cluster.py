"""并查集聚类器（T5.3）。

将所有判重关系（视频对）合并为重复组（传递性闭合）：
- UnionFind: 并查集（路径压缩 + 按秩合并）
- build_groups: 将 matches 合并为 size>1 的重复组
- expand_groups: 将 L1 去重的代表视频展开回全组

用法：
    from fabrica.tools.video_dedup.matching import (
        UnionFind, build_groups, expand_groups,
    )

    groups = build_groups(10, [(1, 2), (2, 3)])   # [[1, 2, 3], ...]
"""

from typing import Dict, List, Sequence


# ============================================================================
# 并查集
# ============================================================================

class UnionFind:
    """并查集（不相交集合）。

    支持路径压缩与按秩合并，find 平均复杂度接近 O(1)。

    Attributes:
        parent: 每个元素的父节点（根节点指向自身）。
        rank: 每个根节点的秩（用于按秩合并）。
    """

    def __init__(self, n: int) -> None:
        """初始化 n 个独立元素。

        Args:
            n: 元素总数。
        """
        self.parent: List[int] = list(range(n))
        self.rank: List[int] = [0] * n

    def find(self, x: int) -> int:
        """查找元素所属集合的根节点（带路径压缩）。

        Args:
            x: 元素下标。

        Returns:
            根节点下标。
        """
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        # 二次遍历，将路径上所有节点直接指向根
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        """合并 a、b 所在的两个集合（按秩合并）。

        Args:
            a: 元素下标。
            b: 元素下标。
        """
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


# ============================================================================
# 构建重复组
# ============================================================================

def build_groups(
    n_videos: int,
    matches: Sequence[Sequence],
) -> List[List[int]]:
    """将所有判重关系合并为重复组（传递性闭合）。

    Args:
        n_videos: 视频总数（并查集规模）。
        matches: 判重关系列表，元素形如 (a_id, b_id, level, score)，
            仅使用前两个字段。

    Returns:
        list[list[int]]，每组包含重复的 video_id 集合（升序）。
        仅返回 size > 1 的组（singleton 不输出）。
    """
    uf = UnionFind(n_videos)
    for record in matches:
        a, b, *_ = record
        uf.union(a, b)

    groups: Dict[int, List[int]] = {}
    for i in range(n_videos):
        groups.setdefault(uf.find(i), []).append(i)
    return [
        sorted(members)
        for members in groups.values()
        if len(members) > 1
    ]


# ============================================================================
# 展开 L1 组
# ============================================================================

def expand_groups(
    l1_groups: Sequence[Sequence],
    l2_groups: Sequence[Sequence],
) -> List[List[int]]:
    """将 L2 组中的代表视频展开回其所属的 L1 全组。

    L1 阶段按文件哈希去重后，每组仅保留一个代表进入 L2/L3；
    L2 组中的「代表」需替换为完整的 L1 成员集合。

    Args:
        l1_groups: L1 重复组列表，每组为字节相同的视频 id 集合。
        l2_groups: 聚类后的重复组列表，每组包含代表视频 id。

    Returns:
        list[list[int]]，展开后的重复组（组内 id 升序）。
        无法命中 L1 映射的 id 保持自身。
    """
    # 建立「成员 -> 全组」映射，任一成员作为代表都能展开
    rep_to_members: Dict[int, Sequence] = {}
    for group in l1_groups:
        for member in group:
            rep_to_members[member] = group

    expanded: List[List[int]] = []
    for group in l2_groups:
        members: set = set()
        for rep in group:
            members.update(rep_to_members.get(rep, [rep]))
        expanded.append(sorted(members))
    return expanded