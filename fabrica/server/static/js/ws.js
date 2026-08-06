/**
 * Fabrica WebSocket 客户端封装
 * 连接任务实时推送端点，按事件类型分发到回调。
 */

export class FabricaWS {
    /**
     * @param {string} url WebSocket 地址（如 "/api/ws/tasks/xxx"）
     * @param {object} handlers 事件处理器：onProgress/onLog/onComplete/onError/onClose
     */
    constructor(url, handlers = {}) {
        this.url = url;
        this.handlers = handlers;
        this.ws = null;
        this.closed = false;
    }

    connect() {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        this.ws = new WebSocket(`${proto}://${location.host}${this.url}`);
        this.ws.onmessage = (ev) => this._dispatch(ev.data);
        this.ws.onclose = () => {
            this.closed = true;
            if (this.handlers.onClose) this.handlers.onClose();
        };
        this.ws.onerror = () => {
            /* 错误由 onclose 统一处理 */
        };
    }

    _dispatch(raw) {
        let data;
        try {
            data = JSON.parse(raw);
        } catch (_) {
            return;
        }
        switch (data.type) {
            case "progress":
                if (this.handlers.onProgress) this.handlers.onProgress(data);
                break;
            case "log":
                if (this.handlers.onLog) this.handlers.onLog(data);
                break;
            case "complete":
                if (this.handlers.onComplete) this.handlers.onComplete(data);
                break;
            case "error":
                if (this.handlers.onError) this.handlers.onError(data);
                break;
            default:
                break;
        }
    }

    sendPing() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: "ping" }));
        }
    }

    close() {
        this.closed = true;
        if (this.ws) this.ws.close();
    }
}

export default FabricaWS;