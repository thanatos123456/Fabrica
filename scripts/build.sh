#!/usr/bin/env bash
# ============================================
# Fabrica - 打包脚本
# 子命令: build / clean
# ============================================
# 注意: PyInstaller 不支持交叉编译，Windows 打包必须在 Windows 环境执行。
# 本脚本为通用 bash，在目标打包环境（Windows Git Bash / WSL / Linux）运行。
# ============================================

set -euo pipefail

# 加载公共函数库
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# spec 文件与产物路径
SPEC_FILE="$FABRICA_DIR/build_win.spec"
DIST_DIR="$FABRICA_DIR/dist"
BUILD_DIR="$FABRICA_DIR/build"
DIST_APP_DIR="$DIST_DIR/fabrica"

# ============================================================================
# 检查 pyinstaller 是否可用
# 返回: 0 表示可用，1 表示不可用
# ============================================================================
check_pyinstaller() {
    if ! command -v pyinstaller >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

# ============================================================================
# 安装 pyinstaller
# ============================================================================
install_pyinstaller() {
    info "安装 PyInstaller..."
    pip install pyinstaller
    success "PyInstaller 安装完成"
}

# ============================================================================
# 执行打包
# 参数: $1 - with_deps (0/1), $2 - make_zip (0/1)
# ============================================================================
do_build() {
    local with_deps="$1"
    local make_zip="$2"

    # 1. 检测 Python
    if ! check_python; then
        exit 1
    fi

    # 2. 检查 spec 文件存在
    if [ ! -f "$SPEC_FILE" ]; then
        error "未找到打包配置: $SPEC_FILE"
        exit 1
    fi

    # 3. 检查/安装 pyinstaller
    if ! check_pyinstaller; then
        if [ "$with_deps" -eq 1 ]; then
            warn "未检测到 PyInstaller，正在自动安装..."
            install_pyinstaller
        else
            error "未检测到 PyInstaller"
            echo "   请先安装: pip install pyinstaller"
            echo "   或使用: bash $(basename "$0") build --with-deps"
            exit 1
        fi
    fi

    # 4. 执行打包
    info "开始打包（onedir 模式）..."
    cd "$FABRICA_DIR"
    pyinstaller build_win.spec --clean

    # 5. 校验产物
    if [ ! -f "$DIST_APP_DIR/fabrica.exe" ] && [ ! -f "$DIST_APP_DIR/fabrica" ]; then
        error "打包产物校验失败: 未找到可执行文件"
        exit 1
    fi
    success "打包完成，产物位于: $DIST_APP_DIR"

    # 6. 可选归档
    if [ "$make_zip" -eq 1 ]; then
        make_zip_archive
    fi
}

# ============================================================================
# 生成 zip 分发包
# ============================================================================
make_zip_archive() {
    local version
    version=$(python3 -c "from fabrica import __version__; print(__version__)" 2>/dev/null \
        || echo "0.1.0")
    local zip_name="fabrica-${version}.zip"
    local zip_path="$DIST_DIR/$zip_name"

    info "生成分发包: $zip_path ..."
    cd "$DIST_DIR"
    if command -v zip >/dev/null 2>&1; then
        zip -r "$zip_name" "fabrica" >/dev/null
    else
        # 无 zip 命令时回退到 Python 打包
        python3 -c "
import shutil
shutil.make_archive('${DIST_DIR}/fabrica-${version}', 'zip', '${DIST_DIR}', 'fabrica')
"
    fi
    success "分发包已生成: $zip_path"
}

# ============================================================================
# 清理构建产物
# ============================================================================
do_clean() {
    info "清理构建产物..."
    local cleaned=0

    if [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
        info "  已删除: $BUILD_DIR"
        cleaned=1
    fi
    if [ -d "$DIST_DIR" ]; then
        rm -rf "$DIST_DIR"
        info "  已删除: $DIST_DIR"
        cleaned=1
    fi

    if [ "$cleaned" -eq 1 ]; then
        success "清理完成"
    else
        info "无残留构建产物，无需清理"
    fi
}

# ============================================================================
# 用法说明
# ============================================================================
print_usage() {
    echo "用法: $(basename "$0") <build|clean> [选项]"
    echo ""
    echo "命令:"
    echo "  build    执行 PyInstaller 打包（onedir 模式）"
    echo "  clean    清理构建产物（build/ dist/）"
    echo ""
    echo "build 选项:"
    echo "  --with-deps   未安装 PyInstaller 时自动安装"
    echo "  --zip         打包完成后生成 zip 分发包"
    echo ""
    echo "示例:"
    echo "  $(basename "$0") build"
    echo "  $(basename "$0") build --with-deps --zip"
    echo "  $(basename "$0") clean"
    echo ""
    echo "注意: PyInstaller 不支持交叉编译，Windows 打包需在 Windows 环境执行"
}

# ============================================================================
# 主函数
# ============================================================================

main() {
    local command="${1:-}"
    shift || true

    local with_deps=0
    local make_zip=0

    if [ "$command" = "build" ]; then
        # 解析 build 选项
        for opt in "$@"; do
            case "$opt" in
                --with-deps)
                    with_deps=1
                    ;;
                --zip)
                    make_zip=1
                    ;;
                *)
                    error "未知选项: $opt"
                    print_usage
                    exit 1
                    ;;
            esac
        done
        do_build "$with_deps" "$make_zip"
    elif [ "$command" = "clean" ]; then
        do_clean
    elif [ "$command" = "" ] || [ "$command" = "-h" ] || [ "$command" = "--help" ]; then
        print_usage
    else
        error "未知命令: $command"
        print_usage
        exit 1
    fi
}

main "$@"