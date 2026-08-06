/**
 * Fabrica SPA 应用入口
 * 初始化路由，绑定主题切换。
 */

import { Router } from "./router.js";

function initTheme() {
    const toggle = document.getElementById("theme-toggle");
    const stored = localStorage.getItem("fabrica-theme");
    if (stored) {
        document.documentElement.setAttribute("data-theme", stored === "dark" ? "dark" : "light");
        if (toggle) toggle.textContent = stored === "dark" ? "☀️" : "🌙";
    }
    if (toggle) {
        toggle.addEventListener("click", () => {
            const isDark = document.documentElement.getAttribute("data-theme") === "dark";
            const next = isDark ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", next);
            toggle.textContent = next === "dark" ? "☀️" : "🌙";
            localStorage.setItem("fabrica-theme", next);
        });
    }
}

function init() {
    initTheme();
    Router.init();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}