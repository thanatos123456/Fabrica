/**
 * 视频验重结果渲染组件（T6.2 + T6.3）
 * 将 final_groups 渲染为结构化卡片，支持一键打开文件夹 + 关键帧网格。
 */

const LEVEL_LABEL = { 1: "L1 文件哈希", 2: "L2 pHash 序列", 3: "L3 深度特征" };

/**
 * 渲染验重结果到容器。
 * @param {HTMLElement} container - 结果区域 DOM 元素
 * @param {Object} report - 验重报告
 */
export function renderDedupResult(container, report) {
    const groups = report?.final_groups || [];
    const totalVideos = report?.total_videos || 0;
    const keyframes = report?.keyframes || {};
    const matchedFrames = report?.matched_frames || [];
    const dupVideoCount = groups.reduce(
        (sum, g) => sum + g.videos.length, 0
    );

    if (groups.length === 0) {
        container.innerHTML = `
            <div class="dedup-summary">
                <span>共 ${totalVideos} 个视频，未发现重复</span>
            </div>`;
        return;
    }

    const groupCards = groups.map((group, idx) => {
        const levelText = LEVEL_LABEL[group.level] || `L${group.level}`;
        const videoRows = group.videos.map((v) => {
            const filename = v.path.split(/[\\/]/).pop() || v.path;
            return `
                <div class="dedup-video-item">
                    <div class="dedup-video-path" title="${escapeHtml(v.path)}">
                        ${escapeHtml(filename)}
                    </div>
                    <div class="dedup-video-meta">
                        <span>${formatSize(v.size)}</span>
                        <span>${formatDuration(v.duration)}</span>
                        <span>${formatResolution(v.width, v.height)}</span>
                    </div>
                    <button class="btn btn-sm btn-secondary dedup-open-btn"
                            data-path="${escapeHtml(v.path)}">打开文件夹</button>
                </div>`;
        }).join("");

        // T6.3: 关键帧网格
        const keyframeSection = renderKeyframeSection(
            group, keyframes, matchedFrames
        );

        return `
            <div class="dedup-group">
                <div class="dedup-group-header">
                    <span class="level-badge level-${group.level}">${escapeHtml(levelText)}</span>
                    <span class="muted">第 ${idx + 1} 组 · ${group.videos.length} 个视频</span>
                </div>
                ${videoRows}
                ${keyframeSection}
            </div>`;
    }).join("");

    container.innerHTML = `
        <div class="dedup-summary">
            <span>共 ${totalVideos} 个视频，发现 ${groups.length} 组重复（${dupVideoCount} 个视频）</span>
        </div>
        ${groupCards}`;

    // 绑定"打开文件夹"按钮
    container.querySelectorAll(".dedup-open-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const path = btn.dataset.path;
            if (window.pywebview && window.pywebview.api) {
                try {
                    btn.disabled = true;
                    await window.pywebview.api.open_in_explorer(path);
                } catch (e) {
                    console.error("打开文件夹失败:", e);
                } finally {
                    btn.disabled = false;
                }
            } else {
                try {
                    await navigator.clipboard.writeText(path);
                    btn.textContent = "已复制路径";
                    setTimeout(() => { btn.textContent = "打开文件夹"; }, 2000);
                } catch {
                    alert("无法访问剪贴板，请手动复制路径:\n" + path);
                }
            }
        });
    });

    // T6.3: 绑定关键帧缩略图点击（lightbox）
    container.querySelectorAll(".kf-thumb").forEach((img) => {
        img.addEventListener("click", () => openLightbox(img.src));
    });
}

// ---- T6.3: 关键帧网格 ----

function renderKeyframeSection(group, keyframes, matchedFrames) {
    const videos = group.videos;
    // 检查是否有关键帧数据
    const hasKeyframes = videos.some((v) => keyframes[v.id]);
    if (!hasKeyframes) return "";

    // 构建匹配帧索引：matchedSet[video_id] = Set(matched_frame_indices)
    const matchedSet = {};
    matchedFrames.forEach((m) => {
        if (!matchedSet[m.a_id]) matchedSet[m.a_id] = new Set();
        if (!matchedSet[m.b_id]) matchedSet[m.b_id] = new Set();
        matchedSet[m.a_id].add(m.a_idx);
        matchedSet[m.b_id].add(m.b_idx);
    });

    const columns = videos.map((v) => {
        const kfMap = keyframes[v.id];
        if (!kfMap) {
            return `<div class="keyframe-column"><div class="muted">无关键帧</div></div>`;
        }
        const filename = v.path.split(/[\\/]/).pop() || v.path;
        const matched = matchedSet[v.id] || new Set();
        const indices = Object.keys(kfMap).map(Number).sort((a, b) => a - b);
        const thumbs = indices.map((idx) => {
            const url = kfMap[idx];
            const cls = matched.has(idx) ? "kf-thumb matched-frame" : "kf-thumb";
            return `<img class="${cls}" src="${escapeHtml(url)}" alt="frame ${idx}" loading="lazy">`;
        }).join("");
        return `
            <div class="keyframe-column">
                <div class="keyframe-col-label" title="${escapeHtml(v.path)}">${escapeHtml(filename)}</div>
                ${thumbs}
            </div>`;
    }).join("");

    return `
        <div class="keyframe-section">
            <div class="keyframe-section-header">关键帧对比（蓝色边框为匹配帧）</div>
            <div class="keyframe-grid">${columns}</div>
        </div>`;
}

function openLightbox(src) {
    const overlay = document.createElement("div");
    overlay.className = "keyframe-lightbox";
    overlay.innerHTML = `<img src="${escapeHtml(src)}" alt="放大查看">`;
    overlay.addEventListener("click", () => overlay.remove());
    document.body.appendChild(overlay);
}

// ---- 格式化辅助 ----

function formatSize(bytes) {
    if (!bytes || bytes <= 0) return "-";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let val = bytes;
    let i = 0;
    while (val >= 1024 && i < units.length - 1) {
        val /= 1024;
        i++;
    }
    return `${val.toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return "-";
    const s = Math.floor(seconds % 60);
    const m = Math.floor((seconds / 60) % 60);
    const h = Math.floor(seconds / 3600);
    if (h > 0) {
        return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }
    return `${m}:${String(s).padStart(2, "0")}`;
}

function formatResolution(w, h) {
    if (!w || !h) return "-";
    return `${w}×${h}`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = String(text ?? "");
    return div.innerHTML;
}

export default renderDedupResult;
