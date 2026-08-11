# Fabrica 桌面交互功能增强设计文档

**文档版本**：v1.0
**更新日期**：2026-08-10
**目标读者**：Fabrica 前端开发者、桌面集成开发者、视频验重功能使用者
**配套实现**：`fabrica/desktop/`、`fabrica/server/static/`、`fabrica/tools/video_dedup/`
**前置文档**：[desktop_integration.md](./desktop_integration.md)、[video_dedup.md](../tools/video_dedup.md)

---

## 1. 模块概述

### 1.1 背景与目标

Fabrica 桌面集成模块（[desktop_integration.md](./desktop_integration.md)）通过 pywebview 将 Web 前端包装为原生桌面窗口，解决了"exe 打开后只显示终端"的问题。但当前前端交互能力受限于浏览器安全沙箱，无法满足视频验重工具的三个核心交互需求：

| 需求 | 当前问题 | 目标体验 |
|------|---------|---------|
| 目录选择 | 浏览器 `<input type="file">` 无法获取完整路径，且代码主动截断路径只保留文件名 | 点击"浏览"弹出原生目录选择对话框，填入完整路径 |
| 结果展示 | 结果以 JSON 文本原样输出，无视频路径、无"打开文件夹"功能 | 结构化展示重复组+视频路径，点击按钮打开文件管理器并选中文件 |
| 关键帧对比 | 关键帧图像抽帧后即丢弃，未持久化，无法展示 | 展示重复组视频关键帧网格，高亮判定为相同的帧对 |

本文档定义三个功能的完整设计方案，作为后续实现的依据。

### 1.2 功能清单

| 编号 | 功能 | 依赖层 | 优先级 |
|------|------|--------|--------|
| F1 | 目录选择器（原生文件对话框） | pywebview JS API | P0 |
| F2 | 结果展示与打开文件夹 | pywebview JS API + 结果结构改造 | P0 |
| F3 | 关键帧展示（仅重复组+高亮匹配帧） | 抽帧保存 + 静态文件服务 + 前端网格 | P1 |

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| **桌面优先，浏览器回退** | 桌面环境（pywebview）使用原生能力，浏览器开发环境回退为手动输入/隐藏按钮 |
| **结果结构向后兼容** | `final_groups` 结构改造时保留原始 ID 信息，新增字段不破坏现有消费方 |
| **按需保存关键帧** | 仅对最终重复组视频保存关键帧图像，避免对全部视频产生磁盘占用 |
| **复用已有 pHash 数据** | 帧级匹配信息利用已存储的 pHash 序列重新计算，不修改抽帧流程的核心逻辑 |
| **静态文件服务图像** | 关键帧 JPEG 通过 FastAPI StaticFiles 提供 HTTP 访问，前端直接 `<img src>` 加载 |

---

## 2. 技术基础：pywebview JS API 桥接

### 2.1 桥接机制

pywebview 提供 `js_api` 参数，可将 Python 对象的方法暴露给前端 JavaScript 调用。前端通过 `window.pywebview.api.<method_name>()` 异步调用，返回 Promise。

```
┌─────────────────────────────────────┐
│        前端 JavaScript               │
│  window.pywebview.api.method(args)  │
│  → 返回 Promise                     │
└──────────────┬──────────────────────┘
               │ pywebview 桥接层
┌──────────────▼──────────────────────┐
│        Python DesktopAPI 类          │
│  def method(self, args): ...        │
│  return result                      │
└─────────────────────────────────────┘
```

**关键约束**：
- `js_api` 对象的方法参数和返回值必须可 JSON 序列化（str/int/float/bool/list/dict/None）
- 方法调用是异步的，前端需 `await`
- `window.pywebview` 对象仅在 pywebview 桌面环境存在，浏览器环境为 `undefined`

### 2.2 DesktopAPI 类设计

**文件：** `fabrica/desktop/__init__.py`（在 [desktop_integration.md](./desktop_integration.md) 定义的模块中扩展）

DesktopAPI 类封装所有暴露给前端的桌面能力，作为 `webview.create_window(js_api=...)` 的参数传入。

```python
class DesktopAPI:
    """暴露给前端 JS 的桌面 API（通过 pywebview js_api 桥接）。

    所有方法参数和返回值必须可 JSON 序列化。
    前端通过 window.pywebview.api.<method>() 异步调用。
    """

    def open_directory_dialog(self) -> Optional[str]:
        """打开原生目录选择对话框。

        Returns:
            选中目录的完整路径，取消选择时返回 None。
        """
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def open_file_dialog(self) -> Optional[str]:
        """打开原生文件选择对话框（file 类型参数用）。

        Returns:
            选中文件的完整路径，取消选择时返回 None。
        """
        import webview
        result = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def open_in_explorer(self, path: str) -> bool:
        """在系统文件管理器中打开并选中指定文件/目录。

        Args:
            path: 文件或目录的完整路径。

        Returns:
            True 表示成功，False 表示失败。
        """
        import os
        import subprocess
        import platform
        try:
            if platform.system() == "Windows":
                # explorer /select, 选中特定文件
                if os.path.isfile(path):
                    subprocess.Popen(['explorer', '/select,', path])
                else:
                    subprocess.Popen(['explorer', path])
            elif platform.system() == "Linux":
                # xdg-open 打开所在目录
                target = os.path.dirname(path) if os.path.isfile(path) else path
                subprocess.Popen(['xdg-open', target])
            return True
        except Exception:
            return False
```

### 2.3 浏览器环境回退策略

前端 JS 调用桌面 API 前需检测环境：

```javascript
// 检测是否在 pywebview 桌面环境
const isDesktop = typeof window.pywebview !== 'undefined' && window.pywebview.api;

if (isDesktop) {
    // 桌面环境：调用原生 API
    const path = await window.pywebview.api.open_directory_dialog();
} else {
    // 浏览器开发环境：回退逻辑
    // F1: 提示手动输入路径
    // F2: 隐藏"打开文件夹"按钮
    // F3: 关键帧展示不受影响（通过 HTTP 加载图像）
}
```

| 功能 | 桌面环境（pywebview） | 浏览器开发环境 |
|------|---------------------|---------------|
| F1 目录选择 | 原生目录选择对话框 | 手动输入完整路径 |
| F2 打开文件夹 | 调用系统文件管理器 | 隐藏按钮，显示路径文本 |
| F3 关键帧展示 | HTTP 加载图像（不受影响） | HTTP 加载图像（不受影响） |

---

## 3. 功能1：目录选择器

### 3.1 需求分析

**现状问题**：
- [tool-form.js:9](../../fabrica/server/static/js/components/tool-form.js) 将 `dir` 类型映射为 `text` 输入框
- [tool-form.js:34](../../fabrica/server/static/js/components/tool-form.js) 渲染"浏览"按钮，触发隐藏的 `<input type="file">`
- [tool-form.js:84](../../fabrica/server/static/js/components/tool-form.js) `input.value.replace(/^.*[\\/]/, "")` **主动截断路径**只保留文件名
- 浏览器安全限制：`<input type="file">` 的 `value` 只返回 `C:\fakepath\filename`，无法获取完整路径

**结果**：用户无法通过"浏览"按钮正确选择目录路径，input_dir 参数始终为空或仅为文件名。

### 3.2 方案设计

**核心思路**：废弃浏览器原生 `<input type="file">`，改用 pywebview 原生文件对话框。

```
用户点击"浏览"
    │
    ├── 检测 window.pywebview.api 是否存在
    │   ├── 是（桌面环境）→ 调用 open_directory_dialog()
    │   │                   → 返回完整路径 → 填入文本框
    │   └── 否（浏览器环境）→ 聚焦文本框，提示手动输入完整路径
    │
    └── 不再使用 <input type="file">
```

### 3.3 前端改造（tool-form.js）

**修改点1**：移除隐藏的 `<input type="file">`（第41行）

当前代码：
```javascript
${isFileLike ? `<input type="file" data-key="${key}" style="display:none">` : ""}
```
改为：
```javascript
// 不再生成隐藏的 file input，改用 pywebview 原生对话框
```

**修改点2**：重写"浏览"按钮点击逻辑（第77-89行）

当前代码：
```javascript
container.querySelectorAll(".browse-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        const input = document.querySelector(`input[type="file"][data-key="${btn.dataset.key}"]`);
        if (input) {
            input.onchange = () => {
                const text = document.querySelector(`input[data-key="${btn.dataset.key}"][type="text"]`);
                if (text && input.value) text.value = input.value.replace(/^.*[\\/]/, "");
            };
            input.click();
        }
    });
});
```

改为：
```javascript
container.querySelectorAll(".browse-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
        const key = btn.dataset.key;
        const isDir = btn.dataset.dir === "true";
        const textInput = document.querySelector(
            `input[data-key="${key}"][type="text"]`
        );

        // 桌面环境：调用 pywebview 原生对话框
        if (window.pywebview && window.pywebview.api) {
            try {
                btn.disabled = true;
                btn.textContent = "选择中...";
                const path = isDir
                    ? await window.pywebview.api.open_directory_dialog()
                    : await window.pywebview.api.open_file_dialog();
                if (path && textInput) {
                    textInput.value = path;  // 完整路径，不截断
                }
            } catch (e) {
                console.error("原生对话框调用失败:", e);
            } finally {
                btn.disabled = false;
                btn.textContent = "浏览";
            }
            return;
        }

        // 浏览器环境：聚焦文本框，提示手动输入
        if (textInput) {
            textInput.focus();
            textInput.placeholder = isDir
                ? "请输入完整目录路径（如 D:\\videos）"
                : "请输入完整文件路径";
        }
    });
});
```

### 3.4 DesktopAPI 接口

见 §2.2 的 `open_directory_dialog()` 和 `open_file_dialog()` 方法。

---

## 4. 功能2：结果展示与打开文件夹

### 4.1 需求分析

**现状问题**：
- [task-progress.js:76](../../fabrica/server/static/js/components/task-progress.js) `JSON.stringify(ev.result, null, 2)` 将结果以 JSON 文本原样展示
- 结果 `final_groups` 只含视频 ID 列表 `List[List[str]]`，**不含视频路径**
- 无"打开文件夹"功能，前端无法调用系统文件管理器

**目标**：
- 验重完成后，结果区域展示重复组卡片（非 JSON 文本）
- 每个重复组列出视频路径、文件大小、时长、分辨率
- 每个视频旁有"打开文件夹"按钮，点击后系统文件管理器打开并选中该文件

### 4.2 结果数据结构改造

**文件：** `fabrica/tools/video_dedup/pipeline.py`

**当前结构**（`report["final_groups"]`）：
```python
final_groups: List[List[str]]  # 每组是视频 ID 列表
# 示例: [["vid_001", "vid_002", "vid_003"], ["vid_010", "vid_011"]]
```

**改造后结构**：
```python
final_groups: List[Dict[str, Any]]
# 每组包含视频元信息 + 判重级别
# 示例:
# [
#   {
#     "level": 2,                    # 组内最高判重级别（1=L1, 2=L2, 3=L3）
#     "videos": [
#       {
#         "id": "vid_001",
#         "path": "D:\\videos\\clip_001.mp4",
#         "size": 10485760,
#         "duration": 120.5,
#         "width": 1920,
#         "height": 1080
#       },
#       ...
#     ]
#   },
#   ...
# ]
```

**改造位置**：`CascadePipeline._cluster()` 方法末尾，在 `expand_groups()` 之后增加元信息展开逻辑。

```python
# _cluster() 方法末尾
final_groups_raw = expand_groups(uf, l1_groups)  # List[List[str]]

# 展开为包含元信息的结构
final_groups: List[Dict[str, Any]] = []
for group_ids in final_groups_raw:
    videos_info = []
    max_level = 0
    for vid in group_ids:
        v = self.storage.get_video(vid)
        if v:
            videos_info.append({
                "id": v.id,
                "path": v.path,
                "size": v.size,
                "duration": v.duration,
                "width": v.width,
                "height": v.height,
            })
    # 确定组内最高判重级别
    for i in range(len(videos_info)):
        for j in range(i + 1, len(videos_info)):
            match = self.storage.get_match(videos_info[i]["id"], videos_info[j]["id"])
            if match and match["level"] > max_level:
                max_level = match["level"]
    final_groups.append({
        "level": max_level,
        "videos": videos_info,
    })
report["final_groups"] = final_groups
```

### 4.3 存储层新增查询方法

**文件：** `fabrica/tools/video_dedup/storage.py`

VideoStorage 类需新增两个查询方法：

```python
def get_video(self, video_id: str) -> Optional[VideoRecord]:
    """根据 ID 查询单个视频元信息。

    Args:
        video_id: 视频 ID。

    Returns:
        VideoRecord 对象（含 id/path/size/duration/width/height），
        不存在时返回 None。
    """

def get_match(self, a_id: str, b_id: str) -> Optional[Dict[str, Any]]:
    """查询两个视频间的判重记录。

    Args:
        a_id: 视频 A 的 ID。
        b_id: 视频 B 的 ID。

    Returns:
        {"level": int, "score": float}，无记录时返回 None。
    """
```

### 4.4 前端结果组件（dedup-result.js）

**文件：** `fabrica/server/static/js/components/dedup-result.js`（新建）

**职责**：专门渲染视频验重结果，替代 task-progress.js 中的 JSON 文本展示。

**核心结构**：
```
┌─────────────────────────────────────────────────────────┐
│  验重结果摘要                                              │
│  共扫描 1520 个视频，发现 8 组重复（23 个视频）              │
├─────────────────────────────────────────────────────────┤
│  重复组 1  [L2 判定]                                       │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 📄 clip_001.mp4                                   │  │
│  │    D:\videos\clip_001.mp4                         │  │
│  │    10.5 MB · 2:00 · 1920×1080   [打开文件夹]       │  │
│  ├───────────────────────────────────────────────────┤  │
│  │ 📄 clip_002.mp4                                   │  │
│  │    D:\videos\sub\clip_002.mp4                     │  │
│  │    10.3 MB · 2:00 · 1920×1080   [打开文件夹]       │  │
│  ├───────────────────────────────────────────────────┤  │
│  │ 📄 clip_003.mp4                                   │  │
│  │    D:\videos\backup\clip_003.mp4                  │  │
│  │    10.5 MB · 2:00 · 1280×720    [打开文件夹]       │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  [关键帧对比 ▼]  ← 功能3，见 §5                          │
├─────────────────────────────────────────────────────────┤
│  重复组 2  [L1 判定]  ...                                 │
└─────────────────────────────────────────────────────────┘
```

**接口设计**：
```javascript
/**
 * 渲染视频验重结果。
 * @param {HTMLElement} container - 结果容器 DOM 元素
 * @param {Object} result - 工具返回的结果对象 {status, tool, report}
 */
export function renderDedupResult(container, result) {
    const report = result.report || {};
    const groups = report.final_groups || [];
    // 1. 渲染摘要
    // 2. 遍历 groups，渲染每组卡片
    // 3. 每组内遍历 videos，渲染视频项 + "打开文件夹"按钮
    // 4. 每组下方渲染关键帧网格（功能3）
}
```

**"打开文件夹"按钮逻辑**：
```javascript
btn.addEventListener("click", async () => {
    if (window.pywebview && window.pywebview.api) {
        await window.pywebview.api.open_in_explorer(video.path);
    } else {
        // 浏览器环境：复制路径到剪贴板，提示用户手动打开
        navigator.clipboard?.writeText(video.path);
        alert(`浏览器环境无法直接打开文件夹，路径已复制：\n${video.path}`);
    }
});
```

### 4.5 task-progress.js 集成

**文件：** `fabrica/server/static/js/components/task-progress.js`

**修改点**：`onComplete` 回调（第72-77行）增加工具类型判断，video_dedup 工具调用专门结果组件。

当前代码：
```javascript
onComplete: (ev) => {
    setStatus(container, "completed");
    const box = document.getElementById("result-box");
    if (box && ev.result !== undefined) {
        box.innerHTML = `<div class="result-box">${escapeHtml(JSON.stringify(ev.result, null, 2))}</div>`;
    }
    ...
}
```

改为：
```javascript
onComplete: (ev) => {
    setStatus(container, "completed");
    const box = document.getElementById("result-box");
    if (box && ev.result !== undefined) {
        if (ev.result.tool === "video_dedup") {
            // video_dedup 工具：调用专门结果组件
            import("./dedup-result.js").then(({ renderDedupResult }) => {
                renderDedupResult(box, ev.result);
            });
        } else {
            // 其他工具：保持 JSON 文本展示
            box.innerHTML = `<div class="result-box">${escapeHtml(JSON.stringify(ev.result, null, 2))}</div>`;
        }
    }
    ...
}
```

---

## 5. 功能3：关键帧展示

### 5.1 需求分析

**现状问题**：
- [sampler.py:53](../../fabrica/tools/video_dedup/sampler.py) `SampledFrame.image` 抽帧时有 PIL 图像，但计算 pHash 后即丢弃
- [storage.py:75-81](../../fabrica/tools/video_dedup/storage.py) `phash_frames` 表只存 phash 值（uint64），**不存图像**
- [storage.py:83-89](../../fabrica/tools/video_dedup/storage.py) `matches` 表只存 `(a_id, b_id, level, score)`，**不存帧级匹配信息**

**目标**：
- 展示重复组中所有视频的关键帧缩略图，按视频列排列
- 高亮判定为相同的帧对（相同颜色边框）
- 点击缩略图可放大查看

**用户确认的策略**：仅保存重复组关键帧 + 高亮匹配帧（见 §5.2 决策记录）。

### 5.2 关键帧保存策略

**核心思路**：判重完成后（`_cluster()` 之后），对 `final_groups` 中的视频**重新抽帧**并保存关键帧图像。

**为什么重新抽帧而非抽帧时保存全部**：
- 抽帧时还不知道哪些视频属于重复组，保存全部会产生大量无用图像
- 假设 5 万视频 × 100 帧 × 15KB ≈ 75GB，不可接受
- 重复组通常远少于总视频数（如 8 组 × 3 视频 = 24 个视频），重新抽帧性能可接受
- 重新抽帧使用与原始相同的采样参数，帧索引一致

**保存流程**：
```
_cluster() 完成
    │
    ├── 收集 final_groups 中所有视频 ID
    │
    ├── 对每个视频：
    │   ├── 调用 sample_frames(path) 重新抽帧
    │   ├── 保存为 JPEG: data/keyframes/{video_id}/frame_{idx:04d}.jpg
    │   └── 记录帧路径映射 {frame_idx: "/keyframes/{video_id}/frame_{idx:04d}.jpg"}
    │
    ├── 计算帧级匹配信息（利用已有 pHash 数据）
    │
    └── 将 keyframe_info 和 matched_frames 写入 report
```

**关键帧存储目录**：
```
data/
├── video_dedup/
│   └── dedup.db                    # 现有数据库
└── keyframes/                      # 新增关键帧目录
    ├── vid_001/
    │   ├── frame_0000.jpg
    │   ├── frame_0001.jpg
    │   └── ...
    ├── vid_002/
    │   └── ...
    └── vid_003/
        └── ...
```

**图像规格**：
| 项 | 值 | 说明 |
|----|-----|------|
| 格式 | JPEG | 有损压缩，体积小 |
| 质量 | 85 | 平衡质量与体积 |
| 尺寸 | 224×224 | 复用采样时已 resize 的尺寸 |
| 单帧体积 | ~15KB | 224×224 JPEG quality=85 |
| 单视频体积 | ~1.5MB | 100 帧 × 15KB |
| 重复组总体积 | ~36MB | 24 视频 × 1.5MB（典型场景） |

### 5.3 帧级匹配信息

**目标**：记录哪些帧对被判定为相同，供前端高亮显示。

**数据结构**：
```python
matched_frames: List[Dict[str, Any]]
# 每条记录表示一对匹配的帧
# 示例:
# [
#   {"a_id": "vid_001", "a_idx": 0, "b_id": "vid_002", "b_idx": 0},
#   {"a_id": "vid_001", "a_idx": 1, "b_id": "vid_002", "b_idx": 1},
#   ...
# ]
```

**计算方法**：利用已存储的 pHash 序列重新计算匹配帧对，复用 [seq_align.py](../../fabrica/tools/video_dedup/matching/seq_align.py) 的单调匹配逻辑。

```python
def _compute_matched_frames(self, final_groups: List[Dict]) -> List[Dict]:
    """计算重复组内视频间的帧级匹配信息。

    对每组内的视频两两计算，利用已存储的 pHash 序列和
    seq_align 的单调匹配逻辑找出匹配帧对。

    Args:
        final_groups: 改造后的重复组列表（含 videos 元信息）。

    Returns:
        matched_frames: 帧级匹配记录列表。
    """
    import numpy as np
    from fabrica.tools.video_dedup.matching.seq_align import _monotonic_hits

    matched = []
    frame_thresh = ...  # 从配置读取，与 L2 判重一致

    for group in final_groups:
        videos = group["videos"]
        # 两两计算匹配帧对
        for i in range(len(videos)):
            for j in range(i + 1, len(videos)):
                a, b = videos[i], videos[j]
                seq_a = self.storage.load_phash(a["id"])  # 已有方法
                seq_b = self.storage.load_phash(b["id"])
                if seq_a is None or seq_b is None:
                    continue

                # 计算全量汉明距离矩阵，找出单调匹配帧对
                arr_a = np.asarray(seq_a).astype(np.uint64)
                arr_b = np.asarray(seq_b).astype(np.uint64)
                if arr_a.size > arr_b.size:
                    short, long = arr_b, arr_a
                    swapped = True
                else:
                    short, long = arr_a, arr_b
                    swapped = False

                dists = np.bitwise_count(short[:, None] ^ long[None, :])

                # 遍历距离矩阵，找出所有命中对（≤ frame_thresh）
                n_short, n_long = dists.shape
                long_ptr = 0
                for si in range(n_short):
                    for li in range(long_ptr, n_long):
                        if int(dists[si, li]) <= frame_thresh:
                            # 还原原始 (a_idx, b_idx)
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
```

### 5.4 关键帧图像服务

**文件：** `fabrica/server/__init__.py`

通过 FastAPI StaticFiles 挂载关键帧目录，提供 HTTP 访问。

```python
# 在 create_app() 中，现有 /static 挂载之后增加
import os
from fastapi.staticfiles import StaticFiles
from fabrica.utils.config import get_config

# 关键帧图像目录（与数据库同级）
db_path = get_config("fabrica.storage.db_path") or "data/video_dedup/dedup.db"
kf_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "keyframes")
os.makedirs(kf_dir, exist_ok=True)
app.mount("/keyframes", StaticFiles(directory=kf_dir), name="keyframes")
```

前端通过以下 URL 访问关键帧图像：
```
http://127.0.0.1:8520/keyframes/{video_id}/frame_{idx:04d}.jpg
```

### 5.5 前端关键帧网格组件

**文件：** `fabrica/server/static/js/components/dedup-result.js`（在 §4.4 的组件中扩展）

**展示逻辑**：
```
重复组卡片
├── 视频列表（路径+元信息+打开文件夹按钮）
└── 关键帧对比区域
    ├── 视频A列：frame_0000 | frame_0001 | frame_0002 | ...
    ├── 视频B列：frame_0000 | frame_0001 | frame_0002 | ...
    └── 视频C列：frame_0000 | frame_0001 | frame_0002 | ...

    匹配的帧对用相同颜色边框高亮：
    ┌────┐ ┌────┐ ┌────┐
    │ A0 │ │ A1 │ │ A2 │   ← 蓝色边框（匹配帧）
    └────┘ └────┘ └────┘
    ┌────┐ ┌────┐ ┌────┐
    │ B0 │ │ B1 │ │ B2 │   ← 蓝色边框（匹配帧）
    └────┘ └────┘ └────┘
```

**渲染函数**：
```javascript
/**
 * 渲染关键帧对比网格。
 * @param {Object} group - 重复组数据
 * @param {Object} keyframeInfo - {video_id: {frame_idx: image_url}}
 * @param {Array} matchedFrames - 帧级匹配记录
 */
function renderKeyframeGrid(group, keyframeInfo, matchedFrames) {
    const videos = group.videos;

    // 构建匹配帧对的查找索引
    // matchedPairs[video_id] = Set(matched_frame_indices)
    const matchedPairs = {};
    matchedFrames.forEach(m => {
        if (!matchedPairs[m.a_id]) matchedPairs[m.a_id] = new Set();
        if (!matchedPairs[m.b_id]) matchedPairs[m.b_id] = new Set();
        matchedPairs[m.a_id].add(m.a_idx);
        matchedPairs[m.b_id].add(m.b_idx);
    });

    // 按视频列渲染关键帧
    // 每列一个视频，每行一个帧
    // 匹配帧的 <img> 加 class "matched-frame"（CSS 高亮边框）
    // 点击缩略图弹出大图查看
}
```

**关键帧网格 CSS**：
```css
.keyframe-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 8px;
    margin-top: 12px;
}
.keyframe-cell {
    text-align: center;
}
.keyframe-cell img {
    width: 100%;
    height: auto;
    border-radius: 4px;
    cursor: pointer;
    border: 2px solid transparent;
    transition: border-color 0.2s;
}
.keyframe-cell img.matched-frame {
    border-color: #2196F3;  /* 蓝色高亮匹配帧 */
}
.keyframe-cell img:hover {
    border-color: #FF9800;  /* 悬停橙色 */
}
```

### 5.6 结果数据结构总览

改造后，`run_pipeline()` 返回的 `report` 完整结构：

```python
report = {
    "cancelled": False,
    "total_videos": 1520,
    "l1_groups": [...],          # L1 哈希分组（不变）
    "l2_pairs": [...],           # L2 判重对（不变）
    "l3_pairs": [...],           # L3 判重对（不变）
    "final_groups": [            # ← 改造：含视频元信息
        {
            "level": 2,
            "videos": [
                {"id": "vid_001", "path": "...", "size": ..., "duration": ..., "width": ..., "height": ...},
                ...
            ]
        },
        ...
    ],
    "keyframes": {               # ← 新增：关键帧图像 URL 映射
        "vid_001": {0: "/keyframes/vid_001/frame_0000.jpg", 1: "...", ...},
        "vid_002": {0: "/keyframes/vid_002/frame_0000.jpg", 1: "...", ...},
        ...
    },
    "matched_frames": [          # ← 新增：帧级匹配信息
        {"a_id": "vid_001", "a_idx": 0, "b_id": "vid_002", "b_idx": 0},
        ...
    ],
    "errors": [...],             # 错误记录（不变）
}
```

---

## 6. 文件修改清单

| 文件 | 操作 | 涉及功能 | 说明 |
|------|------|---------|------|
| `fabrica/desktop/__init__.py` | 新建/扩展 | 前置+F1+F2 | DesktopAPI 类（open_directory_dialog / open_file_dialog / open_in_explorer） |
| `fabrica/server/static/js/components/tool-form.js` | 修改 | F1 | 浏览按钮逻辑改造（pywebview 原生对话框 + 浏览器回退） |
| `fabrica/tools/video_dedup/pipeline.py` | 修改 | F2+F3 | final_groups 结构改造 + _save_keyframes + _compute_matched_frames |
| `fabrica/tools/video_dedup/storage.py` | 修改 | F2+F3 | 新增 get_video() / get_match() 方法 |
| `fabrica/server/__init__.py` | 修改 | F3 | 挂载 /keyframes 静态文件目录 |
| `fabrica/server/static/js/components/dedup-result.js` | 新建 | F2+F3 | 验重结果组件（重复组卡片 + 打开文件夹 + 关键帧网格） |
| `fabrica/server/static/js/components/task-progress.js` | 修改 | F2 | onComplete 检测工具类型，调用 dedup-result.js |
| `fabrica/server/static/css/style.css` | 修改 | F2+F3 | 重复组卡片、关键帧网格、高亮边框样式 |

---

## 7. 设计决策记录（DDR）

### 7.1 为什么用 pywebview JS API 而非浏览器原生 file input

**问题**：目录选择应当使用浏览器原生 `<input type="file" webkitdirectory>` 还是 pywebview 原生对话框？

**决策**：**pywebview JS API**。

**原因**：
1. 浏览器安全限制：`<input type="file">` 的 `value` 只返回 `C:\fakepath\filename`，**无法获取完整文件系统路径**，而 video_dedup 工具需要完整路径来扫描目录
2. `webkitdirectory` 属性虽可选择目录，但仍只返回目录内文件的相对路径，不返回目录本身的完整路径
3. pywebview `create_file_dialog(FOLDER_DIALOG)` 调用系统原生对话框，返回完整路径
4. 当前代码 [tool-form.js:84](../../fabrica/server/static/js/components/tool-form.js) 的 `replace(/^.*[\\/]/, "")` 正是为了规避浏览器限制而截断路径，但这导致 input_dir 始终不正确

### 7.2 为什么 final_groups 改为包含视频元信息

**问题**：结果中的 `final_groups` 应当只含视频 ID（前端再查询）还是直接包含元信息？

**决策**：**直接包含元信息**（path/size/duration/width/height）。

**原因**：
1. 前端展示需要视频路径，若只含 ID 则前端需额外发 HTTP 请求查询，增加复杂度
2. 任务结果通过 WebSocket `complete` 事件一次性推送，包含完整信息更符合事件驱动模型
3. 重复组通常只有几组、每组几个视频，元信息数据量小，不影响传输性能
4. 工具的 `run()` 返回值是任意 dict，结构改造不影响平台层

### 7.3 为什么关键帧判重后重新抽帧而非抽帧时保存

**问题**：关键帧图像应当在抽帧阶段就保存，还是判重后对重复组重新抽帧？

**决策**：**判重后对重复组重新抽帧**。

**原因**：
1. 抽帧时还不知道哪些视频属于重复组，保存全部会产生大量无用图像
2. 假设 5 万视频 × 100 帧 × 15KB ≈ 75GB，磁盘占用不可接受
3. 重复组通常远少于总视频数（典型场景 24 个视频），重新抽帧仅需解码 24 个视频，性能可接受（每个视频 ~2 秒，总计 ~48 秒）
4. 重新抽帧使用与原始相同的采样参数（`compute_sample_timestamps`），帧索引一致，匹配信息有效
5. 避免修改抽帧流程的核心逻辑（sampler.py），降低回归风险

### 7.4 为什么帧级匹配信息利用已有 pHash 重新计算

**问题**：帧级匹配信息应当在 L2 判重时记录，还是判重后重新计算？

**决策**：**判重后利用已存储的 pHash 序列重新计算**。

**原因**：
1. L2 判重时的 `_monotonic_hits` 只返回命中数（int），不返回具体帧对，修改返回值会影响判重逻辑
2. pHash 序列已持久化在 `phash_frames` 表中，重新计算无需重新抽帧
3. 重新计算逻辑与 [seq_align.py](../../fabrica/tools/video_dedup/matching/seq_align.py) 的单调匹配一致，结果可复现
4. 仅对重复组内视频两两计算（通常每组 2-3 个视频），计算量极小

### 7.5 为什么关键帧通过 StaticFiles 而非专用 API 提供

**问题**：关键帧图像应当通过 StaticFiles 静态服务还是专用 API 端点提供？

**决策**：**StaticFiles 静态服务**。

**原因**：
1. 关键帧是纯静态 JPEG 文件，无需动态生成或权限校验
2. StaticFiles 性能优于 API 端点（直接由 ASGI 服务器处理，无 Python 函数调用开销）
3. 前端可直接用 `<img src="/keyframes/{vid}/frame_0000.jpg">` 加载，无需 JS 拼接
4. 现有 `/static` 已通过 StaticFiles 挂载，模式一致

### 7.6 为什么浏览器环境隐藏"打开文件夹"按钮而非报错

**问题**：浏览器环境下"打开文件夹"功能应当如何处理？

**决策**：**隐藏按钮或提示路径已复制**。

**原因**：
1. 浏览器环境无法调用系统文件管理器（安全限制）
2. 直接报错会打断用户体验
3. 保留按钮但改为"复制路径"功能，用户可手动粘贴到文件管理器
4. 桌面环境（生产）才是主要使用场景，浏览器仅用于开发调试

---

## 8. 与实现步骤的对应关系

本设计文档对应的实现任务见 [implementation_steps.md](../product/implementation_steps.md) 中的新增任务项：

| 设计文档章节 | 对应实现任务 |
|-------------|-------------|
| §2.2 DesktopAPI 类 | 前置：桌面窗口基础实现 |
| §3 目录选择器 | T6.1 目录选择器（pywebview 原生对话框） |
| §4 结果展示+打开文件夹 | T6.2 验重结果结构化展示 + 打开文件夹 |
| §5 关键帧展示 | T6.3 关键帧保存与展示 |

---

**文档结束**
