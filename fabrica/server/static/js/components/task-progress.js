/**
 * 任务进度组件
 * 渲染进度条 + 日志流，通过 WebSocket 实时更新。
 */

import { api } from "../api.js";
import { FabricaWS } from "../ws.js";

const STATUS_BADGE = {
    pending: "warning", validating: "warning", valid: "warning", running: "warning",
    completed: "success", failed: "danger", cancelled: "danger", invalid: "danger",
};

export async function renderTaskProgress(container, taskId) {
    container.innerHTML = `<div class="empty-tip">加载中...</div>`;
    let detail;
    try {
        detail = await api.get(`/tasks/${encodeURIComponent(taskId)}`);
    } catch (err) {
        container.innerHTML = `<div class="error-tip">${escapeHtml(err.message)}</div>`;
        return;
    }

    container.innerHTML = `
        <h1 class="page-title">任务详情</h1>
        <div class="form-card">
            <div class="row">
                <span class="muted">任务 ID</span>
                <code>${escapeHtml(detail.task_id)}</code>
                <span class="spacer"></span>
                <span class="badge ${STATUS_BADGE[detail.status] || ""}" id="task-status">${escapeHtml(detail.status)}</span>
            </div>
            <div class="row" style="margin-top:8px">
                <span class="muted">工具</span>
                <span>${escapeHtml(detail.tool_name)}</span>
            </div>
            <div class="progress-wrap">
                <div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:${detail.progress || 0}%"></div></div>
                <div class="progress-text" id="progress-text">${detail.progress || 0}%</div>
            </div>
            <div class="row">
                <button class="btn btn-danger" id="cancel-btn">取消任务</button>
                <a class="btn btn-secondary" href="#/tasks">返回</a>
            </div>
            <div id="result-box"></div>
            <div class="log-stream" id="log-stream"></div>
        </div>`;

    // 渲染已有日志
    (detail.logs || []).forEach((log) => appendLog(container, log));

    const cancelBtn = document.getElementById("cancel-btn");
    cancelBtn?.addEventListener("click", async () => {
        cancelBtn.disabled = true;
        try {
            await api.post(`/tasks/${encodeURIComponent(taskId)}/cancel`);
        } catch (err) {
            cancelBtn.disabled = false;
            alert(`取消失败: ${err.message}`);
        }
    });

    // 连接 WebSocket 实时推送
    const ws = new FabricaWS(`/api/ws/tasks/${encodeURIComponent(taskId)}`, {
        onProgress: (ev) => {
            const fill = document.getElementById("progress-fill");
            const text = document.getElementById("progress-text");
            if (fill) fill.style.width = `${ev.percent}%`;
            if (text) text.textContent = `${ev.percent}% ${ev.message || ""}`;
        },
        onLog: (ev) => appendLog(container, { level: ev.level, message: ev.message, timestamp: new Date().toISOString() }),
        onComplete: (ev) => {
            setStatus(container, "completed");
            const box = document.getElementById("result-box");
            if (box && ev.result !== undefined) {
                box.innerHTML = `<div class="result-box">${escapeHtml(JSON.stringify(ev.result, null, 2))}</div>`;
            }
            const fill = document.getElementById("progress-fill");
            if (fill) fill.style.width = "100%";
            ws.close();
        },
        onError: (ev) => {
            setStatus(container, "failed");
            const box = document.getElementById("result-box");
            if (box) box.innerHTML = `<div class="error-tip">${escapeHtml(ev.error || "执行失败")}</div>`;
            ws.close();
        },
        onClose: () => {
            const text = document.getElementById("progress-text");
            if (text) text.textContent = `${text.textContent}（已断开）`;
        },
    });
    ws.connect();

    // 心跳
    const pingTimer = setInterval(() => ws.sendPing(), 15000);
    container._pingTimer = pingTimer;
}

function setStatus(container, status) {
    const el = document.getElementById("task-status");
    if (el) {
        el.className = `badge ${STATUS_BADGE[status] || ""}`;
        el.textContent = status;
    }
}

function appendLog(container, log) {
    const stream = document.getElementById("log-stream");
    if (!stream) return;
    const line = document.createElement("div");
    line.className = "log-line";
    const ts = log && log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "";
    line.innerHTML = `${ts ? `<span class="ts">${escapeHtml(ts)}</span>` : ""}${escapeHtml(log.message || "")}`;
    stream.appendChild(line);
    stream.scrollTop = stream.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = String(text ?? "");
    return div.innerHTML;
}

export default renderTaskProgress;