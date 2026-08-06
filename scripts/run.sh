#!/usr/bin/env bash
# ============================================
# Fabrica - 服务管理脚本
# 子命令: start / stop / restart / status
# ============================================

set -euo pipefail

# 加载公共函数库
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# ============================================================================
# 启动服务
# ============================================================================
start_service() {
    init_dirs

    local pid
    pid=$(get_pid)

    if [ -n "$pid" ] && is_running "$pid"; then
        warn "服务已在运行 (PID: $pid)"
        return 1
    fi

    # 清理残留 PID 文件
    rm -f "$PID_FILE"

    info "正在启动 Fabrica 服务..."

    # 后台启动
    cd "$FABRICA_DIR"
    nohup python3 "$MAIN_SCRIPT" >> "$LOG_FILE" 2>&1 &
    local new_pid=$!

    # 等待服务启动
    sleep 2

    if ! is_running "$new_pid"; then
        error "服务启动失败"
        if [ -f "$LOG_FILE" ]; then
            echo "   最近日志:"
            tail -n 5 "$LOG_FILE" | sed 's/^/   /'
        fi
        return 1
    fi

    echo "$new_pid" > "$PID_FILE"
    success "服务已启动 (PID: $new_pid)"
    echo "   日志: $LOG_FILE"
    return 0
}

# ============================================================================
# 停止服务
# ============================================================================
stop_service() {
    local pid
    pid=$(get_pid)

    if [ -z "$pid" ]; then
        warn "未找到 PID 文件，服务可能未在运行"
        # 尝试清理残留进程
        local pids
        pids=$(pgrep -f "python3.*main.py" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            info "发现残留进程，正在清理..."
            echo "$pids" | xargs kill 2>/dev/null || true
        fi
        return 0
    fi

    if ! is_running "$pid"; then
        warn "进程 $pid 已不存在，清理 PID 文件"
        rm -f "$PID_FILE"
        return 0
    fi

    info "正在停止服务 (PID: $pid)..."

    # 发送 SIGINT 信号，让程序优雅退出
    kill -SIGINT "$pid" 2>/dev/null || true

    # 等待进程退出（最多 10 秒）
    if wait_for_stop "$pid" 10; then
        rm -f "$PID_FILE"
        success "服务已停止"
        return 0
    fi

    # 如果仍未退出，强制终止
    warn "服务未响应，强制终止..."
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    success "服务已强制停止"
    return 0
}

# ============================================================================
# 显示服务状态
# ============================================================================
show_status() {
    local pid
    pid=$(get_pid)

    echo "=========================================="
    echo " Fabrica 服务状态"
    echo "=========================================="

    if [ -n "$pid" ] && is_running "$pid"; then
        success "状态: 运行中"
        echo "   PID:  $pid"

        # 显示运行时长
        local uptime
        uptime=$(ps -p "$pid" -o etime= 2>/dev/null | xargs)
        if [ -n "$uptime" ]; then
            echo "   时长: $uptime"
        fi

        # 显示 CPU 和内存使用
        local cpu_mem
        cpu_mem=$(ps -p "$pid" -o %cpu,%mem --no-headers 2>/dev/null)
        if [ -n "$cpu_mem" ]; then
            echo "   资源: CPU/MEM $cpu_mem"
        fi
    else
        error "状态: 未运行"
        if [ -f "$PID_FILE" ]; then
            warn "  (PID 文件残留: $PID_FILE)"
        fi
    fi

    echo ""
}

# ============================================================================
# 主函数
# ============================================================================

main() {
    local command="${1:-}"

    case "$command" in
        start)
            start_service
            ;;
        stop)
            stop_service
            ;;
        restart)
            stop_service
            sleep 1
            start_service
            ;;
        status)
            show_status
            ;;
        ""|-h|--help)
            echo "用法: $(basename "$0") <start|stop|restart|status>"
            echo ""
            echo "命令:"
            echo "  start    启动服务（后台运行）"
            echo "  stop     停止服务（优雅关闭）"
            echo "  restart  重启服务"
            echo "  status   查看服务状态"
            ;;
        *)
            error "未知命令: $command"
            echo "用法: $(basename "$0") <start|stop|restart|status>"
            exit 1
            ;;
    esac
}

main "$@"
