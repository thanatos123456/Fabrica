/**
 * Fabrica HTTP API 客户端
 * 使用 fetch + async/await 封装 REST 调用。
 */

const API_BASE = "/api";

async function _request(method, path, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    let res;
    try {
        res = await fetch(API_BASE + path, options);
    } catch (err) {
        throw new Error(`网络错误: ${err.message}`);
    }
    if (!res.ok) {
        let message = `请求失败 (${res.status})`;
        try {
            const data = await res.json();
            if (data && data.message) message = data.message;
        } catch (_) {
            /* 忽略解析失败 */
        }
        const error = new Error(message);
        error.status = res.status;
        error.code = null;
        try {
            const data = await res.json().catch(() => null);
            if (data && data.error_code) error.code = data.error_code;
        } catch (_) { /* ignore */ }
        throw error;
    }
    if (res.status === 204) return null;
    return res.json();
}

export const api = {
    get: (path) => _request("GET", path),
    post: (path, body) => _request("POST", path, body),
    del: (path) => _request("DELETE", path),
};

export default api;