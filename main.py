#!/usr/bin/env python3
"""Fabrica 主入口文件。

负责解析命令行参数、初始化配置和日志系统、启动 uvicorn 服务，
并注册信号处理器实现优雅关闭。

启动命令：
    python main.py              # 默认启动
    python main.py --port 8520  # 指定端口
    python main.py --host 0.0.0.0 --port 9000  # 指定地址和端口
    python main.py --config config/custom.yaml  # 指定配置文件
    python main.py --log-level debug  # 指定日志级别
    python main.py --version    # 显示版本号
    python main.py --help       # 查看帮助
"""

import sys
import os
import argparse
import signal
import threading
import platform

# PyInstaller console=False 时 sys.stdout/stderr 为 None，重定向到 devnull
# 必须在任何 fabrica/aurora 导入之前执行，否则 helios ConsoleHandler 会捕获 None
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')


# ============================================================================
# 路径调整：自动发现 OmniPivot 根目录，插入 aurora/python 路径
# 必须在导入 fabrica 模块之前完成
# ============================================================================
script_path = os.path.abspath(__file__)
path_parts = script_path.split(os.sep)
if 'OmniPivot' in path_parts:
    omnipivot_index = path_parts.index('OmniPivot')
    project_root = os.sep.join(path_parts[:omnipivot_index + 1])
else:
    # 默认向上两级（假设脚本在 nexus/Fabrica/ 下）
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..')
    )

# 插入项目根目录和 aurora/python 路径
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'aurora', 'python'))


# ============================================================================
# 延迟导入：确保 sys.path 已调整
# ============================================================================
def _import_fabrica_modules():
    """延迟导入 fabrica 模块，确保 sys.path 已调整。

    Returns:
        包含 create_app、configure_fabrica、get_config、setup_logging、
        logger、FabricaError 的模块对象元组。
    """
    from fabrica import create_app, __version__
    from fabrica.tool import tool
    from fabrica.utils.config import configure_fabrica, get_config
    from fabrica.utils.exceptions import FabricaError
    from fabrica.utils import setup_logging, get_logger
    return (
        create_app, __version__, configure_fabrica,
        get_config, FabricaError, setup_logging, get_logger, tool,
    )


# ============================================================================
# 参数解析
# ============================================================================

def parse_args():
    """解析命令行参数。

    Returns:
        argparse.Namespace: 解析后的参数。
    """
    # 延迟导入 __version__（需要 sys.path 已调整）
    try:
        from fabrica import __version__ as fabrica_version
    except ImportError:
        fabrica_version = '0.0.0'

    parser = argparse.ArgumentParser(
        description='Fabrica 工具集平台',
    )
    parser.add_argument(
        '--host',
        type=str,
        default=None,
        help='服务监听地址（默认从配置读取，否则 127.0.0.1）',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='服务监听端口（默认从配置读取，否则 8520）',
    )
    parser.add_argument(
        '--config',
        type=str,
        help='指定配置文件路径，覆盖默认配置',
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='info',
        choices=['debug', 'info', 'warning', 'error'],
        help='日志级别（默认: info）',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'fabrica {fabrica_version}',
        help='显示版本号并退出',
    )
    return parser.parse_args()


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数：解析参数 → 初始化配置 → 初始化日志 → 启动服务 → 优雅关闭。

    退出码：
        0: 正常退出
        1: Fabrica 业务异常
        2: 未预期的系统异常
    """
    args = parse_args()

    # 延迟导入 fabrica 模块
    (
        create_app, _version, configure_fabrica,
        get_config, FabricaError, setup_logging, get_logger, tool,
    ) = _import_fabrica_modules()

    try:
        # ---- 1. 初始化配置 ----
        # 配置初始化失败时降级使用默认值，不让程序崩溃
        try:
            configure_fabrica()
        except Exception as config_err:
            print(
                f"警告: 配置初始化失败，使用默认值: {config_err}",
                file=sys.stderr,
            )

        # 如果命令行指定了配置文件，加载它（覆盖默认配置）
        if args.config:
            config_path = os.path.abspath(args.config)
            if not os.path.exists(config_path):
                print(
                    f"错误: 配置文件不存在: {args.config}",
                    file=sys.stderr,
                )
                sys.exit(1)

        # ---- 2. 从配置读取默认 host/port ----
        default_host = get_config('fabrica.server.host', '127.0.0.1')
        default_port = get_config('fabrica.server.port', 8520)

        # 命令行参数覆盖配置值
        host = args.host if args.host is not None else default_host
        port = args.port if args.port is not None else default_port

        # ---- 3. 初始化日志系统 ----
        log_manager = setup_logging()
        logger = get_logger('fabrica')

        logger.info("=" * 60)
        logger.info("Fabrica 工具集平台启动中...")
        logger.info(f"  监听地址: {host}:{port}")
        logger.info(f"  日志级别: {args.log_level}")
        if args.config:
            logger.info(f"  配置文件: {args.config}")
        logger.info("=" * 60)

        # ---- 4. 创建 FastAPI 应用 ----
        app = create_app()

        # ---- 4.0 加载工具插件（触发 @tool.register 注册）----
        # 扫描 fabrica/tools 目录下的工具子包，使平台能识别已注册工具。
        tools_dir = os.path.join(
            project_root, "nexus", "Fabrica", "fabrica", "tools"
        )
        tool.discover([tools_dir])
        logger.info(
            f"已加载工具: {[t.name for t in tool.list_tools()]}"
        )

        # ---- 4.1 初始化 hestia 资源池（CPU 密集型工具调度）----
        tool.init_pool()

        # ---- 5. 创建 uvicorn Server 实例 ----
        # 使用 Server 类而非 uvicorn.run()，以便手动控制信号处理
        import uvicorn
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=args.log_level,
        )
        server = uvicorn.Server(config)

        # ---- 6. 注册信号处理器（优雅关闭）----
        def handle_shutdown(signum, frame):
            """处理 SIGINT/SIGTERM 信号，触发优雅关闭。"""
            logger.info(f"收到信号 {signum}，正在优雅关闭...")
            server.should_exit = True

        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)

        # ---- 7. 判断 dev_mode（桌面窗口 vs 浏览器回退）----
        from fabrica.desktop import (
            launch_window, launch_browser, wait_for_server,
        )

        dev_mode = get_config('fabrica.desktop.dev_mode', False)
        # Linux 开发环境默认回退浏览器模式（pywebview 依赖 GUI 库）
        if platform.system() == 'Linux' and not dev_mode:
            dev_mode = True

        if dev_mode:
            # ---- 7a. 浏览器回退模式 ----
            logger.info("dev_mode 已启用，使用浏览器回退模式")
            launch_browser(host, port)
            logger.info("服务已启动，等待请求...")
            server.run()
        else:
            # ---- 7b. pywebview 桌面窗口模式 ----
            server_thread = threading.Thread(
                target=server.run,
                daemon=True,
                name="uvicorn-server",
            )
            server_thread.start()

            logger.info("等待服务端口就绪...")
            if not wait_for_server(host, port, timeout=10.0):
                logger.error("服务启动超时，无法打开窗口")
                sys.exit(1)

            logger.info("服务已就绪，启动桌面窗口...")

            def on_window_close():
                """窗口关闭回调：触发 uvicorn 优雅停止。"""
                logger.info("桌面窗口已关闭，正在停止服务...")
                server.should_exit = True

            window_title = get_config(
                'fabrica.desktop.window_title', 'Fabrica 工具集平台'
            )
            window_width = get_config('fabrica.desktop.width', 1280)
            window_height = get_config('fabrica.desktop.height', 800)
            window_min_size = tuple(
                get_config('fabrica.desktop.min_size', [1024, 600])
            )

            launch_window(
                host=host,
                port=port,
                title=window_title,
                width=window_width,
                height=window_height,
                min_size=window_min_size,
                on_close=on_window_close,
            )

            # 窗口关闭后，等待服务线程退出
            server_thread.join(timeout=5.0)

        # ---- 8. 优雅关闭资源池 ----
        tool.shutdown()

        logger.info("Fabrica 服务已正常退出")
        sys.exit(0)

    except FabricaError as e:
        logger.error(f"Fabrica 启动失败: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"系统发生未预期错误: {e}", exc_info=True)
        sys.exit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # PyInstaller 打包后 console=False 时，异常输出不可见；
        # 写入 crash.log 便于排查（打包后写到 exe 同级目录）
        import traceback, datetime
        if getattr(sys, 'frozen', False):
            crash_dir = os.path.dirname(sys.executable)
        else:
            crash_dir = os.path.dirname(os.path.abspath(__file__))
        crash_path = os.path.join(crash_dir, 'crash.log')
        with open(crash_path, 'a', encoding='utf-8') as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"Crash at {datetime.datetime.now()}\n")
            f.write(traceback.format_exc())
        raise
