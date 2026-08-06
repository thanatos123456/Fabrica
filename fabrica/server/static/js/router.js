/**
 * Fabrica SPA Hash 路由
 * 支持 5 条路由：/、/tool/{name}、/tool/{name}/run、/tasks、/tasks/{id}
 * 监听 hashchange，惰性加载对应组件渲染函数。
 */

const ROUTES = [
    { pattern: /^\/tool\/([^/?]+)\/run$/, handler: async (app, m, q) => {
        const mod = await import("./components/task-progress.js");
        const taskId = q.get("task");
        if (!taskId) {
            app.innerHTML = `<div class="error-tip">缺少任务 ID</div>`;
            return;
        }
        await mod.renderTaskProgress(app, taskId);
    }},
    { pattern: /^\/tool\/([^/?]+)$/, handler: async (app, m, _q) => {
        const mod = await import("./components/tool-form.js");
        await mod.renderToolForm(app, m[1]);
    }},
    { pattern: /^\/tasks\/([^/?]+)$/, handler: async (app, m, _q) => {
        const mod = await import("./components/task-progress.js");
        await mod.renderTaskProgress(app, m[1]);
    }},
    { pattern: /^\/tasks$/, handler: async (app, _m, _q) => {
        const mod = await import("./components/task-history.js");
        await mod.renderTaskHistory(app);
    }},
    { pattern: /^\/$/, handler: async (app, _m, _q) => {
        const mod = await import("./components/tool-card.js");
        await mod.renderTools(app);
    }},
];

/** 解析当前 hash，返回 { path, query }。 */
function parse() {
    const raw = location.hash.replace(/^#/, "") || "/";
    const qIndex = raw.indexOf("?");
    const path = qIndex >= 0 ? raw.slice(0, qIndex) : raw;
    const query = new URLSearchParams(qIndex >= 0 ? raw.slice(qIndex + 1) : "");
    return { path: path || "/", query };
}

/** 跳转到指定 hash 路由。 */
function navigate(path) {
    location.hash = path;
}

function init() {
    window.addEventListener("hashchange", render);
    render();
}

async function render() {
    const app = document.getElementById("app");
    if (!app) return;
    const { path, query } = parse();
    for (const route of ROUTES) {
        const m = path.match(route.pattern);
        if (m) {
            try {
                await route.handler(app, m, query);
            } catch (err) {
                app.innerHTML = `<div class="error-tip">${escapeHtml(err.message)}</div>`;
            }
            return;
        }
    }
    app.innerHTML = `<div class="empty-tip">404 - 页面不存在</div>`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
}

export const Router = { init, render, navigate, parse };
export default Router;