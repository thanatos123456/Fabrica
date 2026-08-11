/**
 * 工具参数表单组件
 * 根据 ParamDefSchema 动态渲染 10 种控件类型，提交后创建任务并跳转执行页。
 */

import { api } from "../api.js";
import Router from "../router.js";

const INPUT_TYPES = { str: "text", int: "number", float: "number", password: "password", path: "text", file: "text", dir: "text" };

/** 渲染单个控件的输入区。 */
function renderControl(def) {
    const { type, key, placeholder, default: dflt, options } = def;
    const ph = placeholder || "";

    if (type === "bool") {
        return `<input type="checkbox" class="form-control" data-key="${key}" data-type="bool" id="f-${key}" ${dflt ? "checked" : ""}>`;
    }
    if (type === "select") {
        const opts = (options || []).map((o) =>
            `<option value="${escapeHtml(String(o))}" ${String(o) === String(dflt) ? "selected" : ""}>${escapeHtml(String(o))}</option>`).join("");
        return `<select class="form-control" data-key="${key}" data-type="select" id="f-${key}">${opts}</select>`;
    }
    if (type === "multi_select") {
        const opts = (options || []).map((o) =>
            `<option value="${escapeHtml(String(o))}">${escapeHtml(String(o))}</option>`).join("");
        return `<select multiple class="form-control" data-key="${key}" data-type="multi_select" id="f-${key}" style="height:auto;min-height:80px">${opts}</select>`;
    }

    const inputType = INPUT_TYPES[type] || "text";
    const step = type === "int" ? 'step="1"' : type === "float" ? 'step="any"' : "";
    const isFileLike = type === "file" || type === "dir";
    const browse = isFileLike
        ? `<button type="button" class="btn btn-secondary browse-btn" data-key="${key}" data-dir="${type === "dir"}">浏览</button>`
        : "";
    return `
        <div class="row">
            <input type="${inputType}" ${step} class="form-control" data-key="${key}" data-type="${type}"
                id="f-${key}" placeholder="${escapeHtml(ph)}" value="${dflt !== null && dflt !== undefined ? escapeHtml(String(dflt)) : ""}">
            ${browse}
        </div>`;
}

export async function renderToolForm(container, name) {
    container.innerHTML = `<div class="empty-tip">加载中...</div>`;
    let tool;
    try {
        tool = await api.get(`/tools/${encodeURIComponent(name)}`);
    } catch (err) {
        container.innerHTML = `<div class="error-tip">${escapeHtml(err.message)}</div>`;
        return;
    }
    const params = tool.params || [];
    const fields = params.map((def) => `
        <div class="form-group">
            <label class="form-label" for="f-${def.key}">
                ${escapeHtml(def.label || def.key)} ${def.required ? '<span class="req">*</span>' : ""}
            </label>
            ${renderControl(def)}
            ${def.description ? `<div class="form-desc">${escapeHtml(def.description)}</div>` : ""}
        </div>`).join("");

    container.innerHTML = `
        <h1 class="page-title">${escapeHtml(tool.title || tool.name)}</h1>
        <p class="page-desc">${escapeHtml(tool.description || "")}</p>
        <div class="form-card">
            <form id="tool-form">
                ${fields || '<div class="muted">该工具无需参数。</div>'}
                <div class="row">
                    <button type="submit" class="btn" id="run-btn">运行</button>
                    <a class="btn btn-secondary" href="#/">返回</a>
                </div>
            </form>
        </div>`;

    // 文件/目录选择器：pywebview 原生对话框 + 浏览器回退
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

    container.querySelector("#tool-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const runBtn = document.getElementById("run-btn");
        runBtn.disabled = true;
        runBtn.textContent = "提交中...";
        try {
            const p = collectParams(container, params);
            const res = await api.post(`/tools/${encodeURIComponent(name)}/run`, { params: p });
            Router.navigate(`#/tool/${encodeURIComponent(name)}/run?task=${encodeURIComponent(res.task_id)}`);
        } catch (err) {
            runBtn.disabled = false;
            runBtn.textContent = "运行";
            const tip = document.createElement("div");
            tip.className = "error-tip";
            tip.textContent = err.message;
            container.querySelector(".form-card").appendChild(tip);
        }
    });
}

/** 收集控件值并按类型转换。 */
function collectParams(container, defs) {
    const result = {};
    for (const def of defs) {
        const el = document.getElementById(`f-${def.key}`);
        if (!el) continue;
        const type = def.type;
        if (type === "bool") {
            result[def.key] = el.checked;
        } else if (type === "int") {
            result[def.key] = el.value === "" ? null : parseInt(el.value, 10);
        } else if (type === "float") {
            result[def.key] = el.value === "" ? null : parseFloat(el.value);
        } else if (type === "multi_select") {
            result[def.key] = Array.from(el.selectedOptions).map((o) => o.value);
        } else {
            result[def.key] = el.value;
        }
    }
    return result;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = String(text ?? "");
    return div.innerHTML;
}

export default renderToolForm;