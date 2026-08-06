#!/usr/bin/env bash
# ============================================
# Fabrica - 公共函数库
# 提供所有管理脚本共用的路径变量、颜色输出和进程管理函数
# ============================================

set -euo pipefail

# ============================================================================
# 路径变量
# ============================================================================

# 脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 项目根目录（OmniPivot）
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Fabrica 目录
FABRICA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 主脚本路径
MAIN_SCRIPT="$FABRICA_DIR/main.py"

# PID 文件
PID_DIR="$FABRICA_DIR/data/pids"
PID_FILE="$PID_DIR/fabrica.pid"

# 日志文件
LOG_DIR="$FABRICA_DIR/data/logs"
LOG_FILE="$LOG_DIR/fabrica.log"

# ============================================================================
# 颜色输出函数
# ============================================================================

info() {
    echo -e "\033[34m[INFO]\033[0m $1"
}

warn() {
    echo -e "\033[33m[WARN]\033[0m $1"
}

error() {
    echo -e "\033[31m[ERROR]\033[0m $1" >&2
}

success() {
    echo -e "\033[32m[OK]\033[0m $1"
}

# ============================================================================
# 目录初始化
# ============================================================================

init_dirs() {
    mkdir -p "$PID_DIR"
    mkdir -p "$LOG_DIR"
}

# ============================================================================
# 进程管理函数
# ============================================================================

# 获取服务 PID
# 返回: PID 或空字符串
get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

# 检查进程是否运行
# 参数: $1 - PID
# 返回: 0 表示运行中，1 表示未运行
is_running() {
    local pid="$1"
    if [ -z "$pid" ]; then
        return 1
    fi
    kill -0 "$pid" 2>/dev/null
}

# 等待进程退出
# 参数: $1 - PID, $2 - 超时秒数（默认 10）
# 返回: 0 表示已退出，1 表示超时
wait_for_stop() {
    local pid="$1"
    local timeout="${2:-10}"
    local count=0

    while [ $count -lt "$timeout" ]; do
        if ! is_running "$pid"; then
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    return 1
}

# ============================================================================
# 环境检测函数
# ============================================================================

# 检查 Python3 是否可用且版本 >= 3.8
# 返回: 0 表示通过，1 表示失败
check_python() {
    # 检查 python3 命令是否存在
    if ! command -v python3 >/dev/null 2>&1; then
        error "未找到 python3 命令，请安装 Python 3.8+"
        return 1
    fi

    # 检查版本 >= 3.8
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
        local py_version
        py_version=$(python3 --version 2>&1)
        error "Python 版本过低: ${py_version}，需要 3.8+"
        return 1
    fi

    return 0
}

# 检查关键 Python 依赖是否已安装
# 返回: 0 表示通过，1 表示失败
check_deps() {
    # 检查 Fabrica 运行所需的关键依赖
    if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
        error "缺少关键依赖（fastapi/uvicorn）"
        echo "   请运行: bash scripts/dev.sh setup"
        return 1
    fi
    return 0
}
