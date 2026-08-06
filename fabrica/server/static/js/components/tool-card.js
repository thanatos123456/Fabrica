/**
 * 工具卡片组件
 * 渲染工具列表（GET /api/tools），点击跳转到工具详情页。
 */

import { api } from "../api.js";

export async function renderTools(container) {
    container.innerHTML = `<div class="empty-tip">加载中...</div>`;
    let tools;
    try {
        tools = await api.get("/tools");
    } catch (err) {
        container.innerHTML = `<div class="error-tip">${escapeHtml(err.message)}</div>`;
        return;
    }
    if (!tools || tools.length === 0) {
        container.innerHTML = `
            <h1 class="page-title">工具列表</h1>
            <div class="empty-tip">暂无已注册工具</div>`;
        return;
    }
    const cards = tools.map((t) => `
        <a class="tool-card" href="#/tool/${encodeURIComponent(t.name)}">
            <div class="tool-icon">${escapeHtml(t.icon || "🧰")}</div>
            <div class="tool-title">${escapeHtml(t.title || t.name)}</div>
            <div class="tool-desc">${escapeHtml(t.description || "")}</div>
            <div class="tool-meta">${escapeHtml(t.name)} · v${escapeHtml(t.version || "0.1.0")}</div>
        </a>`).join("");
    container.innerHTML = `
        <h1 class="page-title">工具列表</h1>
        <div class="tool-grid">${cards}</div>`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
}

export default renderTools;