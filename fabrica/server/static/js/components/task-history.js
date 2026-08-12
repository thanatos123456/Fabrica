/**
 * 任务历史组件
 * 渲染任务列表表格（GET /api/tasks），支持取消/删除与跳转详情。
 */

import { api } from "../api.js";

const STATUS_BADGE = {
    pending: "warning", validating: "warning", valid: "warning", running: "warning",
    completed: "success", failed: "danger", cancelled: "danger", invalid: "danger",
};

export async function renderTaskHistory(container) {
    container.innerHTML = `<div class="empty-tip">加载中...</div>`;
    let tasks;
    try {
        tasks = await api.get("/tasks");
    } catch (err) {
        container.innerHTML = `<div class="error-tip">${escapeHtml(err.message)}</div>`;
        return;
    }

    const header = `
        <div class="row" style="justify-content:space-between;align-items:center;">
            <h1 class="page-title" style="margin:0;">任务历史</h1>
            <button class="btn btn-secondary" id="cleanup-btn">清理残留</button>
        </div>`;

    let body;
    if (!tasks || tasks.length === 0) {
        body = `<div class="empty-tip">暂无任务记录</div>`;
    } else {
        const rows = tasks.map((t) => {
            const canCancel = ["pending", "validating", "valid", "running"].includes(t.status);
            return `
            <tr data-id="${escapeHtml(t.task_id)}">
                <td><a href="#/tasks/${encodeURIComponent(t.task_id)}"><code>${escapeHtml(t.task_id.slice(0, 8))}</code></a></td>
                <td>${escapeHtml(t.tool_name)}</td>
                <td><span class="badge ${STATUS_BADGE[t.status] || ""}">${escapeHtml(t.status)}</span></td>
                <td>${t.progress || 0}%</td>
                <td>${escapeHtml(t.created_at ? new Date(t.created_at).toLocaleString() : "")}</td>
                <td>
                    <div class="row">
                        ${canCancel ? `<button class="btn btn-secondary btn-sm cancel-btn" data-id="${escapeHtml(t.task_id)}">取消</button>` : ""}
                        <button class="btn btn-danger btn-sm delete-btn" data-id="${escapeHtml(t.task_id)}">删除</button>
                    </div>
                </td>
            </tr>`;
        }).join("");
        body = `
            <table class="table">
                <thead><tr>
                    <th>任务 ID</th><th>工具</th><th>状态</th><th>进度</th><th>创建时间</th><th>操作</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    }
    container.innerHTML = header + body;

    // 全局清理入口：清理不再被任何任务引用的中间产物
    const cleanupBtn = container.querySelector("#cleanup-btn");
    cleanupBtn.addEventListener("click", async () => {
        if (!confirm("将清理不再被任何任务引用的关键帧与特征文件，确认继续？")) return;
        cleanupBtn.disabled = true;
        try {
            const res = await api.post("/tasks/cleanup");
            const c = (res && res.cleaned) || {};
            alert(`已清理：关键帧 ${c.keyframes || 0}，深度特征 ${c.features || 0}，输出报告 ${c.output || 0}`);
        } catch (err) {
            alert(`清理失败: ${err.message}`);
        } finally {
            cleanupBtn.disabled = false;
        }
    });

    container.querySelectorAll(".cancel-btn").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            btn.disabled = true;
            try {
                await api.post(`/tasks/${encodeURIComponent(btn.dataset.id)}/cancel`);
                await renderTaskHistory(container);
            } catch (err) {
                btn.disabled = false;
                alert(`取消失败: ${err.message}`);
            }
        });
    });
    container.querySelectorAll(".delete-btn").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            if (!confirm("确定删除该任务记录？")) return;
            btn.disabled = true;
            try {
                await api.del(`/tasks/${encodeURIComponent(btn.dataset.id)}`);
                await renderTaskHistory(container);
            } catch (err) {
                btn.disabled = false;
                alert(`删除失败: ${err.message}`);
            }
        });
    });
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = String(text ?? "");
    return div.innerHTML;
}

export default renderTaskHistory;