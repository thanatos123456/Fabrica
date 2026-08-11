#!/usr/bin/env bash
# ============================================
# Fabrica - 开发辅助脚本
# 子命令: setup / test / serve
# ============================================

set -euo pipefail

# 加载公共函数库
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# ============================================================================
# 环境初始化
# ============================================================================
setup_env() {
    check_python || return 1

    info "创建虚拟环境..."
    cd "$FABRICA_DIR"
    $PYTHON_CMD -m venv .venv

    info "安装依赖..."
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt

    success "环境初始化完成"
    echo "   虚拟环境: $FABRICA_DIR/.venv"
    echo "   激活命令: source .venv/bin/activate"
}

# ============================================================================
# 运行测试
# ============================================================================
run_tests() {
    check_python || return 1
    info "运行测试..."
    cd "$FABRICA_DIR"
    $PYTHON_CMD -m pytest tests/ -v "$@"
}

# ============================================================================
# 前台启动开发服务器
# ============================================================================
serve_dev() {
    check_python || return 1
    info "启动开发服务器（前台模式）..."
    cd "$FABRICA_DIR"
    $PYTHON_CMD "$MAIN_SCRIPT" "$@"
}

# ============================================================================
# 主函数
# ============================================================================

main() {
    local command="${1:-}"

    case "$command" in
        setup)
            setup_env
            ;;
        test)
            shift
            run_tests "$@"
            ;;
        serve)
            shift
            serve_dev "$@"
            ;;
        ""|-h|--help)
            echo "用法: $(basename "$0") <setup|test|serve> [选项]"
            echo ""
            echo "命令:"
            echo "  setup    创建虚拟环境并安装依赖"
            echo "  test     运行 pytest 测试"
            echo "  serve    前台启动开发服务器"
            echo ""
            echo "示例:"
            echo "  $(basename "$0") setup"
            echo "  $(basename "$0") test"
            echo "  $(basename "$0") serve --port 9000"
            ;;
        *)
            error "未知命令: $command"
            echo "用法: $(basename "$0") <setup|test|serve>"
            exit 1
            ;;
    esac
}

main "$@"
