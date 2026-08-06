# Fabrica 视频重复检测工具详细设计文档

**文档版本**：v1.0  
**更新日期**：2026-08-02  
**目标读者**：Fabrica 工具开发者、视频验重功能使用者、算法测试人员  
**配套实现**：`fabrica/tools/video_dedup/`

---

## 1. 模块概述

### 1.1 职责定位

视频重复检测工具是 Fabrica 平台的首个内置工具，负责在大量视频文件中找出画面内容相同的视频组。核心职责：

- **视频扫描**：递归扫描指定目录，注册所有视频文件元信息
- **文件级去重**：通过文件哈希识别完全相同的文件（字节级）
- **内容级去重**：通过感知哈希和深度特征识别画面内容相同但文件不同的视频
- **结果报告**：输出重复视频组，含相似度分数和判定层级

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **级联过滤** | 三级级联架构，越往后计算越昂贵但处理的量越少，整体效率最大化 |
| **准确率优先** | 使用 CLIP 深度特征作为最终裁决，宁可漏判不可误判 |
| **一切可缓存** | 指纹计算结果落盘存储，重复运行不重算 |
| **设备无关** | 同一份代码在 CPU/GPU 上都能跑，靠配置切换 |
| **容错健壮** | 单个视频解码失败不影响整体流程，跳过并记录错误 |
| **可观测** | 每一级进度、耗时、命中数均可通过日志和进度回调查询 |

### 1.3 边界

**做：**
- 最多 5 万个视频的批量处理
- 支持转码、水印、裁剪、缩放等画面差异的检测
- 视频时长从几秒到小时级
- 可配置的阈值系统

**不做（初期）：**
- 变速 / 剪辑视频的检测（需 DTW 对齐，后续可扩展）
- 音频指纹去重
- 实时视频流处理
- 视频内容分类 / 标签

---

## 2. 模块代码结构

```
fabrica/tools/video_dedup/
├── __init__.py              # 工具注册 + 模块导出
├── config.py                # 工具配置（pydantic 模型）
├── pipeline.py              # 级联调度器（CascadePipeline）
├── sampler.py               # 抽帧模块（自适应采样）
├── device.py                # 设备自动检测（CPU/GPU）
├── models.py                # 数据模型 / ORM
├── storage.py               # SQLite + 向量存储
├── extractors/              # 指纹提取
│   ├── __init__.py
│   ├── filehash.py          # L1 文件哈希
│   ├── phash.py             # L2 pHash 序列
│   └── deepfeat.py          # L3 CLIP 深度特征
├── indexing/                # 索引与检索
│   ├── __init__.py
│   ├── phash_index.py       # FAISS 二进制汉明索引
│   └── deep_index.py        # FAISS 浮点向量索引
└── matching/                # 比对与聚类
    ├── __init__.py
    ├── seq_align.py          # pHash 序列对齐打分
    ├── deep_match.py         # 深度特征比对
    └── cluster.py            # 并查集聚类
```

**模块内部依赖关系：**

```
CascadePipeline（级联调度器，对外统一入口）
    │
    ├── Sampler（抽帧模块）
    │     └── 依赖: PyAV, PIL
    │
    ├── FileHashExtractor（L1）
    │     └── 依赖: hashlib
    │
    ├── PHashExtractor（L2）
    │     └── 依赖: imagehash, numpy
    │     └── 依赖: Sampler（获取帧图像）
    │
    ├── CLIPExtractor（L3）
    │     └── 依赖: open_clip, torch
    │     └── 依赖: Sampler（获取帧图像）
    │
    ├── PHashIndex（FAISS 二进制索引）
    │     └── 依赖: faiss, numpy
    │
    ├── SequenceAligner（序列对齐打分）
    │     └── 依赖: numpy
    │
    ├── DeepMatcher（深度特征比对）
    │     └── 依赖: numpy
    │
    ├── UnionFindCluster（并查集聚类）
    │     └── 纯 Python 数据结构
    │
    └── VideoStorage（存储层）
          └── 依赖: SQLite, numpy
```

---

## 3. 各组件详细设计

### 3.1 Sampler — 抽帧模块

**文件：** `fabrica/tools/video_dedup/sampler.py`

**职责：** 使用 PyAV 对视频文件进行自适应采样，提取关键帧图像。短视频密集抽帧，长视频稀疏但保证总帧数，统一缩放到固定尺寸。

#### 3.1.1 核心属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `min_frames` | int | 16 | 最少采样帧数（短视频保证） |
| `max_frames` | int | 200 | 最大采样帧数（长视频截断） |
| `target_fps` | float | 1.0 | 目标采样帧率（帧/秒） |
| `resize` | tuple | (224, 224) | 统一缩放尺寸 |

#### 3.1.2 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **sample_frames(path, resize, min_frames, max_frames, target_fps)** | str, tuple, int, int, float | `tuple[list[SampledFrame], float]` | 对视频文件抽帧，返回帧列表和时长 |
| **compute_sample_timestamps(duration, min_frames, max_frames, target_fps)** | float, int, int, float | `list[float]` | 计算采样时间点（均匀分布，避开首尾黑帧） |

#### 3.1.3 数据模型

```python
@dataclass
class SampledFrame:
    idx: int                    # 帧序号
    ts: float                   # 时间戳（秒）
    image: Image.Image          # 帧图像（已 resize）
```

#### 3.1.4 实现要点

```python
def sample_frames(
    path: str,
    resize: tuple = (224, 224),
    min_frames: int = 16,
    max_frames: int = 200,
    target_fps: float = 1.0,
) -> tuple[list[SampledFrame], float]:
    """
    用 PyAV 精确 seek 抽帧，只解码需要的帧。

    实现要点：
    - 使用 PyAV 的 seek() 方法精确跳转到采样时间点
    - backward=True 确保 seek 到关键帧前，取解码出的第一帧
    - 长视频不会全解码，只 seek 采样点，小时级视频也很快
    - resize 到 224x224 统一分辨率，同时满足 CLIP 输入尺寸
    """
    container = av.open(path)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    duration = float(stream.duration * stream.time_base) if stream.duration else \
               float(container.duration / av.time_base)

    timestamps = compute_sample_timestamps(duration, min_frames, max_frames, target_fps)
    time_base = stream.time_base

    frames = []
    for i, ts in enumerate(timestamps):
        target = int(ts / time_base)
        container.seek(target, stream=stream, any_frame=False, backward=True)
        for frame in container.decode(stream):
            img = frame.to_image().resize(resize, Image.BILINEAR)
            frames.append(SampledFrame(idx=i, ts=ts, image=img))
            break
    container.close()
    return frames, duration
```

### 3.2 FileHashExtractor — 文件哈希提取器（L1）

**文件：** `fabrica/tools/video_dedup/extractors/filehash.py`

**职责：** 计算视频文件的 MD5 哈希，用于识别字节级完全相同的视频。

#### 3.2.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **file_hash(path, block_size)** | str, int | str | 计算文件 MD5 哈希 |

#### 3.2.2 实现要点

```python
def file_hash(path: str, block_size: int = 1 << 20) -> str:
    """
    计算文件 MD5 哈希。
    block_size = 1MB 分块读取，避免大文件内存溢出。
    """
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()
```

#### 3.2.3 处理策略

相同 hash 的直接归为一组并从后续流程移除（每组保留一个代表参与后续级别，以防它们内容相同但还和别的视频重复）。

### 3.3 PHashExtractor — pHash 序列提取器（L2）

**文件：** `fabrica/tools/video_dedup/extractors/phash.py`

**职责：** 对视频的每一帧计算感知哈希（pHash），生成 64bit 指纹序列。

#### 3.3.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **frame_phash(pil_img, hash_size)** | Image, int | `np.uint64` | 计算单帧 pHash，返回 64bit 整数 |
| **video_phash_sequence(sampled_frames)** | list[SampledFrame] | `np.ndarray` | 计算视频所有帧的 pHash 序列 |

#### 3.3.2 实现要点

```python
def frame_phash(pil_img: Image.Image, hash_size: int = 8) -> np.uint64:
    """
    计算单帧 pHash，返回 64bit 整数。
    hash_size=8 生成 8x8=64bit 指纹，是准确率和速度的平衡点。
    """
    h = imagehash.phash(pil_img, hash_size=hash_size)
    bits = h.hash.flatten()
    val = 0
    for b in bits:
        val = (val << 1) | int(b)
    return np.uint64(val)

def video_phash_sequence(sampled_frames: list[SampledFrame]) -> np.ndarray:
    """计算视频所有帧的 pHash 序列，返回 [n_frames] uint64 数组"""
    return np.array([frame_phash(f.image) for f in sampled_frames], dtype=np.uint64)
```

### 3.4 CLIPExtractor — 深度特征提取器（L3）

**文件：** `fabrica/tools/video_dedup/extractors/deepfeat.py`

**职责：** 使用 OpenCLIP 模型提取视频帧的深度语义特征，用于最终裁决。

#### 3.4.1 核心属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_name` | str | `"ViT-B-32"` | CLIP 模型名称 |
| `pretrained` | str | `"laion2b_s34b_b79k"` | 预训练权重 |
| `device` | str | auto | 计算设备（CPU/GPU） |
| `batch_size` | int | 64 | 推理 batch 大小 |

#### 3.4.2 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **extract(pil_images)** | list[Image] | `np.ndarray` | 批量提取帧的深度特征，返回 [n, dim] 归一化向量 |

#### 3.4.3 实现要点

```python
class CLIPExtractor:
    def __init__(self, model_name="ViT-B-32",
                 pretrained="laion2b_s34b_b79k",
                 device=None, batch_size=64):
        self.device = device or get_device()
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=self.device
        )
        self.model.eval()
        self.batch_size = batch_size

    @torch.no_grad()
    def extract(self, pil_images: list[Image.Image]) -> np.ndarray:
        """
        批量提取深度特征。

        返回 [n, 512] L2 归一化特征向量。
        L2 归一化后，余弦相似度等价于内积，可直接用 FAISS 内积索引加速。
        """
        tensors = torch.stack([self.preprocess(im) for im in pil_images])
        feats = []
        for i in range(0, len(tensors), self.batch_size):
            batch = tensors[i:i+self.batch_size].to(self.device)
            f = self.model.encode_image(batch)
            f = f / f.norm(dim=-1, keepdim=True)
            feats.append(f.cpu().numpy())
        return np.concatenate(feats, axis=0).astype(np.float32)
```

> **模型下载说明**：
> - 首次运行 `CLIPExtractor` 时，OpenCLIP 会自动下载 ViT-B/32 权重（约 350MB）
> - 下载路径：`~/.cache/clip/`（可通过 `OPENCLIP_CACHE_DIR` 环境变量自定义）
> - 若网络受限，可手动下载后放入缓存目录：
>   ```bash
>   # 从 Hugging Face 或镜像站下载
>   wget https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K/resolve/main/open_clip_pytorch_model.bin
>   # 放入缓存目录
>   mv open_clip_pytorch_model.bin ~/.cache/clip/ViT-B-32.pt
>   ```
> - Windows 打包时需将模型文件预下载并打包进 `fabrica/models/` 目录

### 3.5 PHashIndex — FAISS 二进制汉明索引

**文件：** `fabrica/tools/video_dedup/indexing/phash_index.py`

**职责：** 使用 FAISS 二进制索引管理所有视频的 pHash 指纹，支持汉明距离范围检索。

#### 3.5.1 核心属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `index` | `faiss.IndexBinaryFlat` | FAISS 二进制索引（64bit） |
| `frame_owner` | `list[int]` | 每个向量所属的 video_id |
| `k` | `int` | 默认最近邻检索数（默认 32） |

#### 3.5.2 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **add(video_id, phash_seq)** | int, np.ndarray | None | 将视频的 pHash 序列加入索引 |
| **search(phash_seq, k)** | np.ndarray, int | tuple | 检索最近邻，返回距离矩阵和索引矩阵 |
| **generate_candidates(video_ids, hit_threshold)** | list[int], int | list[tuple] | 生成候选视频对 |

#### 3.5.3 候选生成策略

对视频 A 的每一帧，检索最近 k 个帧指纹，统计命中了哪些其他视频的帧。命中帧数超过 `hit_threshold` 的视频对成为候选，避免两两暴力比对。

> **k 参数说明**：k 默认为 32。每视频采样约 8 帧，若 k=8 则自身帧（距离 0）占满 top-k，跨视频真匹配被挤出。k=32 确保跨视频真匹配帧有足够余量进入候选。

**存储规模估算**：5 万视频 × 平均 100 帧 = 500 万个 64bit 向量，`IndexBinaryFlat` 内存约 40MB。

### 3.6 SequenceAligner — 序列对齐打分器

**文件：** `fabrica/tools/video_dedup/matching/seq_align.py`

**职责：** 对候选视频对的 pHash 序列进行对齐打分，计算相似度。

#### 3.6.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **hamming(a, b)** | uint64, uint64 | int | 计算两个 64bit 指纹的汉明距离 |
| **sequence_score(seq_a, seq_b, frame_thresh)** | ndarray, ndarray, int | float | 计算序列相似度（0~1） |

#### 3.6.2 实现要点

```python
def sequence_score(seq_a: np.ndarray, seq_b: np.ndarray,
                   frame_thresh: int = 16) -> float:
    """
    对每一帧 a, 在 b 中找最相似帧, 汉明距离 < frame_thresh 算命中。
    返回命中比例（以短序列为分母）。

    frame_thresh: 64bit 中允许不同的位数，默认 16 表示 64 位中最多 16 位不同。
    T5.7 调参将默认值从 8 提升到 16，以覆盖水印/裁剪等派生版本的帧间差异。
    """
    hits = 0
    short, long_ = (seq_a, seq_b) if len(seq_a) <= len(seq_b) else (seq_b, seq_a)
    for ha in short:
        best = min(hamming(ha, hb) for hb in long_)
        if best <= frame_thresh:
            hits += 1
    return hits / len(short)
```

#### 3.6.3 判定阈值

| 分数范围 | 判定 | 后续处理 |
|---------|------|---------|
| `>= 0.90` | 直接判重（Level 2） | 加入结果，不进入 L3 |
| `[0.50, 0.90)` | 疑似 | 进入 L3 深度特征裁决 |
| `< 0.50` | 不判重 | 丢弃 |

> **frame_thresh 默认值**：T5.7 调参将默认值从 8 提升到 16，以覆盖水印/裁剪等
> 派生版本在 pHash 上较高的帧间汉明距离（9-15 位）。

### 3.7 DeepMatcher — 深度特征比对器

**文件：** `fabrica/tools/video_dedup/matching/deep_match.py`

**职责：** 对进入 L3 的疑似对，用 CLIP 深度特征序列进行余弦相似度比对。

#### 3.7.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **deep_sequence_score(feat_a, feat_b, sim_thresh)** | ndarray, ndarray, float | float | 计算深度特征序列相似度 |

#### 3.7.2 实现要点

```python
def deep_sequence_score(feat_a: np.ndarray, feat_b: np.ndarray,
                        sim_thresh: float = 0.92) -> float:
    """
    feat: [n, dim] 已 L2 归一化。余弦相似度 = 矩阵内积。
    对短序列的每一帧，在长序列中找到最相似帧，余弦 > sim_thresh 算命中。
    """
    short, long_ = (feat_a, feat_b) if len(feat_a) <= len(feat_b) else (feat_b, feat_a)
    sim = short @ long_.T           # [ns, nl]
    best = sim.max(axis=1)          # 每帧最佳匹配
    hits = (best >= sim_thresh).sum()
    return hits / len(short)
```

#### 3.7.3 判定阈值

| 分数范围 | 判定 |
|---------|------|
| `>= 0.85` | 判重（Level 3 最终裁决） |
| `< 0.85` | 不判重 |

CLIP 特征对水印、裁剪、色彩变化极鲁棒，这是准确率的最终保证。

### 3.8 UnionFindCluster — 并查集聚类器

**文件：** `fabrica/tools/video_dedup/matching/cluster.py`

**职责：** 将所有判重关系（视频对）合并为重复组（传递性闭合）。

#### 3.8.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **build_groups(n_videos, matches)** | int, list[tuple] | `list[list[int]]` | 构建重复组，返回每组包含的 video_id 列表 |

#### 3.8.2 实现要点

```python
class UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int):
        self.p[self.find(a)] = self.find(b)


def build_groups(n_videos: int, matches: list[tuple]) -> list[list[int]]:
    """
    将所有判重关系合并为组。
    matches: [(a_id, b_id, level, score), ...]
    使用并查集实现传递性合并（A=B, B=C ⇒ A,B,C 一组）。
    """
    uf = UnionFind(n_videos)
    for a, b, *_ in matches:
        uf.union(a, b)
    groups = {}
    for i in range(n_videos):
        groups.setdefault(uf.find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]
```

### 3.9 CascadePipeline — 级联调度器

**文件：** `fabrica/tools/video_dedup/pipeline.py`

**职责：** 编排三级级联去重流程，管理各阶段的执行顺序、数据传递和结果汇总。

#### 3.9.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **run_pipeline(cfg, progress_cb)** | dict, Callable | dict | 执行完整级联流程，返回结果报告 |

#### 3.9.2 执行流程

```
run_pipeline:
    │
    ├── Stage 0: 扫描视频
    │   ├── 递归扫描 input_dir
    │   ├── 过滤视频扩展名（.mp4, .avi, .mov, .mkv 等）
    │   ├── 注册到数据库
    │   └── 报告: 扫描完成，共 N 个视频
    │
    ├── Stage 1: 文件哈希（L1）
    │   ├── 对未计算 hash 的视频计算 MD5
    │   ├── 按 hash 分组
    │   ├── 每组保留代表视频
    │   └── 报告: L1 去重 N 组，剩余 M 个视频
    │
    ├── Stage 2: pHash 序列（L2）
    │   ├── 对代表视频抽帧
    │   ├── 计算 pHash 序列
    │   ├── 构建 FAISS 二进制索引
    │   ├── 生成候选对
    │   ├── 序列对齐打分
    │   ├── 直接判重 / 疑似 / 丢弃
    │   └── 报告: L2 直接判重 N 对，疑似 M 对
    │
    ├── Stage 3: 深度特征（L3）
    │   ├── 对疑似对提取 CLIP 特征
    │   ├── 深度特征比对
    │   ├── 最终裁决
    │   └── 报告: L3 判重 N 对
    │
    └── Stage 4: 聚类 + 输出
        ├── 并查集合并所有判重关系
        ├── 展开 L1 组
        └── 输出重复组报告
```

### 3.10 VideoStorage — 存储层

**文件：** `fabrica/tools/video_dedup/storage.py`

**职责：** 管理视频元数据、指纹缓存和结果数据的持久化。

#### 3.10.1 SQLite 表结构

```sql
-- 视频基本信息
CREATE TABLE videos (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE,
    size        INTEGER,
    duration    REAL,
    width       INTEGER,
    height      INTEGER,
    file_hash   TEXT,          -- L1
    phash_done  INTEGER DEFAULT 0,
    deep_done   INTEGER DEFAULT 0,
    frame_count INTEGER        -- 采样帧数
);

-- pHash 序列（每帧一行）
CREATE TABLE phash_frames (
    video_id  INTEGER,
    frame_idx INTEGER,
    ts        REAL,            -- 时间戳（秒）
    phash     BLOB,            -- 8 bytes (64bit)
    PRIMARY KEY (video_id, frame_idx)
);

-- 判定结果（视频对）
CREATE TABLE matches (
    a_id     INTEGER,
    b_id     INTEGER,
    level    INTEGER,          -- 1/2/3 由哪级判定
    score    REAL,
    PRIMARY KEY (a_id, b_id)
);
```

#### 3.10.2 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **register_videos(video_list)** | list[dict] | None | 批量注册视频元信息 |
| **videos_without_hash()** | — | list[Video] | 获取未计算文件哈希的视频 |
| **set_hash(video_id, hash_val)** | int, str | None | 设置文件哈希值 |
| **group_by_hash()** | — | list[list[int]] | 按文件哈希分组 |
| **save_phash(video_id, seq, frames)** | int, ndarray, list | None | 保存 pHash 序列 |
| **load_phash(video_id)** | int | ndarray | 加载 pHash 序列 |
| **save_deep(video_id, feats)** | int, ndarray | None | 保存深度特征（存为 .npy 文件） |
| **load_deep(video_id)** | int | ndarray | 加载深度特征 |
| **save_match(a, b, level, score)** | int, int, int, float | None | 保存判重结果 |

#### 3.10.3 数据库迁移策略

SQLite schema 可能随版本迭代变化，需提供迁移机制：

| 版本 | 变更内容 | 迁移方式 |
|------|---------|---------|
| v1.0 | 初始版本 | — |
| 后续版本 | 新增字段/表 | 自动检测 + 迁移脚本 |

**策略**：在 `vdup/storage.py` 中维护 `SCHEMA_VERSION` 常量，启动时检测数据库版本号，自动执行增量迁移脚本。

```python
SCHEMA_VERSION = 1

def migrate(db_path: str):
    """检测并执行数据库迁移"""
    version = _get_version(db_path)
    if version < 1:
        _apply_v1_schema(db_path)
    # 后续版本...
    _set_version(db_path, SCHEMA_VERSION)
```

---

## 4. 配置项

工具配置通过 `config.yaml` 的 `tools.video_dedup` 节控制：

```yaml
tools:
  video_dedup:
    # 输入输出
    input_dir: ""              # 视频输入目录（必填）
    output: "result.json"      # 结果输出路径
    recursive: true            # 是否递归扫描子目录

    # 抽帧参数
    sample:
      min_frames: 16           # 最少采样帧数
      max_frames: 200          # 最大采样帧数
      target_fps: 1.0          # 目标采样帧率
      resize: [224, 224]       # 统一缩放尺寸

    # 设备
    device: "auto"             # auto / cpu / cuda

    # L1 文件哈希
    l1:
      block_size: 1048576      # 读取块大小（字节）

    # L2 pHash
    l2:
      frame_thresh: 16         # 单帧汉明阈值（0-64），T5.7 调参后默认 16
      confirm: 0.90            # 直接判重比例阈值
      suspect: 0.50            # 进入 L3 的比例阈值下限
      search_k: 32             # FAISS 检索最近邻数，T5.7 调参后默认 32
      hit_threshold: 3         # 候选对命中帧数阈值

    # L3 深度特征
    l3:
      model_name: "ViT-B-32"   # CLIP 模型名称
      pretrained: "laion2b_s34b_b79k"  # 预训练权重
      batch_size: 64           # 推理 batch 大小
      sim_thresh: 0.92         # 单帧余弦相似度阈值
      confirm: 0.85            # 判重比例阈值

    # 存储
    storage:
      db_path: "data/video_dedup.db"    # 数据库路径
      feature_dir: "data/video_dedup_features"  # 特征文件目录
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `tools.video_dedup.input_dir` | str | `""` | 视频输入目录 |
| `tools.video_dedup.output` | str | `"result.json"` | 结果输出路径 |
| `tools.video_dedup.recursive` | bool | `true` | 是否递归扫描 |
| `tools.video_dedup.sample.min_frames` | int | `16` | 最少采样帧数 |
| `tools.video_dedup.sample.max_frames` | int | `200` | 最大采样帧数 |
| `tools.video_dedup.sample.target_fps` | float | `1.0` | 目标采样帧率 |
| `tools.video_dedup.device` | str | `"auto"` | 计算设备 |
| `tools.video_dedup.l2.frame_thresh` | int | `16` | pHash 单帧汉明阈值 |
| `tools.video_dedup.l2.confirm` | float | `0.90` | L2 直接判重比例 |
| `tools.video_dedup.l2.suspect` | float | `0.50` | L2 疑似下限 |
| `tools.video_dedup.l3.sim_thresh` | float | `0.92` | CLIP 单帧余弦阈值 |
| `tools.video_dedup.l3.confirm` | float | `0.85` | L3 判重比例 |
| `tools.video_dedup.storage.db_path` | str | `"data/video_dedup.db"` | 数据库路径 |

---

## 5. 模块关系与数据流

### 5.1 级联调度时序

```
CascadePipeline      Sampler         PHashExtractor     CLIPExtractor      FAISS Index      Storage
    │                   │                  │                  │                │               │
    │── Stage 0 ───────▶│                  │                  │                │               │
    │   scan_videos()   │                  │                  │                │               │
    │◀── video_list ────│                  │                  │                │               │
    │                                                                          │               │
    │── register_videos──────────────────────────────────────────────────────────────────────▶│
    │                                                                                          │
    │── Stage 1 ───────▶│                  │                  │                │               │
    │   file_hash()     │                  │                  │                │               │
    │◀── hash_val ──────│                  │                  │                │               │
    │── set_hash ────────────────────────────────────────────────────────────────────────────▶│
    │                                                                                          │
    │── Stage 2 ───────▶│                  │                  │                │               │
    │   sample_frames()─▶                  │                  │                │               │
    │   (for each video)│─ frames ────────▶│                  │                │               │
    │                   │                  │── phash_seq ────▶│                │               │
    │                   │                  │                  │                │               │
    │── add_to_index ──────────────────────────────────────────────────────────▶               │
    │                                                                          │               │
    │── search_candidates ────────────────────────────────────────────────────▶                │
    │                                                                          │               │
    │── sequence_score   │                  │                  │                │               │
    │   (for each pair)  │                  │                  │                │               │
    │                                                                          │               │
    │── save_match (L2) ────────────────────────────────────────────────────────────────────▶│
    │                                                                                          │
    │── Stage 3 ───────▶│                                         │                             │
    │   sample_frames()─▶                                         │                             │
    │   (for suspects)  │─ frames ───────────────────────────────▶│                             │
    │                                                              │── extract()               │
    │                                                              │◀── features ──────────────│
    │                                                              │                            │
    │── deep_sequence_score ──────────────────────────────────────▶                             │
    │                                                                                            │
    │── save_match (L3) ──────────────────────────────────────────────────────────────────────▶│
    │                                                                                            │
    │── Stage 4            │                  │                  │                │               │
    │   build_groups() ───────────────────────────────────────────────────────────────────────▶│
    │                                                                                            │
    │── write_report()                                                                           │
```

### 5.2 与其他模块的关系

| 关系方向 | 模块 | 接口 | 说明 |
|----------|------|------|------|
| **工具 → 平台核心** | ToolRegistry | `@tool.register` | 注册为 Fabrica 平台工具 |
| **工具 → 基础设施** | Utils/device | `get_device()` | 获取计算设备 |
| **工具 → 基础设施** | Utils/logger | `get_logger()` | 日志记录 |
| **工具 → 平台核心** | ToolBase | `run(params, ctx)` | 通过平台上下文报告进度 |

---

## 6. 阈值调参指南

### 6.1 参数总览

| 参数 | 含义 | 起始值 | 调参方向 | 影响 |
|------|------|--------|---------|------|
| `l2.frame_thresh` | pHash 单帧汉明阈值 | 16 | 越大越宽松 | 准确率 ↔ 召回率 |
| `l2.confirm` | L2 直接判重比例 | 0.90 | 越高越严格 | 控制 L2 判重精度 |
| `l2.suspect` | 进 L3 的下限 | 0.50 | 越低越敏感 | 控制 L3 处理量 |
| `l3.sim_thresh` | CLIP 单帧余弦阈值 | 0.92 | 越高越严格 | 核心精度旋钮 |
| `l3.confirm` | L3 判重比例 | 0.85 | 越高越严格 | 最终裁决 |

### 6.2 调参方法论

1. **准备标注测试集**：准备一批已知答案的视频对
   - 真重复：同一视频转码、加水印、裁剪、缩放、变分辨率
   - 真不同：内容不同但可能画面相似（如同一系列节目片头）

2. **从 L2 开始调**：固定 L3 参数，调节 L2 参数，使 L2 在保证高精度的前提下最大化召回

3. **再调 L3**：对 L2 无法确定的"疑似"对，调节 L3 参数，找到最优 Precision-Recall 平衡点

4. **画 PR 曲线**：在测试集上绘制 Precision-Recall 曲线，选择高 Precision 的工作点

### 6.3 关键测试用例

| 测试场景 | 预期结果 | 主要验证层级 |
|---------|---------|------------|
| 同视频不同分辨率 | 判重 | L2 / L3 |
| 加静态水印 | 判重 | L3（pHash 可能失败） |
| 黑边裁剪 | 判重 | L3 |
| 不同视频某几帧相似 | 不判重 | 序列打分（而非单帧） |
| 小时级长视频 | 正常抽帧，不 OOM | Sampler |
| 损坏/无法解码视频 | 跳过，不中断 | Pipeline |

---

## 7. 测试策略

### 7.1 测试用例设计

| 测试类型 | 测试内容 | 验证方法 |
|---------|---------|---------|
| 单元测试 | `compute_sample_timestamps` 各种时长下的采样点数 | 断言数量在 [min_frames, max_frames] 范围内 |
| 单元测试 | `frame_phash` 相同图片返回相同 hash | 两次调用结果相等 |
| 单元测试 | `hamming` 距离计算 | 已知距离的手工验证 |
| 单元测试 | `sequence_score` 完全相同的序列 | 返回 1.0 |
| 单元测试 | `UnionFind` 合并传递性 | union(1,2), union(2,3) → find(1)=find(3) |
| 集成测试 | 完整 L1+L2 级联（10 个小视频） | 已知重复对的检出率 |
| 集成测试 | 完整 L1+L2+L3 级联（含水印/裁剪） | L3 能够补回 L2 漏掉的重复对 |
| 集成测试 | 空目录 / 无视频文件 | 不崩溃，返回空结果 |
| 集成测试 | 损坏视频文件 | 跳过，流程继续 |

### 7.2 测试夹具设计

使用 `VideoFixtureFactory` 生成测试视频，避免依赖外部视频文件：

```python
class VideoFixtureFactory:
    """生成测试用视频夹具"""

    @staticmethod
    def create_test_video(path: Path, duration: int = 5,
                          resolution: tuple = (1920, 1080),
                          content: str = "solid_color") -> Path:
        """使用 PyAV 生成测试视频"""

    @staticmethod
    def create_derived_video(src: Path, watermark: bool = False,
                             crop: bool = False, resize: tuple = None,
                             transcode: str = None) -> Path:
        """从源视频生成派生版本"""
```

### 7.3 精度评估方法

```python
def evaluate(gold_standard: list[set], predictions: list[set]) -> dict:
    """
    评估去重效果。

    gold_standard: 真实重复组列表，每组为 video_id 集合
    predictions: 预测重复组列表

    返回: Precision, Recall, F1
    """
    # 将所有组展开为"视频对"集合
    def pairs_from_groups(groups):
        pairs = set()
        for group in groups:
            ids = sorted(group)
            for i in range(len(ids)):
                for j in range(i+1, len(ids)):
                    pairs.add((ids[i], ids[j]))
        return pairs

    gold_pairs = pairs_from_groups(gold_standard)
    pred_pairs = pairs_from_groups(predictions)

    tp = len(pred_pairs & gold_pairs)
    fp = len(pred_pairs - gold_pairs)
    fn = len(gold_pairs - pred_pairs)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}
```

---

## 8. 部署与打包

### 8.1 依赖安装

本工具依赖由平台统一管理，详见 [README 安装指南](../../README.md#71-环境准备)。以下为工具特定的额外依赖清单（供参考）：

`requirements-base.txt`（跨平台通用）📝 待创建：

```
pyav
imagehash
pillow
numpy
faiss-cpu
open_clip_torch
typer
pydantic
pyyaml
```

`requirements-linux-dev.txt`（Linux 开发环境）📝 待创建：

```
-r requirements-base.txt
torch --index-url https://download.pytorch.org/whl/cpu
```

`requirements-win-deploy.txt`（Windows 部署环境）📝 待创建：

```
-r requirements-base.txt
torch --index-url https://download.pytorch.org/whl/cu121
```

### 8.2 PyInstaller 打包

`build_win.spec` 配置（📝 待创建，详见 [README 打包指南](../../README.md#81-windows-打包)）。该文件由平台统一维护，各工具无需单独定义。

### 8.3 打包注意事项

| 风险 | 对策 |
|------|------|
| CUDA DLL 较大 | 使用 onedir 模式而非 onefile |
| PyTorch 依赖收集不全 | 打包后在 Windows 上测试启动 |
| CLIP 权重下载 | 预下载权重放入 `models/` 目录随包分发 |
| PyAV 依赖 libav | Windows 上 `pip install av` 自带预编译 libav |

---

## 9. 性能预估与优化

### 9.1 性能预估（5 万视频，混合时长）

| 阶段 | 耗时估计 | 瓶颈 |
|------|---------|------|
| L1 文件哈希 | 几分钟 | IO（磁盘读取） |
| L2 抽帧 + pHash | 数小时（CPU 多进程并行） | 视频解码（CPU） |
| L2 检索 + 打分 | 分钟级 | FAISS 检索 |
| L3 特征提取 | 几分钟到几十分钟（GPU） | 模型推理 |
| L3 比对 + 聚类 | 秒级 | 矩阵运算 |

### 9.2 优化方向

| 优化项 | 预期效果 | 实施难度 |
|--------|---------|---------|
| L2 抽帧多进程并行 | 线性加速（CPU 核数） | 低 |
| 使用 `IndexBinaryHNSW` 近似索引 | 加速 L2 检索 | 低 |
| 提高 `hit_threshold` 减少候选对 | 减少 L2 打分和 L3 计算量 | 低 |
| 开发环境临时换 MobileNet 替代 CLIP | 加速 L3 验证 | 中 |

### 9.3 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| L2 候选对仍过多 | L3 计算量大 | 提高候选命中帧数门槛；使用 HNSW 加速 |
| CLIP 在 CPU 开发机太慢 | 开发验证困难 | 开发只跑小样本 + `--limit`；或临时换 MobileNet |
| PyInstaller + CUDA 打包失败 | 无法分发 | 退回 conda-pack 便携环境方案 |
| 损坏/无法解码视频 | 流程中断 | 每个视频 try/except，记录失败列表，跳过继续 |
| 内存：5 万视频特征 | CLIP 512 维 × 100 帧 × 5 万 ≈ 10GB | 特征落盘（.npy），比对时按需加载；L3 只涉及少量疑似对 |

---

## 10. 设计决策记录（DDR）

### 10.1 为什么三级级联而不是端到端

**问题**：是否应当使用一个端到端的深度学习模型直接判断视频是否重复？

**决策**：**三级级联**。

**原因**：
1. **效率**：5 万视频两两比对是 O(n²) 的 12.5 亿对，端到端模型无法处理
2. **可解释性**：每级输出可单独审计，便于调优
3. **渐进成本**：L1 几乎免费过滤掉大量完全相同的文件，L2 用轻量级 pHash 进一步过滤，L3 只处理少量疑似对
4. **工程可行性**：每级可独立开发、测试、优化

### 10.2 为什么选 pHash 而非 dHash / aHash

**问题**：L2 感知哈希应当选择哪种算法？

**决策**：**pHash**。

**原因**：
1. pHash 基于 DCT 变换，对微小的色彩/亮度变化不敏感，适合视频帧比对
2. dHash 对边缘敏感，视频编码导致的块效应会引入噪声
3. aHash 过于简单，对亮度变化敏感
4. pHash 64bit 指纹大小适中，适合 FAISS 二进制索引

### 10.3 为什么选 CLIP 而非传统 CNN

**问题**：L3 深度特征应当使用传统 CNN（如 ResNet）还是 CLIP？

**决策**：**OpenCLIP ViT-B/32**。

**原因**：
1. CLIP 训练数据量大（4 亿图文对），对水印/字幕/色彩/压缩噪声的鲁棒性远超传统 CNN
2. CLIP 的语义空间更丰富，能够区分"画面相似但内容不同"的边界情况
3. ViT-B/32 的 512 维特征向量大小适中，检索效率高
4. 代价是模型 ~350MB，需要 PyTorch，但有 GPU 时推理速度很快

### 10.4 为什么选 FAISS 而非暴力比对

**问题**：帧指纹的相似检索应当使用暴力比对还是 FAISS 索引？

**决策**：**FAISS**。

**原因**：
1. 5 万视频 × 100 帧 = 500 万向量，暴力比对 O(n²) 不可行
2. FAISS 的 `IndexBinaryFlat` 对 64bit 向量索引内存仅 40MB
3. 支持汉明距离（L2 pHash）和余弦距离（L3 CLIP）两种检索
4. 后续可扩展为 `IndexBinaryHNSW` 近似检索加速

### 10.5 为什么选 PyAV 而非 OpenCV / ffmpeg-python

**问题**：视频解码抽帧应当使用哪种方案？

**决策**：**PyAV**。

**原因**：
1. 比反复调用 ffmpeg 子进程快（无进程创建开销）
2. 能精确 seek，只解码需要的帧，避免解码全片
3. 与 OpenCV 的 VideoCapture 相比，PyAV 对编码格式的兼容性更好（HEVC、AV1 等）
4. `stream.thread_type = "AUTO"` 自动利用多线程解码